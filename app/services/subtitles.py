from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start: float
    end: float
    text: str


def _timestamp(seconds: float, separator: str = ",") -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{milliseconds:03}"


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for cue in cues:
        if cue.end <= cue.start or not cue.text.strip():
            continue
        index = len(blocks) + 1
        text = cue.text.replace("\x00", "").strip()
        blocks.append(
            f"{index}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_vtt(cues: list[SubtitleCue]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        if cue.end <= cue.start or not cue.text.strip():
            continue
        text = cue.text.replace("\x00", "").replace("-->", "→").strip()
        blocks.append(
            f"{_timestamp(cue.start, '.')} --> {_timestamp(cue.end, '.')}\n{text}"
        )
    return "\n\n".join(blocks) + "\n"


def save_subtitles(path: str | Path, cues: list[SubtitleCue]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    if suffix == ".srt":
        content = render_srt(cues)
    elif suffix == ".vtt":
        content = render_vtt(cues)
    else:
        raise ValueError("Subtitle file must use .srt or .vtt")
    destination.write_text(content, encoding="utf-8")
    return destination
