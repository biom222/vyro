"""Local FFmpeg shot-boundary suggestions; no semantic or rights assessment."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models import ClipCandidate, SessionLocal, Video


_PTS_TIME = re.compile(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)")
_REASON = "Смена сцены по FFmpeg; проверьте смысл и права на материал вручную."


def scene_ranges(cuts: list[float], duration: float, minimum: float = 3.0,
                 maximum: float = 90.0) -> list[tuple[float, float]]:
    """Merge very short shots and split long spans into editable suggestions."""
    if duration < minimum:
        return []
    boundaries = [0.0] + sorted({cut for cut in cuts if 0 < cut < duration}) + [duration]
    ranges: list[tuple[float, float]] = []
    start = 0.0
    for cut in boundaries[1:]:
        while cut - start > maximum:
            ranges.append((round(start, 2), round(start + maximum, 2)))
            start += maximum
        if cut - start >= minimum:
            ranges.append((round(start, 2), round(cut, 2)))
            start = cut
    if ranges and duration - start > 0.05:
        last_start, _ = ranges[-1]
        if duration - last_start <= maximum:
            ranges[-1] = (last_start, round(duration, 2))
        elif duration - start >= minimum:
            ranges.append((round(start, 2), round(duration, 2)))
    return ranges[:30]


def detect_scene_cuts(source: Path, duration: float, threshold: float = 0.35) -> list[float]:
    if not 0.1 <= threshold <= 0.9:
        raise ValueError("Scene threshold must be between 0.1 and 0.9")
    command = [
        settings.ffmpeg_binary, "-hide_banner", "-nostats", "-loglevel", "info",
        "-i", str(source), "-vf",
        f"scale=320:-2,fps=2,select=gt(scene\\,{threshold:.2f}),showinfo",
        "-an", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False,
                                timeout=max(60, min(1800, round(duration * 5))))
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip()
                           else "FFmpeg scene detection failed")
    return [float(value) for value in _PTS_TIME.findall(result.stderr)]


def suggest_scenes(project_id: int, video_id: int) -> list[int]:
    """Persist deduplicated technical shot suggestions for one project video."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None or video.project_id != project_id:
            raise ValueError("Video does not belong to the selected project")
        source = Path(video.original_path)
        duration = video.duration or 0.0
    if not source.is_file():
        raise FileNotFoundError(f"Video source is missing: {source}")
    if duration <= 0:
        raise ValueError("Video duration is unavailable")
    ranges = scene_ranges(detect_scene_cuts(source, duration), duration)
    if not ranges:
        return []
    with SessionLocal() as session:
        existing = {
            (round(candidate.start_time, 2), round(candidate.end_time, 2))
            for candidate in session.scalars(select(ClipCandidate).where(
                ClipCandidate.project_id == project_id,
                ClipCandidate.video_id == video_id,
                ClipCandidate.reason == _REASON,
            ))
        }
        candidates = []
        for index, (start, end) in enumerate(ranges, 1):
            if (start, end) in existing:
                continue
            candidates.append(ClipCandidate(
                project_id=project_id, video_id=video_id,
                title=f"Сцена {index}", start_time=start, end_time=end,
                score=50.0, reason=_REASON,
            ))
        session.add_all(candidates)
        session.flush()
        ids = [candidate.id for candidate in candidates]
        session.commit()
    return ids
