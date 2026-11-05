"""Local project inventory, recency and metadata-only project deletion."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.models import AppPreference, Post, Project, SessionLocal, Video
from app.services.project_state import ProjectConflict, load_project_state

RECENTS_KEY = "library.recent_projects"


def preference(key: str, default=None):
    with SessionLocal() as session:
        row = session.get(AppPreference, key)
        return row.value_json if row else default


def set_preference(key: str, value) -> None:
    with SessionLocal.begin() as session:
        row = session.get(AppPreference, key)
        if row is None:
            session.add(AppPreference(key=key, value_json=value))
        else:
            row.value_json = value


def mark_opened(project_id: int) -> None:
    with SessionLocal.begin() as session:
        if session.get(Project, project_id) is None:
            return
        row = session.get(AppPreference, RECENTS_KEY)
        previous = row.value_json if row and isinstance(row.value_json, list) else []
        recent = [{"id": project_id, "opened_at": datetime.now(timezone.utc).isoformat()}]
        recent += [item for item in previous if isinstance(item, dict) and item.get("id") != project_id][:19]
        if row:
            row.value_json = recent
        else:
            session.add(AppPreference(key=RECENTS_KEY, value_json=recent))


def recent_projects() -> list[dict]:
    recent = preference(RECENTS_KEY, [])
    if not isinstance(recent, list):
        return []
    with SessionLocal() as session:
        projects = {p.id: p for p in session.scalars(select(Project))}
        videos = list(session.scalars(select(Video).order_by(Video.id)))
    result = []
    for item in recent:
        if not isinstance(item, dict) or item.get("id") not in projects:
            continue
        project = projects[item["id"]]
        primary = next((v.id for v in videos if v.project_id == project.id), None)
        if primary is not None:
            result.append({"id": project.id, "name": project.name, "video_id": primary,
                           "opened_at": item.get("opened_at", "")})
    return result


def library_inventory() -> dict:
    """Filesystem checks belong in a background worker, not the UI event loop."""
    with SessionLocal() as session:
        projects = list(session.scalars(select(Project).order_by(Project.updated_at.desc())))
        videos = list(session.scalars(select(Video).order_by(Video.created_at.desc())))
    video_rows = [{"id": v.id, "project_id": v.project_id, "filename": v.filename,
                   "created_at": v.created_at, "status": v.status, "path": v.original_path,
                   "output_path": v.output_path, "duration": v.duration or 0,
                   "width": v.width or 0, "height": v.height or 0,
                   "missing": not Path(v.original_path).is_file(),
                   "output_exists": bool(v.output_path and Path(v.output_path).is_file())} for v in videos]
    recent = {item["id"]: item["opened_at"] for item in recent_projects()}
    rows = []
    for project in projects:
        members = [v for v in video_rows if v["project_id"] == project.id]
        try:
            loaded = load_project_state(project.id)
            state, missing = loaded.state, list(loaded.missing_files)
            recovered = loaded.recovered
            damaged = False
        except ValueError:
            state, missing, damaged, recovered = {}, [], True, False
        missing += [v["path"] for v in members if v["missing"]]
        primary_id = state.get("primary_id") or (min(v["id"] for v in members) if members else None)
        primary = next((v for v in members if v["id"] == primary_id), {})
        export_path = primary.get("output_path")
        export_ready = bool(export_path and Path(export_path).is_file() and not state.get("dirty", True) and not recovered)
        clips = state.get("clips", [])
        duration = sum(c["end_time"] - c["start_time"] for c in clips) if clips else primary.get("duration", 0)
        if state.get("transition") == "dissolve":
            duration -= max(0, len(clips)-1) * state.get("transition_duration", 0.5)
        status = ("Повреждён черновик" if damaged else "Нет исходников" if missing else
                  "Восстановлен черновик" if recovered else "Экспортирован" if export_ready else "Нет экспорта" if export_path and not Path(export_path).is_file()
                  else "Черновик")
        rows.append({"id": project.id, "name": project.name, "primary_id": primary_id,
                     "created_at": project.created_at, "updated_at": project.updated_at,
                     "revision": project.draft_revision, "status": status, "duration": max(0, duration),
                     "missing": sorted(set(missing)), "output_path": export_path,
                     "opened_at": recent.get(project.id, ""), "members": members})
    return {"projects": rows, "videos": video_rows}


def rename_project(project_id: int, name: str) -> None:
    name = name.strip()
    if not name or len(name) > 255:
        raise ValueError("Название должно содержать от 1 до 255 символов.")
    with SessionLocal.begin() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ValueError("Проект уже удалён.")
        project.name = name


def delete_project(project_id: int, expected_revision: int) -> None:
    """Delete editing metadata only. Keep video rows, files and provider operations."""
    with SessionLocal.begin() as session:
        if session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if project is None:
            raise ValueError("Проект уже удалён.")
        if project.draft_revision != expected_revision:
            raise ProjectConflict("Проект изменился. Обновите список и повторите удаление.")
        ids = select(Video.id).where(Video.project_id == project_id)
        if session.scalar(select(Video.id).where(Video.project_id == project_id, Video.status == "processing")):
            raise ValueError("Дождитесь завершения обработки видео.")
        if session.scalar(select(Post.id).where(Post.video_id.in_(ids), Post.status.in_(
                ("queued", "scheduled", "dispatching", "publishing", "pending", "unknown")))):
            raise ValueError("У проекта есть незавершённые публикации. Сначала завершите или отмените их.")
        # Database CASCADE removes project revisions/candidates; SET NULL detaches
        # videos/ideas. Bulk SQL avoids ORM cascades deleting retained media records.
        session.execute(delete(AppPreference).where(AppPreference.key.startswith(f"editor.project.{project_id}.")))
        session.execute(delete(Project).where(Project.id == project_id))
        recent = session.get(AppPreference, RECENTS_KEY)
        if recent and isinstance(recent.value_json, list):
            recent.value_json = [v for v in recent.value_json if isinstance(v, dict) and v.get("id") != project_id]
