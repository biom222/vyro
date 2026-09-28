from __future__ import annotations

import html
import logging
import queue
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import settings
from app.services.accounts import set_active_account, upsert_account
from app.services.credentials import CredentialStore, get_credential_store
from app.services.network import request_with_retry
from app.services.youtube_oauth import (
    OAuthRequest,
    build_authorization_request,
    exchange_callback,
    save_youtube_account_tokens,
)

logger = logging.getLogger(__name__)

YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


@dataclass(frozen=True, slots=True)
class YouTubeConnectionResult:
    account_id: int
    channel_id: str
    display_name: str
    username: str


def fetch_current_channel(
    access_token: str,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"part": "id,snippet", "mine": "true"}
    if client is not None:
        response = request_with_retry(
            client, "GET", YOUTUBE_CHANNELS_URL, headers=headers, params=params
        )
    else:
        with httpx.Client(timeout=30.0) as local_client:
            response = request_with_retry(
                local_client, "GET", YOUTUBE_CHANNELS_URL, headers=headers, params=params
            )
    response.raise_for_status()
    items = response.json().get("items") or []
    if not items:
        raise RuntimeError("Google account has no accessible YouTube channel")
    item = items[0]
    snippet = item.get("snippet") or {}
    channel_id = str(item.get("id") or "").strip()
    if not channel_id:
        raise RuntimeError("YouTube channel response has no channel ID")
    custom_url = str(snippet.get("customUrl") or "").strip()
    return {
        "channel_id": channel_id,
        "display_name": str(snippet.get("title") or channel_id).strip(),
        "username": custom_url,
        "avatar_url": str(
            (snippet.get("thumbnails") or {}).get("default", {}).get("url") or ""
        ).strip(),
    }


def complete_youtube_oauth(
    code: str,
    state: str,
    store: CredentialStore | None = None,
    client: httpx.Client | None = None,
) -> YouTubeConnectionResult:
    credential_store = store or get_credential_store()
    token_payload = exchange_callback(code, state, credential_store, client)
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("OAuth response did not contain an access token")
    channel = fetch_current_channel(access_token, client)
    account_id = upsert_account(
        provider="youtube",
        external_id=channel["channel_id"],
        display_name=channel["display_name"],
        username=channel["username"],
        avatar_url=channel["avatar_url"] or None,
    )
    save_youtube_account_tokens(account_id, token_payload, credential_store)
    set_active_account(account_id)
    logger.info("Connected YouTube channel %s", channel["channel_id"])
    return YouTubeConnectionResult(
        account_id=account_id,
        channel_id=channel["channel_id"],
        display_name=channel["display_name"],
        username=channel["username"],
    )


def _write_html(handler: BaseHTTPRequestHandler, status: int, title: str, message: str) -> None:
    body = (
        "<!doctype html><html><head><meta charset='utf-8'><title>vyro</title>"
        "<style>body{font-family:system-ui;background:#15171c;color:#eee;max-width:680px;"
        "margin:80px auto;padding:24px}h1{color:#7cc7ff}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
        "<p>Это окно можно закрыть.</p></body></html>"
    ).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def run_local_youtube_oauth(
    *,
    open_browser: bool = True,
    timeout_seconds: float = 300.0,
    store: CredentialStore | None = None,
    client: httpx.Client | None = None,
) -> YouTubeConnectionResult:
    credential_store = store or get_credential_store()
    request: OAuthRequest = build_authorization_request(credential_store)
    redirect = urlparse(settings.youtube_redirect_uri)
    if redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("YOUTUBE_REDIRECT_URI must use http://127.0.0.1 or http://localhost")
    if not redirect.port:
        raise ValueError("YOUTUBE_REDIRECT_URI must include a local port")
    callback_path = redirect.path or "/"
    outcomes: queue.Queue[YouTubeConnectionResult | Exception] = queue.Queue(maxsize=1)

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path != callback_path:
                _write_html(self, 404, "Не найдено", "Неизвестный OAuth callback path.")
                return
            query = parse_qs(parsed.query)
            provider_error = (query.get("error") or [""])[0]
            if provider_error:
                error = RuntimeError(f"Google OAuth error: {provider_error}")
                outcomes.put(error)
                _write_html(self, 400, "Подключение отменено", str(error))
                return
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            try:
                if not code or not state:
                    raise ValueError("OAuth callback has no code or state")
                result = complete_youtube_oauth(
                    code, state, credential_store, client
                )
            except Exception as exc:
                logger.exception("YouTube OAuth callback failed")
                outcomes.put(exc)
                _write_html(self, 400, "Ошибка подключения", str(exc))
            else:
                outcomes.put(result)
                _write_html(
                    self,
                    200,
                    "YouTube подключён",
                    f"Канал «{result.display_name}» успешно подключён к vyro.",
                )

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("OAuth callback: " + format, *args)

    server = ThreadingHTTPServer((redirect.hostname, redirect.port), CallbackHandler)
    server.daemon_threads = True
    server.timeout = 0.5
    try:
        logger.info("Waiting for YouTube OAuth callback at %s", settings.youtube_redirect_uri)
        if open_browser:
            if not webbrowser.open(request.url):
                logger.warning("Could not open a browser automatically: %s", request.url)
        else:
            logger.info("Open this authorization URL: %s", request.url)
        deadline = time.monotonic() + timeout_seconds
        while outcomes.empty() and time.monotonic() < deadline:
            server.handle_request()
        if outcomes.empty():
            credential_store.delete(request.state_reference)
            raise TimeoutError("Timed out waiting for YouTube OAuth callback")
        outcome = outcomes.get_nowait()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    finally:
        server.server_close()
