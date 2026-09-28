from __future__ import annotations

import logging

from sqlalchemy import select

from app.models import ClipCandidate, ContentIdea, Project, SessionLocal, Transcript, Video
from app.services.ai import ContentAssistant, ContentPack, get_content_assistant

logger = logging.getLogger(__name__)


def generate_content_pack_for_video(
    video_id: int,
    assistant: ContentAssistant | None = None,
) -> ContentPack:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        transcript = session.scalar(
            select(Transcript)
            .where(Transcript.video_id == video_id, Transcript.status == "ready")
            .order_by(Transcript.created_at.desc())
        )
        source_text = transcript.text if transcript and transcript.text.strip() else video.filename
        duration = video.duration
    return (assistant or get_content_assistant()).generate(source_text, duration)


def persist_content_pack(project_id: int, video_id: int, pack: ContentPack) -> list[int]:
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        video = session.get(Video, video_id)
        if project is None:
            raise ValueError(f"Project {project_id} does not exist")
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        if video.project_id not in {None, project_id}:
            raise ValueError("Video belongs to another project")
        video.project_id = project_id

        maximum = video.duration
        candidates: list[ClipCandidate] = []
        for suggestion in pack.clip_suggestions:
            start = max(0.0, suggestion.start_time)
            end = suggestion.end_time if maximum is None else min(suggestion.end_time, maximum)
            if end - start < 3.0:
                logger.warning(
                    "Skipping invalid clip suggestion for video %s: %.2f-%.2f",
                    video_id,
                    start,
                    end,
                )
                continue
            candidate = ClipCandidate(
                project_id=project_id,
                video_id=video_id,
                title=suggestion.title,
                start_time=start,
                end_time=end,
                score=suggestion.score,
                reason=suggestion.reason,
            )
            candidates.append(candidate)

        session.add_all(candidates)
        session.flush()
        candidate_ids = [candidate.id for candidate in candidates]

        session.add(
            ContentIdea(
                project_id=project_id,
                title=pack.title,
                hook=pack.hooks[0] if pack.hooks else "",
                format="vertical-short",
                script=pack.description,
                score=max((item.score for item in pack.clip_suggestions), default=0.0),
                copyright_note=pack.copyright_note,
            )
        )
        session.commit()
        return candidate_ids


def analyze_video_for_clips(
    project_id: int,
    video_id: int,
    assistant: ContentAssistant | None = None,
) -> tuple[ContentPack, list[int]]:
    pack = generate_content_pack_for_video(video_id, assistant)
    return pack, persist_content_pack(project_id, video_id, pack)
