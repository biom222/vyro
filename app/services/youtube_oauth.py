from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.models import ConnectedAccount, SessionLocal
from app.services.credentials import CredentialStore, get_credential_store
from app.services.network import request_with_retry

logger = logging.getLogger(__name__)


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
)


@dataclass(frozen=True, slots=True)
class OAuthRequest:
    url: str
    state: str
    code_verifier: str
    state_reference: str


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def build_authorization_request(
    store: CredentialStore | None = None,
    persist: bool = True,
) -> OAuthRequest:
    if not settings.youtube_client_id.strip():
        raise ValueError("YOUTUBE_CLIENT_ID is required")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    query = urlencode(
        {
            "client_id": settings.youtube_client_id,
            "redirect_uri": settings.youtube_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    reference = f"youtube:oauth-state:{state}"
    if persist:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        (store or get_credential_store()).set(
            reference,
            json.dumps(
                {
                    "state": state,
                    "code_verifier": verifier,
                    "expires_at": expires_at.isoformat(),
                }
            ),
        )
    return OAuthRequest(
        url=f"{AUTH_URL}?{query}",
        state=state,
        code_verifier=verifier,
        state_reference=reference,
    )


def exchange_code(
    code: str,
    code_verifier: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    data = {
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": settings.youtube_redirect_uri,
    }
    if client is not None:
        response = request_with_retry(client, "POST", TOKEN_URL, data=data)
    else:
        with httpx.Client(timeout=30.0) as local_client:
            response = request_with_retry(local_client, "POST", TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str, client: httpx.Client | None = None) -> dict[str, Any]:
    data = {
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client is not None:
        response = request_with_retry(client, "POST", TOKEN_URL, data=data)
    else:
        with httpx.Client(timeout=30.0) as local_client:
            response = request_with_retry(local_client, "POST", TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


def exchange_callback(
    code: str,
    state: str,
    store: CredentialStore | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    credential_store = store or get_credential_store()
    reference = f"youtube:oauth-state:{state}"
    raw_session = credential_store.get(reference)
    if not raw_session:
        raise ValueError("OAuth state is missing or has already been used")
    try:
        session = json.loads(raw_session)
        expires_at = datetime.fromisoformat(session["expires_at"])
        if session.get("state") != state:
            raise ValueError("OAuth state does not match")
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("OAuth state has expired")
        return exchange_code(code, str(session["code_verifier"]), client)
    finally:
        credential_store.delete(reference)


def _safe_expires_in(value: Any) -> int:
    try:
        return max(60, int(value))
    except (TypeError, ValueError):
        return 3600


def _decode_token_bundle(raw_value: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {"refresh_token": raw_value}
    if not isinstance(payload, dict):
        raise ValueError("Stored OAuth credential has an invalid format")
    return payload


def save_youtube_account_tokens(
    account_id: int,
    token_payload: dict[str, Any],
    store: CredentialStore | None = None,
) -> None:
    credential_store = store or get_credential_store()
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        if account is None:
            raise ValueError(f"Connected account {account_id} does not exist")
        reference = account.credential_ref or f"youtube:{account_id}:tokens"
        existing_raw = credential_store.get(reference)
        existing = _decode_token_bundle(existing_raw) if existing_raw else {}
        refresh_token = str(
            token_payload.get("refresh_token") or existing.get("refresh_token") or ""
        ).strip()
        if not refresh_token:
            raise ValueError("OAuth response did not include a refresh token")
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=_safe_expires_in(token_payload.get("expires_in"))
        )
        bundle = {
            "refresh_token": refresh_token,
            "access_token": str(token_payload.get("access_token") or "").strip(),
            "expires_at": expires_at.isoformat(),
            "token_type": str(token_payload.get("token_type") or "Bearer"),
        }
        credential_store.set(reference, json.dumps(bundle))
        account.credential_ref = reference
        account.token_expires_at = expires_at
        account.status = "connected"
        session.commit()


def get_valid_access_token(
    account_id: int,
    store: CredentialStore | None = None,
    client: httpx.Client | None = None,
) -> str:
    credential_store = store or get_credential_store()
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        if account is None:
            raise ValueError(f"Connected account {account_id} does not exist")
        if not account.credential_ref:
            raise ValueError("Connected account has no stored OAuth credentials")
        reference = account.credential_ref
    raw_bundle = credential_store.get(reference)
    if not raw_bundle:
        raise ValueError("Stored OAuth credentials are unavailable")
    bundle = _decode_token_bundle(raw_bundle)
    access_token = str(bundle.get("access_token") or "").strip()
    expires_raw = bundle.get("expires_at")
    expires_at = datetime.fromisoformat(expires_raw) if expires_raw else None
    if access_token and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        return access_token

    refresh_token = str(bundle.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError("Stored OAuth credentials have no refresh token")
    logger.info("Refreshing YouTube access token for account %s", account_id)
    refreshed = refresh_access_token(refresh_token, client)
    save_youtube_account_tokens(account_id, refreshed, credential_store)
    token = str(refreshed.get("access_token") or "").strip()
    if not token:
        raise ValueError("OAuth refresh response did not include an access token")
    return token
