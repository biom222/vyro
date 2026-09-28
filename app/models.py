from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AppPreference(Base):
    __tablename__ = "app_preferences"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    videos: Mapped[list[Video]] = relationship(back_populates="project")
    clips: Mapped[list[ClipCandidate]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    ideas: Mapped[list[ContentIdea]] = relationship(back_populates="project")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str] = mapped_column(String(1024))
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project | None] = relationship(back_populates="videos")
    edits: Mapped[list[EditParams]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    posts: Mapped[list[Post]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list[Transcript]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    clip_candidates: Mapped[list[ClipCandidate]] = relationship(back_populates="video")


class EditParams(Base):
    __tablename__ = "edit_params"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    start_time: Mapped[float] = mapped_column(Float, default=0.0)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_vertical: Mapped[bool] = mapped_column(Boolean, default=True)
    subtitle_text: Mapped[str] = mapped_column(Text, default="")

    video: Mapped[Video] = relationship(back_populates="edits")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[str] = mapped_column(String(16), default="auto")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    video: Mapped[Video] = relationship(back_populates="transcripts")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.start_time",
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    words_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")


class ClipCandidate(Base):
    __tablename__ = "clip_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="suggested", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project] = relationship(back_populates="clips")
    video: Mapped[Video] = relationship(back_populates="clip_candidates")


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str] = mapped_column(String(255), default="")
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="connected", index=True)
    credential_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    posts: Mapped[list[Post]] = relationship(back_populates="account")
    analytics: Mapped[list[AnalyticsSnapshot]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    video: Mapped[Video] = relationship(back_populates="posts")
    account: Mapped[ConnectedAccount | None] = relationship(back_populates="posts")


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "period_start", "period_end", name="uq_analytics_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE"), index=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    watch_time_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    subscribers_gained: Mapped[int] = mapped_column(Integer, default=0)
    subscribers_lost: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_schema_version: Mapped[int] = mapped_column(Integer, default=1)

    account: Mapped[ConnectedAccount] = relationship(back_populates="analytics")


class TrendVideo(Base):
    __tablename__ = "trend_videos"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), default="youtube", index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    channel_name: Mapped[str] = mapped_column(String(255), default="")
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category: Mapped[str] = mapped_column(String(128), default="")
    region: Mapped[str] = mapped_column(String(8), default="")
    language: Mapped[str] = mapped_column(String(16), default="")
    work_title: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(64), default="unknown")
    copyright_risk: Mapped[str] = mapped_column(String(32), default="unknown")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    snapshots: Mapped[list[TrendSnapshot]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    ideas: Mapped[list[ContentIdea]] = relationship(
        back_populates="trend_video", cascade="all, delete-orphan"
    )


class TrendSnapshot(Base):
    __tablename__ = "trend_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    trend_video_id: Mapped[int] = mapped_column(
        ForeignKey("trend_videos.id", ondelete="CASCADE"), index=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    trend_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_schema_version: Mapped[int] = mapped_column(Integer, default=1)

    video: Mapped[TrendVideo] = relationship(back_populates="snapshots")


class ContentIdea(Base):
    __tablename__ = "content_ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trend_video_id: Mapped[int | None] = mapped_column(
        ForeignKey("trend_videos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    hook: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(128), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="suggested", index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    copyright_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project | None] = relationship(back_populates="ideas")
    trend_video: Mapped[TrendVideo | None] = relationship(back_populates="ideas")


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def prepare_legacy_schema() -> None:
    """Bring a pre-Alembic desktop database to the baseline schema before stamping it."""
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        inspector = inspect(engine)
        video_columns = {column["name"] for column in inspector.get_columns("videos")}
        desktop_columns = {
            "project_id": "INTEGER",
            "width": "INTEGER",
            "height": "INTEGER",
            "output_duration": "FLOAT",
        }
        with engine.begin() as connection:
            for name, sql_type in desktop_columns.items():
                if name not in video_columns:
                    connection.execute(
                        text(f"ALTER TABLE videos ADD COLUMN {name} {sql_type}")
                    )

            post_columns = {column["name"] for column in inspector.get_columns("posts")}
            scheduler_columns = {
                "account_id": "INTEGER",
                "scheduled_at": "DATETIME",
                "published_at": "DATETIME",
                "last_attempt_at": "DATETIME",
                "retry_count": "INTEGER DEFAULT 0",
                "payload_json": "JSON",
            }
            for name, sql_type in scheduler_columns.items():
                if name not in post_columns:
                    connection.execute(
                        text(f"ALTER TABLE posts ADD COLUMN {name} {sql_type}")
                    )

            content_idea_columns = {
                column["name"] for column in inspector.get_columns("content_ideas")
            }
            if "project_id" not in content_idea_columns:
                connection.execute(text("ALTER TABLE content_ideas ADD COLUMN project_id INTEGER"))

            analytics_columns = {
                column["name"] for column in inspector.get_columns("analytics_snapshots")
            }
            if "raw_schema_version" not in analytics_columns:
                connection.execute(
                    text(
                        "ALTER TABLE analytics_snapshots "
                        "ADD COLUMN raw_schema_version INTEGER DEFAULT 1"
                    )
                )

            trend_columns = {
                column["name"] for column in inspector.get_columns("trend_snapshots")
            }
            if "raw_schema_version" not in trend_columns:
                connection.execute(
                    text(
                        "ALTER TABLE trend_snapshots "
                        "ADD COLUMN raw_schema_version INTEGER DEFAULT 1"
                    )
                )


def init_db() -> None:
    """Upgrade the database to the latest Alembic revision."""
    from app.database import upgrade_database

    upgrade_database()
