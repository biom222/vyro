"""Transactional drafts backed by a bounded history of validated snapshots."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select, update, text

from app.models import AppPreference, Project, ProjectRevision, SessionLocal, Video, utc_now


class ProjectStateError(ValueError):
    pass


class ProjectConflict(ProjectStateError):
    pass


@dataclass(frozen=True)
class LoadedDraft:
    state: dict
    revision: int
    recovered: bool = False
    missing_files: tuple[str, ...] = ()


def draft_key(project_id: int) -> str:
    return f"editor.project.{project_id}.sequence"


def checksum(state: dict) -> str:
    try:
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ProjectStateError("Состояние проекта содержит недопустимые значения.") from exc
    if len(encoded) > 5_000_000:
        raise ProjectStateError("Состояние проекта превышает допустимый размер.")
    return hashlib.sha256(encoded).hexdigest()


def _validate(session, project_id: int, state: dict) -> tuple[str, ...]:
    if not isinstance(state, dict) or state.get("schema_version", 1) != 1:
        raise ProjectStateError("Формат проекта не поддерживается этой версией vyro.")
    checksum(state)
    clips = state.get("clips", [])
    if not isinstance(clips, list) or not 1 <= len(clips) <= 30:
        raise ProjectStateError("Проект должен содержать от 1 до 30 клипов.")
    members = {video.id: video for video in session.scalars(select(Video).where(Video.project_id == project_id))}
    if state.get("primary_id") not in members:
        raise ProjectStateError("Основное видео не принадлежит этому проекту.")
    missing = []
    for clip in clips:
        if not isinstance(clip, dict) or clip.get("video_id") not in members:
            raise ProjectStateError("В проекте обнаружена неверная ссылка на клип.")
        video = members[clip["video_id"]]
        try:
            start, end = float(clip["start_time"]), float(clip["end_time"])
            if not math.isfinite(start + end) or not 0 <= start < end <= (video.duration or end) + 0.05:
                raise ValueError("Invalid range")
        except (KeyError, ValueError, TypeError) as exc:
            raise ProjectStateError("В проекте обнаружен неверный диапазон обрезки.") from exc
        if not Path(video.original_path).is_file():
            missing.append(video.original_path)
    for key, maximum in (("title_layers", 8), ("video_layers", 4)):
        layers = state.get(key, [])
        if not isinstance(layers, list) or len(layers) > maximum or any(not isinstance(item, dict) for item in layers):
            raise ProjectStateError("Повреждены данные монтажных слоёв.")
    if any(item.get("video_id") not in members for item in state.get("video_layers", [])):
        raise ProjectStateError("Видеослой ссылается на другой проект.")
    music = state.get("music_path") or ""
    if not isinstance(music, str) or "\x00" in music or (music and not Path(music).is_absolute()):
        raise ProjectStateError("Путь к музыке должен быть полным путём к файлу.")
    if music and not Path(music).is_file():
        missing.append(music)
    if not isinstance(state.get("editor", {}), dict) or not isinstance(state.get("publication", {}), dict):
        raise ProjectStateError("Повреждены настройки проекта.")
    def number(value, low=0, high=1_000_000):
        try:
            result = float(value)
            if not math.isfinite(result) or not low <= result <= high:
                raise ValueError("Number outside range")
            return result
        except (TypeError, ValueError) as exc:
            raise ProjectStateError("В настройках проекта обнаружено неверное числовое значение.") from exc
    number(state.get("active_index", 0), 0, len(clips) - 1)
    number(state.get("playhead", 0))
    number(state.get("music_volume", 0.25), 0, 1)
    number(state.get("transition_duration", 0.5), 0, 10)
    if state.get("transition", "cut") not in {"cut", "dissolve"}:
        raise ProjectStateError("Неизвестный тип перехода в проекте.")
    editor = state.get("editor", {})
    if str(editor.get("fps", "30")) not in {"source", "24", "25", "30", "50", "60"}:
        raise ProjectStateError("Неподдерживаемая частота кадров проекта.")
    if editor.get("quality", "standard") not in {"standard", "high"}:
        raise ProjectStateError("Неподдерживаемое качество экспорта.")
    number(editor.get("crop_position", 0.5), 0, 1)
    number(editor.get("font_size", 64), 1, 400)
    for layer in state.get("title_layers", []) + state.get("video_layers", []):
        for key in ("start", "end", "source_start", "font_size", "width", "x", "y", "opacity"):
            if key in layer:
                number(layer[key])
        keys = layer.get("keyframes", [])
        if not isinstance(keys, list) or any(not isinstance(item, dict) for item in keys):
            raise ProjectStateError("Повреждены ключевые кадры проекта.")
        for keyframe in keys:
            for key in ("time", "x", "y", "opacity"):
                if key in keyframe:
                    number(keyframe[key])
    def reject_secrets(value):
        if isinstance(value, dict):
            if any(str(key).lower() in {"access_token", "refresh_token", "client_secret", "api_key", "code_verifier"} for key in value):
                raise ProjectStateError("Секреты нельзя сохранять в проекте. Используйте системное хранилище учётных данных.")
            for item in value.values():
                reject_secrets(item)
        elif isinstance(value, list):
            for item in value:
                reject_secrets(item)
    reject_secrets(state)
    return tuple(dict.fromkeys(missing))


def load_project_state(project_id: int) -> LoadedDraft:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectStateError("Проект не найден.")
        preference = session.execute(text("SELECT value_json FROM app_preferences WHERE key=:key"),
                                     {"key": draft_key(project_id)}).first()
        if preference is None and project.draft_revision == 0:
            return LoadedDraft({}, 0)
        records = session.execute(text("SELECT revision, state, checksum FROM project_revisions "
            "WHERE project_id=:project_id ORDER BY revision DESC"), {"project_id": project_id}).mappings().all()
        record = next((item for item in records if item["revision"] == project.draft_revision), None)
        candidates = [(preference[0] if preference else None, record["checksum"] if record else None, False)] if record or project.draft_revision == 0 else []
        candidates += [(item["state"], item["checksum"], True) for item in records]
        for state, signature, recovered in candidates:
            try:
                state = json.loads(state) if isinstance(state, (str, bytes)) else state
                if state is None or (signature is not None and checksum(state) != signature):
                    continue
                missing = _validate(session, project_id, state)
                return LoadedDraft(copy.deepcopy(state), project.draft_revision, recovered, missing)
            except (ProjectStateError, json.JSONDecodeError):
                continue
        raise ProjectStateError("Не удалось прочитать проект и его сохранённые версии. Данные сохранены для восстановления из резервной копии.")


def _store_snapshot(session, project_id: int, state: dict, expected_revision: int) -> int:
    _validate(session, project_id, state)
    signature = checksum(state)
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectStateError("Проект не найден.")
    if project.draft_revision != expected_revision:
        raise ProjectConflict("Проект изменён в другом окне. Откройте его заново перед сохранением.")
    previous_checksum = session.scalar(select(ProjectRevision.checksum).where(
        ProjectRevision.project_id == project_id, ProjectRevision.revision == expected_revision))
    raw_preference = session.execute(text("SELECT value_json FROM app_preferences WHERE key=:key"),
                                     {"key": draft_key(project_id)}).first()
    try:
        current = raw_preference[0] if raw_preference else None
        current = json.loads(current) if isinstance(current, (str, bytes)) else current
        current_signature = checksum(current) if raw_preference else None
    except (ProjectStateError, json.JSONDecodeError):
        current_signature = None
    if previous_checksum == signature and current_signature == signature:
        return expected_revision
    revision = expected_revision + 1
    result = session.execute(update(Project).where(Project.id == project_id,
        Project.draft_revision == expected_revision).values(draft_revision=revision, updated_at=utc_now()))
    if result.rowcount != 1:
        raise ProjectConflict("Проект изменён во время сохранения. Откройте его заново.")
    updated = session.execute(update(AppPreference).where(AppPreference.key == draft_key(project_id))
                              .values(value_json=copy.deepcopy(state)))
    if updated.rowcount == 0:
        session.add(AppPreference(key=draft_key(project_id), value_json=copy.deepcopy(state)))
    session.add(ProjectRevision(project_id=project_id, revision=revision,
                                state=copy.deepcopy(state), checksum=signature))
    session.execute(delete(ProjectRevision).where(ProjectRevision.project_id == project_id,
                                                   ProjectRevision.revision <= revision - 20))
    return revision


def save_project_state(project_id: int, state: dict, expected_revision: int) -> int:
    with SessionLocal.begin() as session:
        return _store_snapshot(session, project_id, state, expected_revision)
