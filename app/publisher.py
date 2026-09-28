from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class PublishingError(RuntimeError):
    """Raised when a publishing request fails."""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.taisly_api_key}"}


def is_mock_mode() -> bool:
    return not bool(settings.taisly_api_key.strip())


def get_platforms() -> list[dict[str, Any]]:
    if is_mock_mode():
        return [
            {"id": "mock-youtube", "platform": "YouTube", "displayName": "Mock YouTube"},
            {"id": "mock-tiktok", "platform": "TikTok", "displayName": "Mock TikTok"},
            {"id": "mock-instagram", "platform": "Instagram", "displayName": "Mock Instagram"},
        ]

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{settings.taisly_base_url.rstrip('/')}/platform/platforms",
            headers=_headers(),
        )
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PublishingError(f"Could not load Taisly platforms: {exc}") from exc
    if not payload.get("success") or not isinstance(payload.get("data"), list):
        raise PublishingError("Taisly returned an invalid platforms response")
    return payload["data"]


def _resolve_platform_id(requested_platform: str, platforms: list[dict[str, Any]]) -> str:
    requested = requested_platform.strip().casefold()
    for platform in platforms:
        platform_id = str(platform.get("id") or platform.get("_id") or "")
        names = {
            platform_id.casefold(),
            str(platform.get("platform", "")).casefold(),
            str(platform.get("displayName", "")).casefold(),
        }
        if requested in names:
            return platform_id
    raise PublishingError(f"No connected Taisly platform matches '{requested_platform}'")


def publish_video(
    video_path: str | Path,
    platform: str,
    title: str,
    description: str,
) -> dict[str, Any]:
    path = Path(video_path)
    if not path.is_file():
        raise PublishingError("Rendered video file does not exist")

    platforms = get_platforms()
    platform_id = _resolve_platform_id(platform, platforms)
    caption = "\n\n".join(part for part in (title.strip(), description.strip()) if part)

    if is_mock_mode():
        logger.info("Published in mock mode: %s -> %s", path.name, platform)
        return {
            "success": True,
            "historyId": f"mock-{platform.lower()}-{path.stem}",
            "result": [{"platformId": platform_id, "status": "SUCCESS"}],
            "mock": True,
        }

    data = {"platforms": json.dumps([platform_id]), "description": caption}
    try:
        with path.open("rb") as video_file, httpx.Client(timeout=300.0) as client:
            response = client.post(
                f"{settings.taisly_base_url.rstrip('/')}/post",
                headers=_headers(),
                data=data,
                files={"video": (path.name, video_file, "video/mp4")},
            )
            response.raise_for_status()
            payload = response.json()
    except (OSError, httpx.HTTPError, ValueError) as exc:
        raise PublishingError(f"Taisly upload failed: {exc}") from exc
    if not payload.get("success") or not payload.get("historyId"):
        raise PublishingError("Taisly rejected the post")
    return payload


def get_post_status(history_id: str) -> dict[str, Any] | None:
    if history_id.startswith("mock-") or is_mock_mode():
        return {"id": history_id, "status": "SUCCESS", "mock": True}

    with httpx.Client(timeout=30.0) as client:
        for page in range(1, 6):
            try:
                response = client.get(
                    f"{settings.taisly_base_url.rstrip('/')}/post/history",
                    headers=_headers(),
                    params={"page": page},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise PublishingError(f"Could not load Taisly post history: {exc}") from exc

            entries = payload.get("data", [])
            for entry in entries:
                if str(entry.get("id")) == history_id:
                    statuses = [str(item.get("status", "PENDING")) for item in entry.get("result", [])]
                    if any(status == "FAILED" for status in statuses):
                        overall = "FAILED"
                    elif statuses and all(status == "SUCCESS" for status in statuses):
                        overall = "SUCCESS"
                    else:
                        overall = "PENDING"
                    return {**entry, "status": overall}
            if len(entries) < 10:
                break
    return None
