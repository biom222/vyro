"""Direct TikTok and Instagram account authorization for the desktop app."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import queue
import secrets
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.config import settings
from app.models import ConnectedAccount, SessionLocal
from app.services.accounts import set_active_account, upsert_account
from app.services.credentials import CredentialStore, get_credential_store

logger = logging.getLogger(__name__)
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_URL = "https://open.tiktokapis.com/v2/user/info/"


def _json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Provider returned an invalid JSON response")
    return payload


def _loopback_code(redirect_uri: str, authorization_url: str, state: str,
                   *, open_browser: bool = True, timeout_seconds: float = 300) -> str:
    redirect = urlparse(redirect_uri)
    if (redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost"}
            or not redirect.port or redirect.query or redirect.fragment):
        raise ValueError("OAuth redirect must be a plain http://localhost or 127.0.0.1 URL with a port")
    outcome: queue.Queue[str | Exception] = queue.Queue(maxsize=1)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
            parsed = urlparse(self.path)
            if parsed.path != redirect.path:
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            returned_state = (query.get("state") or [""])[0]
            error = (query.get("error_description") or query.get("error") or [""])[0]
            code = (query.get("code") or [""])[0]
            if not secrets.compare_digest(returned_state, state):
                result: str | Exception = ValueError("OAuth state mismatch")
            elif error:
                result = RuntimeError(f"Provider authorization failed: {error}")
            elif not code:
                result = ValueError("OAuth callback did not include an authorization code")
            else:
                result = code
            if outcome.empty():
                outcome.put(result)
            title = "Account connected" if isinstance(result, str) else "Connection failed"
            message = "Return to vyro; this tab may be closed." if isinstance(result, str) else str(result)
            body = (f"<!doctype html><meta charset='utf-8'><title>vyro</title>"
                    f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>").encode()
            self.send_response(200 if isinstance(result, str) else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("Social OAuth callback: " + format, *args)

    server = ThreadingHTTPServer((redirect.hostname, redirect.port), Handler)
    server.daemon_threads = True
    server.timeout = 0.5
    try:
        if open_browser and not webbrowser.open(authorization_url):
            logger.warning("Could not open the authorization browser")
        deadline = time.monotonic() + timeout_seconds
        while outcome.empty() and time.monotonic() < deadline:
            server.handle_request()
        if outcome.empty():
            raise TimeoutError("Timed out waiting for account authorization")
        result = outcome.get_nowait()
        if isinstance(result, Exception):
            raise result
        return result
    finally:
        server.server_close()


def _save_bundle(account_id: int, provider: str, bundle: dict[str, Any],
                 store: CredentialStore | None = None) -> None:
    if not str(bundle.get("access_token") or "").strip():
        raise ValueError("Provider did not return an access token")
    reference = f"{provider}:{account_id}:tokens"
    credential_store = store or get_credential_store()
    credential_store.set(reference, json.dumps(bundle))
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        if account is None or account.provider != provider:
            raise ValueError("Connected account is missing or belongs to another provider")
        account.credential_ref = reference
        expires = bundle.get("expires_at")
        account.token_expires_at = datetime.fromisoformat(expires) if expires else None
        account.status = "connected"
        session.commit()


def _expires_at(seconds: Any) -> str:
    try:
        lifetime = max(60, int(seconds))
    except (ValueError, TypeError):
        lifetime = 3600
    return (datetime.now(timezone.utc) + timedelta(seconds=lifetime)).isoformat()


def connect_tiktok(*, open_browser: bool = True, client: httpx.Client | None = None,
                   store: CredentialStore | None = None) -> int:
    if not settings.tiktok_client_key or not settings.tiktok_client_secret:
        raise ValueError("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in .env")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": settings.tiktok_client_key,
        "response_type": "code",
        "scope": "user.info.basic,video.publish",
        "redirect_uri": settings.tiktok_redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    code = _loopback_code(settings.tiktok_redirect_uri, url, state, open_browser=open_browser)
    def complete(http: httpx.Client) -> int:
        tokens = _json(http.post(TIKTOK_TOKEN_URL, data={
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.tiktok_redirect_uri,
            "code_verifier": verifier,
        }))
        access_token = str(tokens.get("access_token") or "")
        granted = set(str(tokens.get("scope") or "").split(","))
        if not {"user.info.basic", "video.publish"}.issubset(granted):
            raise ValueError("TikTok did not grant the required publishing permissions")
        user_payload = _json(http.get(TIKTOK_USER_URL, params={
            "fields": "open_id,display_name,avatar_url",
        }, headers={"Authorization": f"Bearer {access_token}"}))
        error = user_payload.get("error") or {}
        if error.get("code") != "ok":
            raise ValueError(f"TikTok user lookup failed: {error.get('message', 'unknown error')}")
        user = (user_payload.get("data") or {}).get("user") or {}
        open_id = str(user.get("open_id") or tokens.get("open_id") or "")
        if not open_id:
            raise ValueError("TikTok did not return an account ID")
        account_id = upsert_account("tiktok", open_id,
                                    str(user.get("display_name") or open_id),
                                    avatar_url=user.get("avatar_url"))
        _save_bundle(account_id, "tiktok", {
            "access_token": access_token,
            "refresh_token": str(tokens.get("refresh_token") or ""),
            "expires_at": _expires_at(tokens.get("expires_in")),
            "scope": str(tokens.get("scope") or ""),
        }, store)
        set_active_account(account_id)
        return account_id
    if client is not None:
        return complete(client)
    with httpx.Client(timeout=30) as http:
        return complete(http)


def connect_instagram(*, open_browser: bool = True, client: httpx.Client | None = None,
                      store: CredentialStore | None = None) -> list[int]:
    if not settings.instagram_app_id or not settings.instagram_app_secret:
        raise ValueError("Set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET in .env")
    state = secrets.token_urlsafe(32)
    base = f"https://graph.facebook.com/{settings.instagram_graph_version}"
    url = f"https://www.facebook.com/{settings.instagram_graph_version}/dialog/oauth?" + urlencode({
        "client_id": settings.instagram_app_id,
        "redirect_uri": settings.instagram_redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": "pages_show_list,pages_read_engagement,instagram_basic,instagram_content_publish",
    })
    code = _loopback_code(settings.instagram_redirect_uri, url, state,
                          open_browser=open_browser)
    def complete(http: httpx.Client) -> list[int]:
        short = _json(http.get(f"{base}/oauth/access_token", params={
            "client_id": settings.instagram_app_id,
            "client_secret": settings.instagram_app_secret,
            "redirect_uri": settings.instagram_redirect_uri,
            "code": code,
        }))
        long_lived = _json(http.get(f"{base}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.instagram_app_id,
            "client_secret": settings.instagram_app_secret,
            "fb_exchange_token": short["access_token"],
        }))
        pages = _json(http.get(f"{base}/me/accounts", params={
            "fields": "id,name,access_token,instagram_business_account{id,username,name,profile_picture_url}",
            "limit": 100,
        }, headers={"Authorization": f"Bearer {long_lived['access_token']}"}))
        ids: list[int] = []
        for page in pages.get("data") or []:
            instagram = page.get("instagram_business_account") or {}
            ig_id = str(instagram.get("id") or "")
            page_token = str(page.get("access_token") or "")
            if not ig_id or not page_token:
                continue
            account_id = upsert_account("instagram", ig_id,
                str(instagram.get("name") or instagram.get("username") or ig_id),
                username=str(instagram.get("username") or ""),
                avatar_url=instagram.get("profile_picture_url"))
            _save_bundle(account_id, "instagram", {
                "access_token": page_token,
                "page_id": str(page.get("id") or ""),
            }, store)
            ids.append(account_id)
        if not ids:
            raise ValueError("No professional Instagram account linked to an accessible Facebook Page")
        set_active_account(ids[0])
        return ids
    if client is not None:
        return complete(client)
    with httpx.Client(timeout=30) as http:
        return complete(http)


def get_social_access_token(account_id: int, *, store: CredentialStore | None = None,
                            client: httpx.Client | None = None) -> str:
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        if account is None or account.provider not in {"tiktok", "instagram"} or not account.credential_ref:
            raise ValueError("Account is not connected for direct publishing")
        provider, reference = account.provider, account.credential_ref
    credential_store = store or get_credential_store()
    raw = credential_store.get(reference)
    if not raw:
        raise ValueError("Account credentials are unavailable; reconnect the account")
    bundle = json.loads(raw)
    token = str(bundle.get("access_token") or "")
    if not token:
        raise ValueError("Stored account credential has no access token")
    if provider == "instagram":
        return token
    expires_at = datetime.fromisoformat(bundle["expires_at"])
    if expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
        return token
    refresh_token = str(bundle.get("refresh_token") or "")
    if not refresh_token:
        raise ValueError("TikTok refresh token is unavailable; reconnect the account")
    def refresh(http: httpx.Client) -> str:
        payload = _json(http.post(TIKTOK_TOKEN_URL, data={
            "client_key": settings.tiktok_client_key,
            "client_secret": settings.tiktok_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }))
        refreshed = str(payload.get("access_token") or "")
        if not refreshed:
            raise ValueError("TikTok token refresh failed; reconnect the account")
        _save_bundle(account_id, "tiktok", {
            "access_token": refreshed,
            "refresh_token": str(payload.get("refresh_token") or refresh_token),
            "expires_at": _expires_at(payload.get("expires_in")),
            "scope": str(payload.get("scope") or bundle.get("scope") or ""),
        }, credential_store)
        return refreshed
    if client is not None:
        return refresh(client)
    with httpx.Client(timeout=30) as http:
        return refresh(http)
