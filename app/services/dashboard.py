from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from app.models import AnalyticsSnapshot, Post, Project, SessionLocal, Video
from app.services.accounts import get_active_account_id


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    active_account_id: int | None
    views: int
    views_change: int
    likes: int
    comments: int
    shares: int
    watch_time_minutes: float
    subscribers_net: int
    projects: int
    ready_videos: int
    scheduled_posts: int
    published_posts: int


def get_dashboard_summary(account_id: int | None = None) -> DashboardSummary:
    selected_account = account_id if account_id is not None else get_active_account_id()
    with SessionLocal() as session:
        snapshots: list[AnalyticsSnapshot] = []
        if selected_account is not None:
            snapshots = list(
                session.scalars(
                    select(AnalyticsSnapshot)
                    .where(AnalyticsSnapshot.account_id == selected_account)
                    .order_by(AnalyticsSnapshot.captured_at.desc())
                    .limit(2)
                ).all()
            )
        latest = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None

        def count(model, criterion=None) -> int:
            query = select(func.count()).select_from(model)
            if criterion is not None:
                query = query.where(criterion)
            return int(session.scalar(query) or 0)

        return DashboardSummary(
            active_account_id=selected_account,
            views=latest.views if latest else 0,
            views_change=(latest.views - previous.views) if latest and previous else 0,
            likes=latest.likes if latest else 0,
            comments=latest.comments if latest else 0,
            shares=latest.shares if latest else 0,
            watch_time_minutes=latest.watch_time_minutes if latest else 0.0,
            subscribers_net=(
                latest.subscribers_gained - latest.subscribers_lost if latest else 0
            ),
            projects=count(Project),
            ready_videos=count(Video, Video.status == "ready"),
            scheduled_posts=count(Post, Post.status == "scheduled"),
            published_posts=count(Post, Post.status == "published"),
        )
