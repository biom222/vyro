from __future__ import annotations

from datetime import date, datetime, time, timezone
import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.models import AnalyticsSnapshot, ConnectedAccount, SessionLocal
from app.services.credentials import CredentialStore
from app.services.network import request_with_retry
from app.services.youtube_oauth import get_valid_access_token

logger = logging.getLogger(__name__)


class AnalyticsDataError(RuntimeError):
    """Raised when YouTube Analytics returns an unusable payload."""


class YouTubeAnalyticsClient:
    base_url = "https://youtubeanalytics.googleapis.com/v2"

    def __init__(self, access_token: str | None = None, client: httpx.Client | None = None):
        self.access_token = (access_token or settings.youtube_access_token).strip()
        self._client = client

    def channel_summary(self, start_date: date, end_date: date) -> dict[str, Any]:
        if not self.access_token:
            raise ValueError("A YouTube OAuth access token is required")
        params = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": (
                "views,likes,comments,shares,estimatedMinutesWatched,"
                "subscribersGained,subscribersLost"
            ),
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if self._client is not None:
            response = request_with_retry(
                self._client, "GET", "/reports", params=params, headers=headers
            )
        else:
            with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
                response = request_with_retry(
                    client, "GET", "/reports", params=params, headers=headers
                )
        response.raise_for_status()
        return response.json()


def _metric_map(payload: dict[str, Any]) -> dict[str, float]:
    headers = [item.get("name") for item in payload.get("columnHeaders", [])]
    rows = payload.get("rows")
    if not headers:
        raise AnalyticsDataError("YouTube Analytics response has no column headers")
    if not rows:
        raise AnalyticsDataError("YouTube Analytics returned no data for the selected period")
    row = rows[0]
    if len(row) != len(headers):
        raise AnalyticsDataError("YouTube Analytics row does not match its headers")

    def number(value: Any, metric: str) -> float:
        if value is None or value == "":
            return 0.0
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError) as exc:
            raise AnalyticsDataError(f"Metric {metric} is not numeric: {value!r}") from exc

    return {str(name): number(value, str(name)) for name, value in zip(headers, row)}


def store_youtube_snapshot(
    account_id: int,
    start_date: date,
    end_date: date,
    payload: dict[str, Any],
) -> int:
    metrics = _metric_map(payload)
    period_start = datetime.combine(start_date, time.min, timezone.utc)
    period_end = datetime.combine(end_date, time.max, timezone.utc)
    with SessionLocal() as session:
        account = session.get(ConnectedAccount, account_id)
        if account is None:
            raise ValueError(f"Connected account {account_id} does not exist")
        snapshot = session.scalar(
            select(AnalyticsSnapshot).where(
                AnalyticsSnapshot.account_id == account_id,
                AnalyticsSnapshot.period_start == period_start,
                AnalyticsSnapshot.period_end == period_end,
            )
        )
        if snapshot is None:
            snapshot = AnalyticsSnapshot(
                account_id=account_id,
                period_start=period_start,
                period_end=period_end,
            )
            session.add(snapshot)
        snapshot.views = int(metrics.get("views", 0))
        snapshot.likes = int(metrics.get("likes", 0))
        snapshot.comments = int(metrics.get("comments", 0))
        snapshot.shares = int(metrics.get("shares", 0))
        snapshot.watch_time_minutes = metrics.get("estimatedMinutesWatched", 0.0)
        snapshot.subscribers_gained = int(metrics.get("subscribersGained", 0))
        snapshot.subscribers_lost = int(metrics.get("subscribersLost", 0))
        snapshot.raw_json = payload
        snapshot.raw_schema_version = 1
        snapshot.captured_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(snapshot)
        return snapshot.id


def sync_youtube_analytics(
    account_id: int,
    start_date: date,
    end_date: date,
    client: YouTubeAnalyticsClient | None = None,
    credential_store: CredentialStore | None = None,
    http_client: httpx.Client | None = None,
) -> int:
    analytics_client = client
    if analytics_client is None:
        access_token = get_valid_access_token(
            account_id, credential_store, client=http_client
        )
        analytics_client = YouTubeAnalyticsClient(access_token, client=http_client)
    logger.info(
        "Syncing YouTube analytics for account %s from %s to %s",
        account_id,
        start_date,
        end_date,
    )
    payload = analytics_client.channel_summary(start_date, end_date)
    return store_youtube_snapshot(account_id, start_date, end_date, payload)
