from __future__ import annotations

import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

from app.config import settings
from app.models import SessionLocal, Video
from app.publisher import get_platforms
from app.tasks import (
    analyze_video_for_clips,
    probe_video,
    publish_video,
    refresh_trends,
    search_short_clip_trends,
    render_video,
    sync_account_analytics,
)


class ProbeWorker(QThread):
    succeeded = pyqtSignal(float, int, int)
    error = pyqtSignal(str)
    copy_progress = pyqtSignal(int)

    def __init__(self, video_id: int, parent=None):
        super().__init__(parent)
        self.video_id = video_id

    def run(self) -> None:
        try:
            probe_video(self.video_id)
            from app.services.media_library import store_imported_video

            store_imported_video(self.video_id, self.copy_progress.emit)
            with SessionLocal() as session:
                video = session.get(Video, self.video_id)
                if video is None or video.duration is None:
                    raise RuntimeError("Video metadata was not saved")
                self.succeeded.emit(
                    video.duration,
                    video.width or 0,
                    video.height or 0,
                )
        except Exception as exc:
            with SessionLocal() as session:
                video = session.get(Video, self.video_id)
                if video is not None:
                    video.status = "error"
                    video.error_message = str(exc)[:2000]
                    session.commit()
            self.error.emit(str(exc))


class RelinkWorker(QThread):
    succeeded = pyqtSignal(int, str)
    error = pyqtSignal(str)

    def __init__(self, video_id: int, replacement_path: str, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.replacement_path = replacement_path

    def run(self) -> None:
        try:
            from app.services.media_library import relink_video

            managed_path = relink_video(self.video_id, self.replacement_path)
            self.succeeded.emit(self.video_id, str(managed_path))
        except Exception as exc:
            self.error.emit(str(exc))


class AudioImportWorker(QThread):
    progress = pyqtSignal(int)
    succeeded = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, source_path: str, parent=None):
        super().__init__(parent)
        self.source_path = source_path

    def run(self) -> None:
        try:
            from app.services.media_library import store_project_music

            path = store_project_music(self.source_path, self.progress.emit)
            self.succeeded.emit(str(path))
        except Exception as exc:
            self.error.emit(str(exc))


class RenderWorker(QThread):
    progress = pyqtSignal(int)
    succeeded = pyqtSignal(str, float)
    error = pyqtSignal(str)

    def __init__(self, video_id: int, params: dict, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.params = params

    def run(self) -> None:
        try:
            output_path, duration = render_video(
                self.video_id,
                self.params,
                progress_callback=self.progress.emit,
            )
            self.succeeded.emit(output_path, duration)
        except Exception as exc:
            self.error.emit(str(exc))


class PreviewRenderWorker(QThread):
    progress = pyqtSignal(int)
    succeeded = pyqtSignal(str, float)
    error = pyqtSignal(str)

    def __init__(self, video_id: int, params: dict, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self.params = params

    def run(self) -> None:
        try:
            from app.video_processor import render_preview

            output_path, duration = render_preview(self.video_id, self.params, self.progress.emit)
            self.succeeded.emit(output_path, duration)
        except Exception as exc:
            self.error.emit(str(exc))


class PublishWorker(QThread):
    succeeded = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, post_id: int, parent=None):
        super().__init__(parent)
        self.post_id = post_id

    def run(self) -> None:
        try:
            publish_video(self.post_id)
            self.succeeded.emit(self.post_id)
        except Exception as exc:
            self.error.emit(str(exc))


class PlatformWorker(QThread):
    succeeded = pyqtSignal(object)
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.succeeded.emit(get_platforms())
        except Exception as exc:
            self.error.emit(str(exc))


class TranscriptionWorker(QThread):
    progress = pyqtSignal(int)
    succeeded = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, video_id: int, parent=None):
        super().__init__(parent)
        self.video_id = video_id
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            from app.services.transcription import transcribe_video

            transcript_id = transcribe_video(
                self.video_id,
                progress_callback=self.progress.emit,
                is_cancelled=lambda: self._cancelled,
            )
            self.succeeded.emit(transcript_id)
        except Exception as exc:
            self.error.emit(str(exc))


class ContentAnalysisWorker(QThread):
    succeeded = pyqtSignal(object, object)
    error = pyqtSignal(str)

    def __init__(self, project_id: int, video_id: int, parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.video_id = video_id

    def run(self) -> None:
        try:
            pack, candidate_ids = analyze_video_for_clips(
                self.project_id, self.video_id
            )
            self.succeeded.emit(pack, candidate_ids)
        except Exception as exc:
            self.error.emit(str(exc))


class SceneDetectionWorker(QThread):
    succeeded = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, project_id: int, video_id: int, parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.video_id = video_id

    def run(self) -> None:
        try:
            from app.services.scenes import suggest_scenes

            self.succeeded.emit(suggest_scenes(self.project_id, self.video_id))
        except Exception as exc:
            self.error.emit(str(exc))


class TrendRefreshWorker(QThread):
    succeeded = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, query: str | None = None, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self) -> None:
        try:
            self.succeeded.emit(search_short_clip_trends(self.query) if self.query else refresh_trends())
        except Exception as exc:
            self.error.emit(str(exc))


class TrendIdeaWorker(QThread):
    succeeded = pyqtSignal(int, object)
    error = pyqtSignal(str)

    def __init__(self, trend_video_id: int, parent=None):
        super().__init__(parent)
        self.trend_video_id = trend_video_id

    def run(self) -> None:
        try:
            from app.models import ContentIdea, SessionLocal, TrendVideo
            from app.services.ai import get_content_assistant

            with SessionLocal() as session:
                trend = session.get(TrendVideo, self.trend_video_id)
                if trend is None:
                    raise ValueError("Trend video does not exist")
                source = f"{trend.title}\n{trend.description}".strip()
            pack = get_content_assistant().generate(source, 45.0)
            with SessionLocal() as session:
                idea = ContentIdea(
                    trend_video_id=self.trend_video_id,
                    title=pack.title,
                    hook=pack.hooks[0] if pack.hooks else "",
                    format="vertical-short",
                    script=pack.description,
                    score=max((item.score for item in pack.clip_suggestions), default=0.0),
                    copyright_note=pack.copyright_note,
                )
                session.add(idea)
                session.commit()
                session.refresh(idea)
                idea_id = idea.id
            self.succeeded.emit(idea_id, pack.model_dump())
        except Exception as exc:
            self.error.emit(str(exc))


class AnalyticsSyncWorker(QThread):
    succeeded = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, account_id: int, start_date, end_date, parent=None):
        super().__init__(parent)
        self.account_id = account_id
        self.start_date = start_date
        self.end_date = end_date

    def run(self) -> None:
        try:
            snapshot_id = sync_account_analytics(
                self.account_id, self.start_date, self.end_date
            )
            self.succeeded.emit(snapshot_id)
        except Exception as exc:
            self.error.emit(str(exc))


class YouTubeConnectWorker(QThread):
    succeeded = pyqtSignal(object)
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            from app.services.youtube_oauth_server import run_local_youtube_oauth

            self.succeeded.emit(run_local_youtube_oauth())
        except Exception as exc:
            self.error.emit(str(exc))


class PreviewFrameWorker(QThread):
    succeeded = pyqtSignal(bytes, float)
    error = pyqtSignal(str)

    def __init__(self, media_path: str, seconds: float, parent=None):
        super().__init__(parent)
        self.media_path = media_path
        self.seconds = max(0.0, seconds)

    def run(self) -> None:
        command = [
            settings.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{self.seconds:.3f}",
            "-i",
            self.media_path,
            "-frames:v",
            "1",
            "-vf",
            "scale=960:-2",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, check=False, timeout=20,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode != 0 or not completed.stdout:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail or "FFmpeg did not return a preview frame")
            self.succeeded.emit(completed.stdout, self.seconds)
        except Exception as exc:
            self.error.emit(str(exc))
