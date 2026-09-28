"""Upload finished videos to the selected account through official platform APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import ConnectedAccount, SessionLocal
from app.services.social_oauth import get_social_access_token
from app.services.youtube_oauth import get_valid_access_token

TIKTOK_BASE = "https://open.tiktokapis.com/v2/post/publish"


class PublishingError(RuntimeError):
    """A provider rejected the request or returned an invalid response."""


class PublicationUncertain(PublishingError):
    """Upload may have reached a provider; do not automatically send it again."""

    def __init__(self, message: str, external_id: str = "") -> None:
        super().__init__(message)
        self.external_id = external_id


@dataclass(frozen=True, slots=True)
class PublicationResult:
    external_id: str
    status: str  # published or pending
    external_url: str | None = None
    payload: dict[str, Any] | None = None


def _json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise PublishingError("Provider returned an invalid response")
    return payload


def _tiktok_json(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise PublishingError("TikTok returned an invalid response")
    error = payload.get("error") or {}
    if error.get("code") != "ok":
        raise PublishingError(f"TikTok: {error.get('message') or error.get('code') or 'unknown error'}")
    response.raise_for_status()
    return payload.get("data") or {}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _approved_upload_url(url: str, domain: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not (
        parsed.hostname == domain or parsed.hostname.endswith("." + domain)
    ):
        raise PublishingError("Provider returned an untrusted upload URL")
    return url


def get_tiktok_creator_info(account_id: int, *, client: httpx.Client | None = None) -> dict[str, Any]:
    token = get_social_access_token(account_id, client=client)
    def fetch(http: httpx.Client) -> dict[str, Any]:
        data = _tiktok_json(http.post(f"{TIKTOK_BASE}/creator_info/query/",
                                      headers={**_bearer(token), "Content-Type": "application/json; charset=UTF-8"}))
        if not isinstance(data.get("privacy_level_options"), list):
            raise PublishingError("TikTok did not return creator privacy options")
        return data
    if client is not None:
        return fetch(client)
    with httpx.Client(timeout=30) as http:
        return fetch(http)


def _youtube(path: Path, account_id: int, title: str, description: str,
             options: dict[str, Any], http: httpx.Client) -> PublicationResult:
    token = get_valid_access_token(account_id, client=http)
    privacy = str(options.get("youtube_privacy") or "private")
    if privacy not in {"private", "unlisted", "public"}:
        raise PublishingError("Invalid YouTube privacy setting")
    metadata = {
        "snippet": {"title": title or path.stem, "description": description},
        "status": {"privacyStatus": privacy},
    }
    start = http.post("https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={**_bearer(token), "X-Upload-Content-Type": "video/mp4",
                 "X-Upload-Content-Length": str(path.stat().st_size)}, json=metadata)
    start.raise_for_status()
    upload_url = start.headers.get("Location") or ""
    _approved_upload_url(upload_url, "googleapis.com")
    try:
        with path.open("rb") as source:
            result = http.put(upload_url, content=source,
                headers={**_bearer(token), "Content-Type": "video/mp4",
                         "Content-Length": str(path.stat().st_size)})
        payload = _json(result)
    except (httpx.HTTPError, OSError) as exc:
        raise PublicationUncertain("YouTube upload status is uncertain; check the channel before retrying") from exc
    video_id = str(payload.get("id") or "")
    if not video_id:
        raise PublicationUncertain("YouTube did not return a video ID; check the channel before retrying")
    return PublicationResult(video_id, "published", f"https://www.youtube.com/watch?v={video_id}")


def _chunk_layout(size: int) -> tuple[int, int]:
    if size <= 0:
        raise PublishingError("Video file is empty")
    chunk_size = min(size, 32 * 1024 * 1024)
    return chunk_size, max(1, size // chunk_size)


def _tiktok(path: Path, account_id: int, title: str, description: str,
            options: dict[str, Any], http: httpx.Client) -> PublicationResult:
    token = get_social_access_token(account_id, client=http)
    info = get_tiktok_creator_info(account_id, client=http)
    privacy = str(options.get("privacy_level") or "")
    allowed = info.get("privacy_level_options") or []
    if privacy not in allowed:
        raise PublishingError("Select a TikTok privacy option offered for this account")
    size = path.stat().st_size
    chunk_size, count = _chunk_layout(size)
    caption = "\n\n".join(piece for piece in (title.strip(), description.strip()) if piece)
    request = {
        "post_info": {
            "title": caption[:2200],
            "privacy_level": privacy,
            "disable_duet": bool(options.get("disable_duet", False)),
            "disable_comment": bool(options.get("disable_comment", False)),
            "disable_stitch": bool(options.get("disable_stitch", False)),
            "brand_content_toggle": bool(options.get("brand_content_toggle", False)),
            "brand_organic_toggle": bool(options.get("brand_organic_toggle", False)),
            "is_aigc": bool(options.get("is_aigc", False)),
        },
        "source_info": {
            "source": "FILE_UPLOAD", "video_size": size,
            "chunk_size": chunk_size, "total_chunk_count": count,
        },
    }
    data = _tiktok_json(http.post(f"{TIKTOK_BASE}/video/init/",
                              headers=_bearer(token), json=request))
    publish_id = str(data.get("publish_id") or "")
    upload_url = str(data.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise PublishingError("TikTok did not return an upload session")
    _approved_upload_url(upload_url, "tiktokapis.com")
    try:
        with path.open("rb") as source:
            for index in range(count):
                chunk = source.read(chunk_size if index < count - 1 else -1)
                first = source.tell() - len(chunk)
                response = http.put(upload_url, content=chunk, headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {first}-{first + len(chunk) - 1}/{size}",
                })
                response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        raise PublicationUncertain("TikTok upload may be incomplete; inspect its status before retrying",
                                   publish_id) from exc
    return PublicationResult(publish_id, "pending")


def _instagram(path: Path, account_id: int, title: str, description: str,
               http: httpx.Client) -> PublicationResult:
    token = get_social_access_token(account_id, client=http)
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        ig_id = account.external_id if account else ""
    if not ig_id:
        raise PublishingError("Instagram account is missing")
    base = f"https://graph.facebook.com/{settings.instagram_graph_version}"
    caption = "\n\n".join(piece for piece in (title.strip(), description.strip()) if piece)
    created = _json(http.post(f"{base}/{ig_id}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
    }, headers=_bearer(token)))
    container_id = str(created.get("id") or "")
    if not container_id:
        raise PublishingError("Instagram did not return a media container")
    upload_url = created.get("uri") or (
        f"https://rupload.facebook.com/ig-api-upload/{settings.instagram_graph_version}/{container_id}"
    )
    _approved_upload_url(str(upload_url), "facebook.com")
    try:
        with path.open("rb") as source:
            uploaded = http.post(str(upload_url), content=source, headers={
                "Authorization": f"OAuth {token}", "offset": "0",
                "file_size": str(path.stat().st_size),
                "Content-Length": str(path.stat().st_size),
                "Content-Type": "video/mp4",
            })
        _json(uploaded)
    except (httpx.HTTPError, OSError) as exc:
        raise PublicationUncertain("Instagram upload status is uncertain; do not resend automatically",
                                   container_id) from exc
    return PublicationResult(container_id, "pending", payload={"instagram_container_id": container_id})


def publish_direct(account_id: int, video_path: str | Path, title: str,
                   description: str, options: dict[str, Any] | None = None,
                   *, client: httpx.Client | None = None) -> PublicationResult:
    path = Path(video_path)
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise PublishingError("A rendered MP4 file is required")
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        if account is None or account.status != "connected" or not account.credential_ref:
            raise PublishingError("Select and connect a publishing account")
        provider = account.provider
    def publish(http: httpx.Client) -> PublicationResult:
        if provider == "youtube":
            return _youtube(path, account_id, title, description, options or {}, http)
        if provider == "tiktok":
            return _tiktok(path, account_id, title, description, options or {}, http)
        if provider == "instagram":
            return _instagram(path, account_id, title, description, http)
        raise PublishingError(f"Unsupported direct publishing provider: {provider}")
    if client is not None:
        return publish(client)
    with httpx.Client(timeout=300) as http:
        return publish(http)


def check_direct_status(account_id: int, provider: str, external_id: str,
                        *, client: httpx.Client | None = None) -> PublicationResult:
    def check(http: httpx.Client) -> PublicationResult:
        if provider == "youtube":
            return PublicationResult(external_id, "published",
                                     f"https://www.youtube.com/watch?v={external_id}")
        if provider == "tiktok":
            token = get_social_access_token(account_id, client=http)
            data = _tiktok_json(http.post(f"{TIKTOK_BASE}/status/fetch/",
                headers=_bearer(token), json={"publish_id": external_id}))
            status = str(data.get("status") or "")
            if status == "PUBLISH_FAILED":
                raise PublishingError(f"TikTok publication failed: {data.get('fail_reason', 'unknown reason')}")
            return PublicationResult(external_id,
                                     "published" if status == "PUBLISH_COMPLETE" else "pending")
        if provider == "instagram":
            token = get_social_access_token(account_id, client=http)
            base = f"https://graph.facebook.com/{settings.instagram_graph_version}"
            data = _json(http.get(f"{base}/{external_id}",
                params={"fields": "status_code"}, headers=_bearer(token)))
            status = str(data.get("status_code") or "")
            if status in {"ERROR", "EXPIRED"}:
                raise PublishingError(f"Instagram media processing failed: {status}")
            if status not in {"FINISHED", "PUBLISHED"}:
                return PublicationResult(external_id, "pending")
            if status == "PUBLISHED":
                return PublicationResult(external_id, "published")
            with SessionLocal() as session:
                account = session.get(ConnectedAccount, account_id)
                ig_id = account.external_id if account else ""
            try:
                published = _json(http.post(f"{base}/{ig_id}/media_publish",
                    data={"creation_id": external_id}, headers=_bearer(token)))
            except httpx.HTTPError as exc:
                raise PublicationUncertain(
                    "Instagram publish response is uncertain; inspect the account before retrying",
                    external_id,
                ) from exc
            media_id = str(published.get("id") or "")
            if not media_id:
                raise PublicationUncertain("Instagram publish status is uncertain", external_id)
            permalink = None
            try:
                details = _json(http.get(f"{base}/{media_id}",
                    params={"fields": "permalink"}, headers=_bearer(token)))
                candidate = str(details.get("permalink") or "")
                if candidate.startswith("https://www.instagram.com/"):
                    permalink = candidate
            except (httpx.HTTPError, ValueError):
                pass
            return PublicationResult(media_id, "published", permalink)
        raise PublishingError(f"Unsupported provider: {provider}")
    if client is not None:
        return check(client)
    with httpx.Client(timeout=30) as http:
        return check(http)
