"""Keep newly imported media inside the application's managed storage."""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models import AppPreference, SessionLocal, Video, utc_now, Project


def store_imported_video(video_id: int, progress_callback: Callable[[int], None] | None = None,
                         source_path: str | Path | None = None) -> Path:
    """Atomically copy a probed source into uploads and update its database path."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        source = Path(source_path or video.original_path).resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Video source is missing: {source}")
    if source.stat().st_size > settings.max_file_size:
        raise ValueError("Video exceeds the configured file size limit")

    uploads = settings.upload_folder.resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    if source.parent == uploads:
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video is None:
                raise ValueError(f"Video {video_id} was removed during import")
            if video.original_path != str(source):
                video.original_path = str(source)
                session.commit()
        if progress_callback:
            progress_callback(100)
        return source

    destination = uploads / f"video-{video_id}-{uuid.uuid4().hex}{source.suffix.lower()}"
    temporary = destination.with_name(destination.name + ".part")
    total = max(source.stat().st_size, 1)
    copied = 0
    try:
        with source.open("rb") as input_file, temporary.open("xb") as output_file:
            while chunk := input_file.read(1024 * 1024):
                output_file.write(chunk)
                copied += len(chunk)
                if progress_callback:
                    progress_callback(min(99, round(copied / total * 100)))
            output_file.flush()
            os.fsync(output_file.fileno())
        if copied != total:
            raise OSError("Video file changed during import")
        os.replace(temporary, destination)
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video is None:
                raise ValueError(f"Video {video_id} was removed during import")
            video.original_path = str(destination)
            session.commit()
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    if progress_callback:
        progress_callback(100)
    return destination


def relink_video(video_id: int, new_path: str | Path) -> Path:
    """Validate a replacement source before changing an existing project's link."""
    from app.video_processor import probe_video_metadata

    replacement = Path(new_path).resolve()
    if not replacement.is_file():
        raise FileNotFoundError(f"Replacement video is missing: {replacement}")
    if replacement.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        raise ValueError("Unsupported replacement video format")
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        expected_duration = video.duration
        expected_size = (video.width, video.height)
    duration, width, height = probe_video_metadata(replacement)
    if expected_duration is not None and abs(duration - expected_duration) > 0.25:
        raise ValueError("Replacement duration does not match the original video")
    if all(expected_size) and expected_size != (width, height):
        raise ValueError("Replacement resolution does not match the original video")
    managed_path = store_imported_video(video_id, source_path=replacement)
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is not None:
            previous_output = video.output_path
            video.status = "uploaded"
            video.error_message = None
            video.output_path = None
            video.output_duration = None
            if previous_output:
                previous = session.get(AppPreference, f"editor.video.{video_id}.previous_output")
                if previous is None:
                    previous = AppPreference(key=f"editor.video.{video_id}.previous_output")
                    session.add(previous)
                previous.value_json = previous_output
            if video.project_id is not None:
                preference = session.get(AppPreference, f"editor.project.{video.project_id}.sequence")
                if preference is not None and isinstance(preference.value_json, dict):
                    preference.value_json = {**preference.value_json, "dirty": True}
                project = session.get(Project, video.project_id)
                if project is not None:
                    project.updated_at = utc_now()
            session.commit()
    return managed_path


def store_project_music(source_path: str | Path,
                        progress_callback: Callable[[int], None] | None = None) -> Path:
    """Copy a selected soundtrack into managed storage without blocking the GUI."""
    source = Path(source_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Music file is missing: {source}")
    if source.suffix.lower() not in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
        raise ValueError("Unsupported music format")
    total = source.stat().st_size
    if total > settings.max_file_size:
        raise ValueError("Music exceeds the configured file size limit")
    try:
        probe = subprocess.run(
            [settings.ffprobe_binary, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(source)],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is not installed") from exc
    if probe.returncode or not probe.stdout.strip():
        raise ValueError("Selected music file has no readable audio stream")
    uploads = settings.upload_folder.resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    if source.parent == uploads:
        if progress_callback:
            progress_callback(100)
        return source
    destination = uploads / f"music-{uuid.uuid4().hex}{source.suffix.lower()}"
    temporary = destination.with_name(destination.name + ".part")
    copied = 0
    try:
        with source.open("rb") as input_file, temporary.open("xb") as output_file:
            while chunk := input_file.read(1024 * 1024):
                output_file.write(chunk)
                copied += len(chunk)
                if progress_callback:
                    progress_callback(min(99, round(copied / max(total, 1) * 100)))
            output_file.flush()
            os.fsync(output_file.fileno())
        if copied != total:
            raise OSError("Music file changed during import")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    if progress_callback:
        progress_callback(100)
    return destination
