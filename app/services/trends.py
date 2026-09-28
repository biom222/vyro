from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.models import SessionLocal, TrendSnapshot, TrendVideo
from app.services.copyright import assess_copyright_risk
from app.services.network import request_with_retry

logger = logging.getLogger(__name__)


def _short_duration(value: str) -> bool:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if match is None:
        return False
    hours, minutes, seconds = (int(item or 0) for item in match.groups())
    return 3 <= hours * 3600 + minutes * 60 + seconds <= 90


def calculate_trend_score(
    views: int,
    likes: int,
    comments: int,
    published_at: datetime | None,
    now: datetime | None = None,
) -> float:
    current = now or datetime.now(timezone.utc)
    if published_at is None:
        age_hours = 168.0
    else:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age_hours = max(1.0, (current - published_at).total_seconds() / 3600)
    engagement = min(0.25, (likes + comments * 2) / max(views, 1))
    daily_velocity = views / max(age_hours / 24, 1)
    popularity_score = math.log10(max(views, 1)) * 12
    velocity_score = math.log10(1 + max(daily_velocity, 0)) * 8
    engagement_score = engagement * 160
    freshness_score = max(0.0, 20.0 - age_hours / 12)
    return round(popularity_score + velocity_score + engagement_score + freshness_score, 2)


class YouTubeTrendClient:
    base_url = "https://www.googleapis.com/youtube/v3"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    def fetch_popular(self, limit: int = 25) -> list[dict[str, Any]]:
        if not settings.youtube_api_key.strip():
            raise ValueError("YOUTUBE_API_KEY is required for live trend discovery")
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": settings.youtube_region,
            "maxResults": max(1, min(limit, 50)),
            "key": settings.youtube_api_key,
        }
        if self._client is not None:
            response = request_with_retry(self._client, "GET", "/videos", params=params)
        else:
            with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
                response = request_with_retry(client, "GET", "/videos", params=params)
        response.raise_for_status()
        return list(response.json().get("items", []))

    def search_short_videos(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """Discover recent short videos, then fetch their actual public statistics."""
        clean_query = " ".join(query.split())[:120]
        if not clean_query:
            raise ValueError("Enter a topic or a film/series title")
        if not settings.youtube_api_key:
            raise ValueError("YOUTUBE_API_KEY is required for live clip discovery")
        after = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        search_params = {
            "part": "snippet", "q": clean_query, "type": "video", "videoDuration": "short",
            "order": "viewCount", "publishedAfter": after,
            "regionCode": settings.youtube_region,
            "relevanceLanguage": settings.youtube_language,
            "maxResults": max(1, min(limit, 50)), "key": settings.youtube_api_key,
        }
        def fetch(client: httpx.Client) -> list[dict[str, Any]]:
            search_response = request_with_retry(client, "GET", "/search", params=search_params)
            search_response.raise_for_status()
            ids = [str(item.get("id", {}).get("videoId", "")) for item in search_response.json().get("items", [])]
            ids = [item for item in ids if item]
            if not ids:
                return []
            response = request_with_retry(client, "GET", "/videos", params={
                "part": "snippet,statistics,contentDetails", "id": ",".join(ids),
                "maxResults": len(ids), "key": settings.youtube_api_key,
            })
            response.raise_for_status()
            items = [item for item in response.json().get("items", [])
                     if _short_duration(str(item.get("contentDetails", {}).get("duration", "")))]
            for item in items:
                item["_content_type"] = "short_clip_search"
            return items
        if self._client is not None:
            return fetch(self._client)
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            return fetch(client)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _safe_int(value: Any) -> int:
    try:
        return int(str(value or 0).replace(",", "").strip())
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric YouTube statistic: %r", value)
        return 0


def _mock_items() -> list[dict[str, Any]]:
    published_at = (datetime.now(timezone.utc) - timedelta(hours=18)).isoformat().replace(
        "+00:00", "Z"
    )
    return [
        {
            "id": "mock-trend-1",
            "snippet": {
                "title": "Как устроен сильный хук в коротком видео",
                "description": "Synthetic trend fixture for local development.",
                "channelTitle": "Shorts Lab",
                "publishedAt": published_at,
                "categoryId": "27",
                "thumbnails": {"high": {"url": ""}},
            },
            "statistics": {"viewCount": "150000", "likeCount": "12000", "commentCount": "830"},
        }
    ]


def refresh_youtube_trends(
    client: YouTubeTrendClient | None = None,
    items: list[dict[str, Any]] | None = None,
) -> list[int]:
    source_items = items
    if source_items is None:
        source_items = _mock_items() if settings.trends_mock_mode else (client or YouTubeTrendClient()).fetch_popular()
    saved_ids: list[int] = []
    with SessionLocal() as session:
        for item in source_items:
            external_id = str(item.get("id", "")).strip()
            if not external_id:
                continue
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            video = session.scalar(
                select(TrendVideo).where(
                    TrendVideo.provider == "youtube", TrendVideo.external_id == external_id
                )
            )
            if video is None:
                video = TrendVideo(
                    provider="youtube",
                    external_id=external_id,
                    url=f"https://www.youtube.com/watch?v={external_id}",
                    title=str(snippet.get("title", "Untitled")),
                )
                session.add(video)
            video.title = str(snippet.get("title", video.title))
            video.description = str(snippet.get("description", ""))
            video.channel_name = str(snippet.get("channelTitle", ""))
            video.category = str(snippet.get("categoryId", ""))
            video.region = settings.youtube_region
            video.language = settings.youtube_language
            video.content_type = str(item.get("_content_type") or "unknown")
            video.thumbnail_url = str(
                snippet.get("thumbnails", {}).get("high", {}).get("url", "")
            ) or None
            video.published_at = _parse_datetime(snippet.get("publishedAt"))
            assessment = assess_copyright_risk(video.title, video.description)
            video.copyright_risk = assessment.level
            views = _safe_int(statistics.get("viewCount"))
            likes = _safe_int(statistics.get("likeCount"))
            comments = _safe_int(statistics.get("commentCount"))
            session.flush()
            score = calculate_trend_score(views, likes, comments, video.published_at)
            latest = session.scalar(
                select(TrendSnapshot)
                .where(TrendSnapshot.trend_video_id == video.id)
                .order_by(TrendSnapshot.captured_at.desc())
                .limit(1)
            )
            if (
                latest
                and latest.views == views
                and latest.likes == likes
                and latest.comments == comments
            ):
                latest.trend_score = score
                latest.raw_json = item
                latest.raw_schema_version = 1
            else:
                session.add(
                    TrendSnapshot(
                    trend_video_id=video.id,
                    views=views,
                    likes=likes,
                    comments=comments,
                    trend_score=score,
                    raw_json=item,
                    raw_schema_version=1,
                    )
                )
            saved_ids.append(video.id)
        session.commit()
    return saved_ids


def refresh_short_clip_trends(query: str, client: YouTubeTrendClient | None = None) -> list[int]:
    return refresh_youtube_trends(items=(client or YouTubeTrendClient()).search_short_videos(query))
