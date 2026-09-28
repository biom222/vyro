from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Callable

from sqlalchemy import select, update

from app.models import Post, SessionLocal

logger = logging.getLogger(__name__)


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def schedule_post(post_id: int, scheduled_at: datetime) -> None:
    scheduled_at = _utc(scheduled_at)
    with SessionLocal() as session:
        post = session.get(Post, post_id)
        if post is None:
            raise ValueError(f"Post {post_id} does not exist")
        post.scheduled_at = scheduled_at
        post.status = "scheduled"
        post.error_message = None
        session.commit()


def run_due_posts(
    publish: Callable[[int], None],
    now: datetime | None = None,
    limit: int = 10,
    max_retries: int = 3,
    base_backoff_seconds: int = 60,
) -> list[int]:
    current = _utc(now)
    with SessionLocal() as session:
        candidates = list(
            session.scalars(
                select(Post.id)
                .where(Post.status == "scheduled", Post.scheduled_at <= current)
                .order_by(Post.scheduled_at.asc())
                .limit(limit)
            ).all()
        )
        due_ids: list[int] = []
        for post_id in candidates:
            result = session.execute(
                update(Post)
                .where(Post.id == post_id, Post.status == "scheduled")
                .values(status="dispatching", last_attempt_at=current)
            )
            if result.rowcount == 1:
                due_ids.append(post_id)
        session.commit()
    completed: list[int] = []
    for post_id in due_ids:
        try:
            publish(post_id)
            completed.append(post_id)
        except Exception as exc:
            logger.exception("Scheduled publication %s failed", post_id)
            with SessionLocal() as session:
                post = session.get(Post, post_id)
                if post is None:
                    continue
                attempts = post.retry_count or 0
                if post.status == "dispatching":
                    attempts += 1
                post.retry_count = attempts
                post.error_message = str(exc)[:2000]
                if attempts < max_retries:
                    delay = base_backoff_seconds * (2 ** max(0, attempts - 1))
                    post.status = "scheduled"
                    post.scheduled_at = datetime.fromtimestamp(
                        current.timestamp() + delay, timezone.utc
                    )
                else:
                    post.status = "error"
                session.commit()
    return completed
