from __future__ import annotations

from pathlib import Path
import copy

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import (AppPreference, ClipCandidate, ContentIdea, EditParams, Project,
                        SessionLocal, Transcript, TranscriptSegment, Video)


def create_project(name: str, description: str = "") -> Project:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Project name cannot be empty")
    with SessionLocal() as session:
        project = Project(name=clean_name, description=description.strip())
        session.add(project)
        session.commit()
        session.refresh(project)
        session.expunge(project)
        return project


def add_video_to_project(project_id: int, video_id: int) -> None:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        video = session.get(Video, video_id)
        if project is None:
            raise ValueError(f"Project {project_id} does not exist")
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        if video.project_id not in {None, project_id}:
            raise ValueError(f"Video {video_id} already belongs to project {video.project_id}")
        video.project_id = project.id
        session.commit()


def create_project_for_video(video_id: int, name: str | None = None) -> Project:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        if video.project_id is not None:
            raise ValueError(f"Video {video_id} already belongs to project {video.project_id}")
        project = Project(name=(name or Path(video.filename).stem).strip() or "Untitled")
        session.add(project)
        session.flush()
        video.project_id = project.id
        session.commit()
        session.refresh(project)
        session.expunge(project)
        return project


def list_projects(offset: int = 0, limit: int = 100) -> list[Project]:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("Expected offset >= 0 and 1 <= limit <= 500")
    with SessionLocal() as session:
        projects = list(
            session.scalars(
                select(Project)
                .options(selectinload(Project.videos), selectinload(Project.clips))
                .order_by(Project.updated_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )
        for project in projects:
            session.expunge(project)
        return projects


def duplicate_project(project_id: int, name: str, draft_state: dict | None = None) -> tuple[int, int]:
    """Create independent edits; share immutable media, never clone publication jobs."""
    from app.services.project_state import ProjectConflict, load_project_state, _store_snapshot

    name = name.strip()
    if not name or len(name) > 255:
        raise ValueError("Введите название проекта длиной от 1 до 255 символов.")
    loaded = load_project_state(project_id)
    if not loaded.state and draft_state is None:
        raise ValueError("Сначала сохраните исходный проект.")
    with SessionLocal.begin() as session:
        original = session.get(Project, project_id)
        if original.draft_revision != loaded.revision:
            raise ProjectConflict("Исходный проект изменился. Повторите дублирование.")
        duplicate = Project(name=name, description=original.description)
        session.add(duplicate)
        session.flush()
        remap = {}
        preferences = []

        def clone(row, **overrides):
            values = {column.key: copy.deepcopy(getattr(row, column.key))
                      for column in row.__table__.columns if not column.primary_key}
            values.update(overrides)
            result = type(row)(**values)
            session.add(result)
            session.flush()
            return result

        for video in session.scalars(select(Video).where(Video.project_id == project_id)).all():
            new_video = clone(video, project_id=duplicate.id, output_path=None, output_duration=None,
                              status="uploaded", error_message=None)
            remap[video.id] = new_video.id
            for edit in session.scalars(select(EditParams).where(EditParams.video_id == video.id)).all():
                clone(edit, video_id=new_video.id)
            preference = session.get(AppPreference, f"editor.video.{video.id}")
            if preference:
                preferences.append((new_video.id, copy.deepcopy(preference.value_json)))
            for transcript in session.scalars(select(Transcript).where(Transcript.video_id == video.id)).all():
                new_transcript = clone(transcript, video_id=new_video.id)
                for segment in transcript.segments:
                    clone(segment, transcript_id=new_transcript.id)
        for candidate in session.scalars(select(ClipCandidate).where(ClipCandidate.project_id == project_id)).all():
            clone(candidate, project_id=duplicate.id, video_id=remap[candidate.video_id])
        for idea in session.scalars(select(ContentIdea).where(ContentIdea.project_id == project_id)).all():
            clone(idea, project_id=duplicate.id)
        def remap_media_ids(value):
            if isinstance(value, list):
                return [remap_media_ids(item) for item in value]
            if isinstance(value, dict):
                return {key: remap.get(item, item) if key in {"video_id", "primary_id"} and isinstance(item, int)
                        else remap_media_ids(item) for key, item in value.items()}
            return value
        for video_id, preference in preferences:
            session.add(AppPreference(key=f"editor.video.{video_id}", value_json=remap_media_ids(preference)))
        state = copy.deepcopy(draft_state if draft_state is not None else loaded.state)
        state["primary_id"] = remap[state["primary_id"]]
        state["dirty"] = True
        for clip in state["clips"]:
            clip["video_id"] = remap[clip["video_id"]]
        for layer in state.get("video_layers", []):
            layer["video_id"] = remap[layer["video_id"]]
        _store_snapshot(session, duplicate.id, state, 0)
        return duplicate.id, state["primary_id"]
