from __future__ import annotations

import json
import hashlib
import logging
import math
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.config import settings
from app.models import SessionLocal, Transcript, Video
from app.services.subtitles import SubtitleCue, save_subtitles

logger = logging.getLogger(__name__)


class VideoProcessingError(RuntimeError):
    """Raised when FFmpeg or FFprobe cannot process a video."""


def _run(command: list[str]) -> None:
    logger.info("Running video command: %s", " ".join(command[:4]) + " ...")
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError(f"Required executable is missing: {command[0]}") from exc

    if completed.returncode != 0:
        details = completed.stderr.strip().splitlines()
        message = details[-1] if details else "Unknown FFmpeg error"
        raise VideoProcessingError(message)


def probe_video_metadata(input_path: str | Path) -> tuple[float, int, int]:
    command = [
        settings.ffprobe_binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration:stream=width,height",
        "-of",
        "json",
        str(input_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError("ffprobe is not installed") from exc

    if completed.returncode != 0:
        raise VideoProcessingError(completed.stderr.strip() or "Could not inspect video")

    try:
        payload = json.loads(completed.stdout)
        duration = float(payload["format"]["duration"])
        stream = payload["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VideoProcessingError("Could not read video metadata") from exc

    if duration <= 0 or width <= 0 or height <= 0:
        raise VideoProcessingError("Video metadata contains invalid values")
    return duration, width, height


def probe_duration(input_path: str | Path) -> float:
    duration, _, _ = probe_video_metadata(input_path)
    return duration


def _encode_command(input_path: str | Path, output_path: str | Path) -> list[str]:
    return [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def trim_video(
    input_path: str | Path,
    output_path: str | Path,
    start: float,
    end: float,
) -> Path:
    if start < 0 or end <= start:
        raise ValueError("Trim range must satisfy 0 <= start < end")

    command = [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(input_path),
        "-t",
        str(end - start),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run(command)
    return Path(output_path)


def make_vertical(input_path: str | Path, output_path: str | Path,
                  crop_position: float = 0.5) -> Path:
    position = min(max(float(crop_position), 0.0), 1.0)
    video_filter = (
        "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)':"
        f"x='(iw-ow)*{position:.4f}':y='(ih-oh)/2',scale=1080:1920,setsar=1"
    )
    command = _encode_command(input_path, output_path)
    command[-1:-1] = ["-vf", video_filter]
    _run(command)
    return Path(output_path)


def _filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _font_path() -> Path:
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/Library/Fonts/Arial Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise VideoProcessingError("No supported font file was found")


def add_text(
    input_path: str | Path,
    output_path: str | Path,
    text: str,
    position: str = "bottom",
    font_size: int = 64,
    font_color: str = "white",
) -> Path:
    if not text.strip():
        shutil.copy2(input_path, output_path)
        return Path(output_path)

    output = Path(output_path)
    text_file = output.parent / f"caption-{uuid.uuid4().hex}.txt"
    text_file.write_text(text, encoding="utf-8")
    try:
        positions = {
            "top": "h*0.10",
            "center": "(h-text_h)/2",
            "bottom": "h-text_h-h*0.12",
        }
        colors = {"white", "yellow", "#69c0ff"}
        y_position = positions.get(position, positions["bottom"])
        safe_size = min(max(int(font_size), 24), 120)
        safe_color = font_color if font_color in colors else "white"
        video_filter = (
            f"drawtext=fontfile='{_filter_path(_font_path())}':"
            f"textfile='{_filter_path(text_file)}':reload=0:"
            f"fontcolor={safe_color}:fontsize={safe_size}:line_spacing=12:"
            "borderw=4:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y={y_position}:fix_bounds=1"
        )
        command = _encode_command(input_path, output_path)
        command[-1:-1] = ["-vf", video_filter]
        _run(command)
    finally:
        text_file.unlink(missing_ok=True)
    return output


def _keyframe_expression(keyframes: list[dict], field: str) -> str:
    """Generate a piecewise-linear FFmpeg expression over output time."""
    def number(value: float) -> str:
        return f"{value:.4f}"

    expression = number(float(keyframes[-1][field]))
    for left, right in reversed(list(zip(keyframes, keyframes[1:]))):
        start, end = float(left["time"]), float(right["time"])
        value, delta = float(left[field]), float(right[field]) - float(left[field])
        segment = f"({number(value)}+{number(delta)}*(t-{number(start)})/{number(end-start)})"
        expression = f"if(lt(t,{number(end)}),{segment},{expression})"
    first = keyframes[0]
    return f"if(lt(t,{number(float(first['time']))}),{number(float(first[field]))},{expression})"


def _validated_title_layers(layers: object, duration: float) -> list[dict]:
    if not isinstance(layers, list) or len(layers) > 8:
        raise VideoProcessingError("A project supports at most eight title layers")
    validated = []
    for layer in layers:
        if not isinstance(layer, dict):
            raise VideoProcessingError("Invalid title layer")
        text = str(layer.get("text", "")).strip()
        start, end = float(layer.get("start", 0)), float(layer.get("end", duration))
        if not text or not all(map(math.isfinite, (start, end))) or not 0 <= start < end <= duration + 0.05:
            raise VideoProcessingError("Title text or time range is invalid")
        raw_keyframes = layer.get("keyframes") or [
            {"time": start, "x": 0.5, "y": 0.8, "opacity": 1.0},
            {"time": end, "x": 0.5, "y": 0.8, "opacity": 1.0},
        ]
        if not isinstance(raw_keyframes, list) or not 1 <= len(raw_keyframes) <= 20:
            raise VideoProcessingError("Title keyframes must contain between 1 and 20 points")
        keyframes = []
        for frame in raw_keyframes:
            if not isinstance(frame, dict):
                raise VideoProcessingError("Invalid title keyframe")
            point = {key: float(frame[key]) for key in ("time", "x", "y", "opacity")}
            if (not all(map(math.isfinite, point.values()))
                    or not start - 0.05 <= point["time"] <= end + 0.05
                    or any(not 0 <= point[key] <= 1 for key in ("x", "y", "opacity"))):
                raise VideoProcessingError("Title keyframe is outside its layer")
            keyframes.append(point)
        keyframes.sort(key=lambda item: item["time"])
        if any(right["time"] - left["time"] < 0.001 for left, right in zip(keyframes, keyframes[1:])):
            raise VideoProcessingError("Title keyframes need unique times")
        validated.append({
            "text": text, "start": start, "end": end, "keyframes": keyframes,
            "font_size": min(max(int(layer.get("font_size", 64)), 16), 160),
            "color": layer.get("color") if isinstance(layer.get("color"), str)
            and layer.get("color") in {"white", "yellow", "#69c0ff"} else "white",
        })
    return validated


def render_title_layers(input_path: str | Path, output_path: str | Path,
                        layers: list[dict], duration: float, preview: bool = False) -> Path:
    """Burn multiple independently timed titles with animated position and opacity."""
    validated = _validated_title_layers(layers, duration)
    if not validated:
        shutil.copy2(input_path, output_path)
        return Path(output_path)
    with tempfile.TemporaryDirectory(prefix="shorts-titles-") as temp_dir:
        filters = []
        for index, layer in enumerate(validated):
            text_file = Path(temp_dir) / f"title-{index}.txt"
            text_file.write_text(layer["text"], encoding="utf-8")
            keyframes = layer["keyframes"]
            x = _keyframe_expression(keyframes, "x")
            y = _keyframe_expression(keyframes, "y")
            alpha = _keyframe_expression(keyframes, "opacity")
            size = max(12, round(layer["font_size"] * (0.5 if preview else 1)))
            filters.append(
                f"drawtext=fontfile='{_filter_path(_font_path())}':"
                f"textfile='{_filter_path(text_file)}':reload=0:"
                f"fontcolor={layer['color']}:fontsize={size}:"
                "borderw=3:bordercolor=black@0.85:"
                f"x='({x})*w-text_w/2':y='({y})*h-text_h/2':alpha='{alpha}':"
                f"enable='between(t,{layer['start']:.4f},{layer['end']:.4f})'"
            )
        command = _encode_command(input_path, output_path)
        command[-1:-1] = ["-vf", ",".join(filters)]
        _run(command)
    return Path(output_path)


def _validated_video_layers(layers: object, video_id: int, duration: float) -> list[dict]:
    """Resolve video overlays from the same project; never trust saved paths."""
    if not isinstance(layers, list) or len(layers) > 4:
        raise VideoProcessingError("A project supports at most four video overlays")
    with SessionLocal() as session:
        primary = session.get(Video, video_id)
        if primary is None or primary.project_id is None:
            raise VideoProcessingError("The project video is missing")
        resolved = []
        for layer in layers:
            if not isinstance(layer, dict) or not isinstance(layer.get("video_id"), int):
                raise VideoProcessingError("Invalid video overlay")
            video = session.get(Video, layer["video_id"])
            if video is None or video.project_id != primary.project_id:
                raise VideoProcessingError("An overlay must belong to the current project")
            path = Path(video.original_path)
            if not path.is_file():
                raise VideoProcessingError(f"Overlay source is missing: {path}")
            try:
                start = float(layer.get("start", 0))
                end = float(layer.get("end", duration))
                source_start = float(layer.get("source_start", 0))
                x = float(layer.get("x", 0.5))
                y = float(layer.get("y", 0.1))
                width = float(layer.get("width", 0.5))
                opacity = float(layer.get("opacity", 1))
            except (TypeError, ValueError) as exc:
                raise VideoProcessingError("Invalid video overlay values") from exc
            if (not all(map(math.isfinite, (start, end, source_start, x, y, width, opacity)))
                    or not 0 <= start < end <= duration + 0.05
                    or source_start < 0 or source_start + end - start > (video.duration or probe_duration(path)) + 0.05
                    or not 0 <= x <= 1 or not 0 <= y <= 1
                    or not 0.1 <= width <= 1 or not 0 <= opacity <= 1):
                raise VideoProcessingError("Video overlay is outside the project or source")
            resolved.append({"path": path, "start": start, "end": end,
                             "source_start": source_start, "x": x, "y": y,
                             "width": width, "opacity": opacity})
    return resolved


def render_video_layers(input_path: str | Path, output_path: str | Path,
                        layers: list[dict], video_id: int, duration: float,
                        preview: bool = False, vertical: bool = True) -> Path:
    """Composite independent silent video tracks over the assembled timeline."""
    resolved = _validated_video_layers(layers, video_id, duration)
    if not resolved:
        shutil.copy2(input_path, output_path)
        return Path(output_path)
    canvas_width = (540 if preview else 1080) if vertical else (640 if preview else 1280)
    command = [settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path)]
    for layer in resolved:
        command += ["-i", str(layer["path"])]
    filters = []
    current = "0:v"
    for index, layer in enumerate(resolved, 1):
        length = layer["end"] - layer["start"]
        target_width = max(2, round(canvas_width * layer["width"] / 2) * 2)
        filters.append(
            f"[{index}:v]trim=start={layer['source_start']:.4f}:duration={length:.4f},"
            f"setpts=PTS-STARTPTS+{layer['start']:.4f}/TB,"
            f"scale={target_width}:-2,format=rgba,colorchannelmixer=aa={layer['opacity']:.4f}[overlay{index}]"
        )
        filters.append(
            f"[{current}][overlay{index}]overlay="
            f"x='(W-w)*{layer['x']:.4f}':y='(H-h)*{layer['y']:.4f}':"
            f"eof_action=pass:repeatlast=0:shortest=0:"
            f"enable='between(t,{layer['start']:.4f},{layer['end']:.4f})'[mixed{index}]"
        )
        current = f"mixed{index}"
    command += ["-filter_complex", ";".join(filters), "-map", f"[{current}]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium",
                "-crf", "30" if preview else "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output_path)]
    _run(command)
    return Path(output_path)


def burn_subtitles(
    input_path: str | Path,
    output_path: str | Path,
    subtitle_path: str | Path,
) -> Path:
    subtitles = Path(subtitle_path)
    if not subtitles.is_file():
        raise VideoProcessingError(f"Subtitle file does not exist: {subtitles}")
    if subtitles.suffix.lower() not in {".srt", ".vtt", ".ass", ".ssa"}:
        raise VideoProcessingError("Supported subtitle formats are SRT, VTT, ASS and SSA")
    style = (
        "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=110"
    )
    video_filter = (
        f"subtitles=filename='{_filter_path(subtitles)}':force_style='{style}'"
    )
    command = _encode_command(input_path, output_path)
    command[-1:-1] = ["-vf", video_filter]
    _run(command)
    return Path(output_path)


def _has_audio(path: Path) -> bool:
    try:
        result = subprocess.run(
            [settings.ffprobe_binary, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=False, encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError("ffprobe is not installed") from exc
    if result.returncode:
        raise VideoProcessingError(result.stderr.strip() or "Could not inspect audio")
    return bool(result.stdout.strip())


def _auto_subtitles(clips: list[tuple[int, float, float]], destination: Path,
                    overlap: float = 0.0) -> Path:
    """Map transcript segment times onto the finished sequence."""
    cues: list[SubtitleCue] = []
    position = 0.0
    with SessionLocal() as session:
        for index, (video_id, start, end) in enumerate(clips):
            transcript = session.scalar(
                select(Transcript).where(Transcript.video_id == video_id, Transcript.status == "ready")
                .order_by(Transcript.created_at.desc(), Transcript.id.desc()).limit(1)
            )
            if transcript is not None:
                for segment in transcript.segments:
                    cue_start = max(segment.start_time, start)
                    cue_end = min(segment.end_time, end)
                    if cue_end > cue_start and segment.text.strip():
                        cues.append(SubtitleCue(position + cue_start - start,
                                                position + cue_end - start, segment.text))
            position += end - start
            if index < len(clips) - 1:
                position -= overlap
    if not cues:
        raise VideoProcessingError("No timed transcript found. Recognize speech in AI clips first")
    return save_subtitles(destination, sorted(cues, key=lambda cue: cue.start))


def render_sequence(
    video_id: int,
    params: dict[str, Any],
    progress_callback: Callable[[int], None] | None = None,
    preview: bool = False,
) -> tuple[str, float]:
    """Join ordered project clips with cuts, normalized video/audio, and optional music."""
    raw_clips = params.get("clips")
    if not isinstance(raw_clips, list) or not 1 <= len(raw_clips) <= 30:
        raise VideoProcessingError("The sequence needs between 1 and 30 clips")
    with SessionLocal() as session:
        primary = session.get(Video, video_id)
        if primary is None or primary.project_id is None:
            raise VideoProcessingError("The project video is missing")
        ids = []
        for item in raw_clips:
            if not isinstance(item, dict) or not isinstance(item.get("video_id"), int):
                raise VideoProcessingError("Invalid sequence clip")
            ids.append(item["video_id"])
        videos = {video.id: video for video in session.scalars(select(Video).where(Video.id.in_(ids)))}
        clips = []
        for item in raw_clips:
            video = videos.get(item["video_id"])
            if video is None or video.project_id != primary.project_id:
                raise VideoProcessingError("A sequence clip does not belong to this project")
            source = Path(video.original_path)
            if not source.is_file():
                raise VideoProcessingError(f"Source file is missing: {source}")
            duration = video.duration or probe_duration(source)
            try:
                start, end = float(item["start_time"]), float(item["end_time"])
            except (KeyError, ValueError, TypeError) as exc:
                raise VideoProcessingError("Invalid clip time range") from exc
            if not 0 <= start < end <= duration + 0.05:
                raise VideoProcessingError(f"Invalid clip range for {video.filename}")
            clips.append((source, start, min(end, duration)))

    music_value = str(params.get("music_path") or "").strip()
    music = Path(music_value) if music_value else None
    if music and (not music.is_file() or music.suffix.lower() not in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}):
        raise VideoProcessingError("The music file is missing or unsupported")
    try:
        music_volume = float(params.get("music_volume", 0.25))
    except (TypeError, ValueError) as exc:
        raise VideoProcessingError("Invalid music volume") from exc
    if not 0 <= music_volume <= 1:
        raise VideoProcessingError("Music volume must be between 0 and 1")
    transition = str(params.get("transition", "cut"))
    if transition not in {"cut", "dissolve"}:
        raise VideoProcessingError("Unsupported transition")
    try:
        transition_duration = float(params.get("transition_duration", 0.5))
    except (TypeError, ValueError) as exc:
        raise VideoProcessingError("Invalid transition duration") from exc
    if transition == "dissolve" and len(clips) > 1 and (
        not 0.1 <= transition_duration <= 2 or
        any(end - start <= transition_duration for _, start, end in clips)
    ):
        raise VideoProcessingError("Dissolve duration must be shorter than every clip")

    total_duration = sum(end - start for _, start, end in clips)
    if transition == "dissolve":
        total_duration -= transition_duration * (len(clips) - 1)
    title_layers = params.get("title_layers") or []
    video_layers = params.get("video_layers") or []
    resolved_video_layers = []
    if title_layers:
        _validated_title_layers(title_layers, total_duration)
    if video_layers:
        resolved_video_layers = _validated_video_layers(video_layers, video_id, total_duration)

    vertical = bool(params.get("is_vertical", True))
    crop_position = min(max(float(params.get("crop_position", 0.5)), 0.0), 1.0)
    if vertical:
        video_filter = ("crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)':"
                        f"x='(iw-ow)*{crop_position:.4f}':y='(ih-oh)/2',"
                        f"scale={'540:960' if preview else '1080:1920'}")
    else:
        dimensions = "640:360" if preview else "1280:720"
        video_filter = (f"scale={dimensions}:force_original_aspect_ratio=decrease,"
                        f"pad={dimensions}:(ow-iw)/2:(oh-ih)/2")
    command = [settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y"]
    for source, _, _ in clips:
        command += ["-i", str(source)]
    if music:
        command += ["-stream_loop", "-1", "-i", str(music)]
    filters = []
    for index, (source, start, end) in enumerate(clips):
        filters.append(f"[{index}:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS,{video_filter},setsar=1,fps=30,settb=AVTB,format=yuv420p[v{index}]")
        if _has_audio(source):
            filters.append(f"[{index}:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo[a{index}]")
        else:
            filters.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={end-start},asetpts=PTS-STARTPTS[a{index}]")
    if transition == "dissolve" and len(clips) > 1:
        video_name, audio_name = "v0", "a0"
        elapsed = clips[0][2] - clips[0][1]
        for index, (_, start, end) in enumerate(clips[1:], 1):
            offset = elapsed - transition_duration
            filters.append(f"[{video_name}][v{index}]xfade=transition=fade:duration={transition_duration}:offset={offset}[vx{index}]")
            filters.append(f"[{audio_name}][a{index}]acrossfade=d={transition_duration}[ax{index}]")
            video_name, audio_name = f"vx{index}", f"ax{index}"
            elapsed += end - start - transition_duration
        filters.append(f"[{video_name}]null[vout]")
        filters.append(f"[{audio_name}]anull[joined_audio]")
    else:
        inputs = "".join(f"[v{index}][a{index}]" for index in range(len(clips)))
        filters.append(f"{inputs}concat=n={len(clips)}:v=1:a=1[vout][joined_audio]")
    audio_map = "[joined_audio]"
    if music:
        filters.append(f"[{len(clips)}:a:0]atrim=duration={total_duration},asetpts=PTS-STARTPTS,aresample=44100,volume={music_volume}[music]")
        filters.append("[joined_audio][music]amix=inputs=2:duration=first:dropout_transition=0[mixed_audio]")
        audio_map = "[mixed_audio]"
    settings.ensure_directories()
    if preview:
        source_state = [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path, _, _ in clips]
        if music:
            source_state.append((str(music), music.stat().st_mtime_ns, music.stat().st_size))
        for layer in resolved_video_layers:
            path = layer["path"]
            source_state.append((str(path), path.stat().st_mtime_ns, path.stat().st_size))
        signature = hashlib.sha256(json.dumps(["preview-v1", params, source_state],
                                               sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
        final_path = settings.cache_folder / f"preview-{video_id}-{signature}.mp4"
        if final_path.is_file():
            if progress_callback:
                progress_callback(100)
            return str(final_path), probe_duration(final_path)
    else:
        final_path = settings.output_folder / f"video-{video_id}-{uuid.uuid4().hex[:10]}.mp4"
    if progress_callback:
        progress_callback(10)
    try:
        with tempfile.TemporaryDirectory(dir=settings.cache_folder if preview else settings.output_folder,
                                         prefix=f"sequence-{video_id}-") as temp_dir:
            joined = Path(temp_dir) / "joined.mp4"
            command += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", audio_map,
                        "-c:v", "libx264", "-preset", "ultrafast" if preview else "medium",
                        "-crf", "30" if preview else "23", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(joined)]
            _run(command)
            if progress_callback:
                progress_callback(75)
            current = joined
            if video_layers:
                layered = Path(temp_dir) / "video-layers.mp4"
                render_video_layers(current, layered, video_layers, video_id,
                                    total_duration, preview, vertical)
                current = layered
                if progress_callback:
                    progress_callback(82)
            if params.get("auto_subtitles"):
                subtitle_source = _auto_subtitles(
                    [(item["video_id"], start, end) for item, (_, start, end) in zip(raw_clips, clips)],
                    Path(temp_dir) / "auto.srt",
                    transition_duration if transition == "dissolve" else 0.0,
                )
                subtitled = Path(temp_dir) / "subtitled.mp4"
                burn_subtitles(current, subtitled, subtitle_source)
                current = subtitled
                if progress_callback:
                    progress_callback(88)
            if title_layers:
                titled = Path(temp_dir) / "titles.mp4"
                render_title_layers(current, titled, title_layers, total_duration, preview)
                current = titled
                if progress_callback:
                    progress_callback(94)
            subtitle_text = str(params.get("subtitle_text", "")).strip()
            if subtitle_text:
                captioned = Path(temp_dir) / "captioned.mp4"
                add_text(current, captioned, subtitle_text,
                         position=str(params.get("text_position", "bottom")),
                         font_size=max(24, round(int(params.get("font_size", 64)) * (0.5 if preview else 1))),
                         font_color=str(params.get("font_color", "white")))
                current = captioned
                if progress_callback:
                    progress_callback(98)
            shutil.move(str(current), final_path)
        duration = probe_duration(final_path)
        if progress_callback:
            progress_callback(100)
        return str(final_path), duration
    except Exception:
        final_path.unlink(missing_ok=True)
        raise


def render_preview(video_id: int, params: dict[str, Any],
                   progress_callback: Callable[[int], None] | None = None) -> tuple[str, float]:
    """Render a cached, lower-resolution preview with export timing and audio effects."""
    return render_sequence(video_id, params, progress_callback, preview=True)


def render_video(
    video_id: int,
    params: dict[str, Any],
    progress_callback: Callable[[int], None] | None = None,
) -> tuple[str, float]:
    if params.get("clips"):
        return render_sequence(video_id, params, progress_callback)
    def report(percent: int) -> None:
        if progress_callback is not None:
            progress_callback(percent)

    report(5)
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise VideoProcessingError(f"Video {video_id} does not exist")
        source = Path(video.original_path)
        source_duration = video.duration or probe_duration(source)

    start = float(params.get("start_time", 0.0))
    requested_end = params.get("end_time")
    end = source_duration if requested_end is None else float(requested_end)
    if start < 0 or end <= start or end > source_duration + 0.05:
        raise VideoProcessingError(
            f"Invalid trim range. Expected 0 <= start < end <= {source_duration:.2f}"
        )

    settings.ensure_directories()
    final_path = settings.output_folder / f"video-{video_id}-{uuid.uuid4().hex[:10]}.mp4"

    with tempfile.TemporaryDirectory(dir=settings.output_folder, prefix=f"render-{video_id}-") as temp_dir:
        temp_root = Path(temp_dir)
        trimmed = temp_root / "01-trimmed.mp4"
        trim_video(source, trimmed, start, end)
        current = trimmed
        report(45)

        if bool(params.get("is_vertical", True)):
            vertical = temp_root / "02-vertical.mp4"
            make_vertical(current, vertical, float(params.get("crop_position", 0.5)))
            current = vertical
        report(75)

        if params.get("auto_subtitles"):
            subtitle_source = _auto_subtitles([(video_id, start, end)], temp_root / "auto.srt")
            subtitled = temp_root / "auto-subtitled.mp4"
            burn_subtitles(current, subtitled, subtitle_source)
            current = subtitled

        subtitle_path = params.get("subtitle_path")
        if subtitle_path:
            subtitled = temp_root / "03-subtitled.mp4"
            burn_subtitles(current, subtitled, subtitle_path)
            current = subtitled
        report(85)

        subtitle_text = str(params.get("subtitle_text", "")).strip()
        if subtitle_text:
            captioned = temp_root / "04-captioned.mp4"
            add_text(
                current,
                captioned,
                subtitle_text,
                position=str(params.get("text_position", "bottom")),
                font_size=int(params.get("font_size", 64)),
                font_color=str(params.get("font_color", "white")),
            )
            current = captioned
        report(92)

        shutil.move(str(current), final_path)

    rendered_duration = probe_duration(final_path)
    report(100)
    return str(final_path), rendered_duration
