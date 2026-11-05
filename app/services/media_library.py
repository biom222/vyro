"""Keep newly imported media inside the application's managed storage."""
from __future__ import annotations

import os
import subprocess
import uuid
import json
import hashlib
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models import AppPreference, SessionLocal, Video, utc_now, Project, Post


def store_imported_video(video_id: int, progress_callback: Callable[[int], None] | None = None,
                         source_path: str | Path | None = None, update_record: bool = True) -> Path:
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
            if update_record and video.original_path != str(source):
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
            if update_record:
                video.original_path = str(destination)
                session.commit()
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    if progress_callback:
        progress_callback(100)
    return destination


def inspect_media(video_id: int) -> dict:
    """Cache bounded technical metadata and a thumbnail by source fingerprint."""
    from app.media_process import execute
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError("Видео больше нет в медиатеке.")
        path = Path(video.original_path).resolve()
    stat = path.stat()
    signature = hashlib.sha256(f"media-v1:{path}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:24]
    settings.ensure_directories()
    metadata = settings.cache_folder / f"media-{signature}.json"
    thumbnail = settings.cache_folder / f"thumbnail-{signature}.jpg"
    if metadata.is_file() and thumbnail.is_file():
        try:
            cached = json.loads(metadata.read_text(encoding="utf-8"))
            if (isinstance(cached, dict) and cached.get("path") == str(path)
                    and cached.get("thumbnail") == str(thumbnail)
                    and {"width", "height", "duration", "size", "codec", "fps", "pixel_format", "audio"} <= cached.keys()):
                return cached
        except (ValueError, OSError):
            pass
    payload = json.loads(execute([settings.ffprobe_binary, "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(path)], timeout=30))
    stream = next((v for v in payload["streams"] if v.get("codec_type") == "video"), None)
    if stream is None:
        raise ValueError("В файле не найдена видеодорожка.")
    info = {"path": str(path), "size": stat.st_size, "duration": float(payload["format"].get("duration", 0)),
            "width": stream.get("width", 0), "height": stream.get("height", 0),
            "fps": stream.get("avg_frame_rate", "unknown"), "codec": stream.get("codec_name", "unknown"),
            "pixel_format": stream.get("pix_fmt", "unknown"),
            "audio": any(v.get("codec_type") == "audio" for v in payload["streams"]), "thumbnail": str(thumbnail)}
    temporary = thumbnail.with_name(f"thumbnail-{signature}-{uuid.uuid4().hex}.part.jpg")
    try:
        execute([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", "-ss", "0",
                 "-i", str(path), "-frames:v", "1", "-vf", "scale=240:240:force_original_aspect_ratio=decrease",
                 "-q:v", "4", str(temporary)], timeout=20)
        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            raise OSError("Файл изменился во время анализа. Повторите выбор.")
        os.replace(temporary, thumbnail)
        temporary_json = metadata.with_name(f"media-{signature}-{uuid.uuid4().hex}.part")
        try:
            temporary_json.write_text(json.dumps(info), encoding="utf-8")
            os.replace(temporary_json, metadata)
        finally:
            temporary_json.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)
    return info


def copy_export(source_path, destination, progress=None, control=None) -> Path:
    """Copy off the UI thread; replace the chosen destination only after a full copy."""
    source, target = Path(source_path).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError("Экспорт больше не найден. Повторите обработку.")
    with SessionLocal() as session:
        protected = [Path(value).resolve() for row in session.query(Video.original_path, Video.output_path)
                     for value in row if value]
        protected += [Path(row.value_json).resolve() for row in session.query(AppPreference).filter(
            AppPreference.key.endswith(".previous_output")) if isinstance(row.value_json, str)]
        protected += [Path(row.payload_json["media_path"]).resolve() for row in session.query(Post)
                      if isinstance(row.payload_json, dict) and row.payload_json.get("media_path")]
    if target == source or target in protected:
        raise ValueError("Нельзя перезаписать исходник или используемый приложением экспорт. Выберите другое имя.")
    temporary = target.with_name(f".vyro-{uuid.uuid4().hex}.part")
    before = source.stat()
    copied = 0
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            while chunk := src.read(1024*1024):
                if control:
                    control.check()
                dst.write(chunk)
                copied += len(chunk)
                if progress:
                    progress(min(99, round(copied / max(1, before.st_size) * 100)))
            dst.flush()
            os.fsync(dst.fileno())
        after = source.stat()
        if copied != before.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise OSError("Экспорт изменился во время копирования.")
        if control:
            control.check()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    if progress:
        progress(100)
    return target


def relink_video(video_id: int, new_path: str | Path) -> Path:
    """Validate a replacement source before changing an existing project's link."""
    from app.video_processor import probe_video_metadata
    from app.services.project_state import load_project_state, _store_snapshot, ProjectConflict

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
        original_path, project_id = video.original_path, video.project_id
        if video.status == "processing":
            raise ValueError("Дождитесь завершения обработки видео.")
    loaded = load_project_state(project_id) if project_id else None
    duration, width, height = probe_video_metadata(replacement)
    if expected_duration is not None and abs(duration - expected_duration) > 0.25:
        raise ValueError("Replacement duration does not match the original video")
    if all(expected_size) and expected_size != (width, height):
        raise ValueError("Replacement resolution does not match the original video")
    managed_path = store_imported_video(video_id, source_path=replacement, update_record=False)
    try:
        with SessionLocal.begin() as session:
            video = session.get(Video, video_id)
            if video is None or video.original_path != original_path or video.project_id != project_id or video.status == "processing":
                raise ProjectConflict("Видео изменилось во время перепривязки. Обновите проект и повторите.")
            video.original_path = str(managed_path)
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
                if loaded and loaded.state:
                    _store_snapshot(session, project_id, {**loaded.state, "dirty": True}, loaded.revision)
                project = session.get(Project, video.project_id)
                if project is not None:
                    project.updated_at = utc_now()
    except Exception:
        if (managed_path.resolve() not in {replacement, Path(original_path).resolve()}
                and managed_path.parent.resolve() == settings.upload_folder.resolve()
                and not managed_path.is_symlink()):
            managed_path.unlink(missing_ok=True)
        raise
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
