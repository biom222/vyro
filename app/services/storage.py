"""Conservative startup cleanup of disposable artifacts, never source media."""
from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models import AppPreference, Post, ProjectRevision, SessionLocal, Video

logger = logging.getLogger(__name__)


def cleanup_stale_artifacts(now: float | None = None, minimum_age: float = 86400) -> list[Path]:
    now = time.time() if now is None else now
    protected: set[Path] = set()

    def collect(value):
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str) and "\x00" not in value:
            try:
                path = Path(value)
                if path.is_absolute():
                    protected.add(path.resolve())
            except (OSError, ValueError):
                logger.debug("Non-path value encountered while collecting references")

    try:
        with SessionLocal() as session:
            for video in session.scalars(select(Video)):
                collect(video.original_path)
                collect(video.output_path)
            for preference in session.scalars(select(AppPreference)):
                collect(preference.value_json)
            for revision in session.scalars(select(ProjectRevision)):
                collect(revision.state)
            for post in session.scalars(select(Post)):
                collect(post.payload_json)
    except (SQLAlchemyError, ValueError):
        logger.exception("Cleanup skipped because asset references could not be read safely")
        return []
    removed = []
    for folder in (settings.cache_folder, settings.output_folder, settings.upload_folder):
        root = folder.resolve()
        if not root.is_dir():
            continue
        for candidate in root.iterdir():
            name = candidate.name
            is_temporary = bool(re.fullmatch(r"(?:render|sequence)-\d+-[\w-]+", name))
            is_partial = bool(re.fullmatch(r"(?:video-\d+-|music-)[a-f0-9]+\.[\w.]+\.part", name))
            is_preview = folder == settings.cache_folder and bool(re.fullmatch(r"preview-\d+-[a-f0-9]+\.mp4", name))
            if not (is_temporary or is_partial or is_preview):
                continue
            try:
                if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                    continue
                target = candidate.resolve()
                if target.parent != root or any(path == target or target in path.parents for path in protected):
                    continue
                children = list(candidate.rglob("*")) if candidate.is_dir() else []
                if any(item.is_symlink() or getattr(item, "is_junction", lambda: False)() for item in children):
                    continue
                if any(not item.resolve().is_relative_to(root) for item in children):
                    continue
                latest = max([candidate.stat().st_mtime] + [item.stat().st_mtime for item in children])
                if now - latest < minimum_age:
                    continue
                if candidate.is_dir() and is_temporary:
                    shutil.rmtree(target)
                elif candidate.is_file() and (is_partial or is_preview):
                    candidate.unlink()
                else:
                    continue
                removed.append(target)
            except OSError:
                logger.warning("Could not clean disposable artifact %s", candidate, exc_info=True)
    return removed
