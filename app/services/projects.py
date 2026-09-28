from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Project, SessionLocal, Video


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
