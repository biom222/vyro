from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import update

from app.config import settings
from app.models import ConnectedAccount, Post, SessionLocal, Video
from app.services.direct_publishing import (
    PublicationUncertain,
    check_direct_status,
    publish_direct,
)
from app.video_processor import (
    probe_duration,
    probe_video_metadata,
    render_video as process_video,
)

logger = logging.getLogger(__name__)


def probe_video(video_id: int) -> None:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        video.status = "processing"
        video.error_message = None
        session.commit()
        original_path = video.original_path

    try:
        if not Path(original_path).is_file():
            raise FileNotFoundError(f"Video file does not exist: {original_path}")
        duration, width, height = probe_video_metadata(original_path)
        if duration > settings.max_video_duration:
            raise ValueError(
                f"Video is {duration:.1f}s long; the editor limit is "
                f"{settings.max_video_duration:.0f}s"
            )
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video:
                video.duration = duration
                video.width = width
                video.height = height
                video.status = "uploaded"
                video.error_message = None
                session.commit()
    except Exception as exc:
        logger.exception("Video probing failed for video %s", video_id)
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video:
                video.status = "error"
                video.error_message = str(exc)[:2000]
                session.commit()
        raise


def render_video(
    video_id: int,
    params: dict[str, Any],
    progress_callback: Callable[[int], None] | None = None,
) -> tuple[str, float]:
    old_output: str | None = None
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        video.status = "processing"
        video.error_message = None
        old_output = video.output_path
        session.commit()

    try:
        output_path, duration = process_video(video_id, params, progress_callback)
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video:
                video.output_path = output_path
                video.output_duration = duration
                video.status = "ready"
                video.error_message = None
                session.commit()
        if old_output and old_output != output_path:
            try:
                Path(old_output).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove previous output %s", old_output)
        return output_path, duration
    except Exception as exc:
        logger.exception("Rendering failed for video %s", video_id)
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video:
                video.status = "error"
                video.error_message = str(exc)[:2000]
                session.commit()
        raise


def _claim_post_for_publication(post_id: int) -> None:
    with SessionLocal() as session:
        claimed = session.execute(
            update(Post)
            .where(
                Post.id == post_id,
                Post.status.in_(("queued", "scheduled", "dispatching", "error")),
            )
            .values(
                status="publishing",
                error_message=None,
                last_attempt_at=datetime.now(timezone.utc),
            )
        )
        if claimed.rowcount != 1:
            existing = session.get(Post, post_id)
            if existing is None:
                raise ValueError(f"Post {post_id} does not exist")
            raise ValueError(
                f"Post {post_id} cannot be published from status '{existing.status}'"
            )
        session.commit()


def publish_video(post_id: int) -> None:
    _claim_post_for_publication(post_id)
    try:
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            account = session.get(ConnectedAccount, post.account_id) if post.account_id else None
            if account is None or account.status != "connected" or not account.credential_ref:
                raise ValueError("Post has no connected direct-publishing account")
            if post.platform != account.provider:
                raise ValueError("Post platform does not match its selected account")
            video = session.get(Video, post.video_id)
            if video is None or video.status != "ready" or not video.output_path:
                raise ValueError("Video is not ready for publishing")

            publish_duration = video.output_duration or probe_duration(video.output_path)
            if not 3 <= publish_duration <= settings.max_video_duration:
                raise ValueError("Video duration is outside the supported editor range")

            values = (account.id, video.output_path, post.title, post.description,
                      post.payload_json or {})

        result = publish_direct(*values)
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            if post:
                post.status = result.status
                post.external_id = result.external_id
                post.external_url = result.external_url
                if result.payload:
                    post.payload_json = {**(post.payload_json or {}), **result.payload}
                if result.status == "published":
                    post.published_at = datetime.now(timezone.utc)
                post.error_message = None
                session.commit()
    except PublicationUncertain as exc:
        logger.exception("Publication state is uncertain for post %s", post_id)
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            if post:
                post.status = "unknown"
                post.external_id = exc.external_id or None
                post.error_message = str(exc)[:2000]
                session.commit()
        raise
    except Exception as exc:
        logger.exception("Publishing failed for post %s", post_id)
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            if post:
                post.status = "error"
                post.error_message = str(exc)[:2000]
                post.retry_count = (post.retry_count or 0) + 1
                post.last_attempt_at = datetime.now(timezone.utc)
                session.commit()
        raise


def refresh_publication(post_id: int) -> str:
    """Poll a pending provider publication without creating a second upload."""
    with SessionLocal() as session:
        post = session.get(Post, post_id)
        if post is None or post.status not in {"pending", "unknown"}:
            raise ValueError("Post is not waiting for a provider result")
        if not post.account_id or not post.external_id:
            raise ValueError("Provider did not return an ID; check the account manually")
        values = (post.account_id, post.platform, post.external_id)
    result = check_direct_status(*values)
    with SessionLocal() as session:
        post = session.get(Post, post_id)
        if post is not None:
            post.status = result.status
            post.external_id = result.external_id
            post.external_url = result.external_url
            post.error_message = None
            if result.status == "published":
                post.published_at = datetime.now(timezone.utc)
            session.commit()
    return result.status


def transcribe_video(video_id: int) -> int:
    """Create and persist a timed transcript for a local video."""
    from app.services.transcription import transcribe_video as transcribe

    return transcribe(video_id)


def analyze_video_for_clips(project_id: int, video_id: int) -> tuple[dict[str, Any], list[int]]:
    """Generate a content pack and persist validated clip candidates."""
    from app.services.content_pipeline import analyze_video_for_clips as analyze

    pack, candidate_ids = analyze(project_id, video_id)
    return pack.model_dump(), candidate_ids


def refresh_trends() -> list[int]:
    """Fetch or generate the latest trend snapshots."""
    from app.services.trends import refresh_youtube_trends

    return refresh_youtube_trends()


def search_short_clip_trends(query: str) -> list[int]:
    from app.services.trends import refresh_short_clip_trends

    return refresh_short_clip_trends(query)


def sync_account_analytics(account_id: int, start_date: date, end_date: date) -> int:
    """Fetch a YouTube Analytics summary and persist it."""
    from app.services.analytics import sync_youtube_analytics

    return sync_youtube_analytics(account_id, start_date, end_date)


def run_scheduled_publications(now: datetime | None = None) -> list[int]:
    """Publish all due posts. Intended to be called by a lightweight local timer."""
    from app.services.scheduler import run_due_posts

    return run_due_posts(
        publish_video,
        now=now,
        limit=settings.scheduler_batch_size,
    )
