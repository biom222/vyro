"""Real FFmpeg hardening checks; artifacts and a JSON report stay under ignored work/."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECK = ROOT / "work" / "media-check"
CHECK.mkdir(parents=True, exist_ok=True)
RUN = Path(tempfile.mkdtemp(prefix="run ' кириллица-", dir=CHECK))
for key, value in {"DATABASE_URL": f"sqlite:///{(RUN / 'check.sqlite3').as_posix()}",
                   "DATA_FOLDER": str(RUN / "data"), "CACHE_FOLDER": str(RUN / "cache"),
                   "UPLOAD_FOLDER": str(RUN / "uploads"), "OUTPUT_FOLDER": str(RUN / "outputs"),
                   "SCHEDULER_ENABLED": "false", "QT_QPA_PLATFORM": "offscreen"}.items():
    os.environ[key] = value

from PyQt6.QtCore import QCoreApplication, QTimer
from app.config import settings
from app.models import Project, SessionLocal, Video, Transcript, TranscriptSegment, init_db
from app.media_process import VideoProcessingError
from app.video_processor import probe_video_metadata, render_preview, render_sequence, render_video
from gui.worker import RenderWorker, PreviewRenderWorker


def ffmpeg(args):
    subprocess.run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def streams(path):
    return json.loads(subprocess.run([settings.ffprobe_binary, "-v", "error", "-show_streams",
        "-show_format", "-of", "json", str(path)], capture_output=True, check=True, timeout=30).stdout)


def register(path, project_id):
    duration, width, height = probe_video_metadata(path)
    with SessionLocal() as session:
        video = Video(project_id=project_id, filename=path.name, original_path=str(path),
                      duration=duration, width=width, height=height, status="uploaded")
        session.add(video)
        session.commit()
        return video.id


def frame(path, seconds):
    return subprocess.run([settings.ffmpeg_binary, "-v", "error", "-ss", str(seconds), "-i", str(path),
        "-frames:v", "1", "-vf", "scale=160:284", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=30).stdout


def main():
    init_db()
    settings.ensure_directories()
    app = QCoreApplication([])
    with SessionLocal() as session:
        project = Project(name="Media matrix")
        session.add(project)
        session.commit()
        project_id = project.id
    report = {"run": str(RUN), "inputs": [], "checks": []}
    cases = [("landscape24", "320x180", "24", "44100"),
             ("portrait2997", "180x320", "30000/1001", "48000"),
             ("square60-silent", "240x240", "60", None),
             ("vfr", "320x180", "30", "32000"),
             ("odd", "321x181", "25", None)]
    ids = []
    for name, size, fps, audio_rate in cases:
        folder = RUN / "исходники с пробелами ' тест"
        folder.mkdir(exist_ok=True)
        path = folder / (name + (".mkv" if name == "odd" else ".mp4"))
        args = ["-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration=1.6"]
        if audio_rate:
            audio_duration = 0.7 if name == "landscape24" else 1.6
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={audio_rate}:duration={audio_duration}"]
        if name == "vfr":
            args += ["-vf", "select='if(lt(t,0.8),not(mod(n,2)),1)'", "-fps_mode", "vfr"]
        args += ["-c:v", "ffv1" if name == "odd" else "libx264", "-pix_fmt", "yuv444p" if name == "odd" else "yuv420p"]
        if audio_rate:
            args += ["-c:a", "aac"]
        ffmpeg([*args, str(path)])
        if name == "vfr":
            stream = streams(path)["streams"][0]
            assert stream["r_frame_rate"] != stream["avg_frame_rate"]
        ids.append(register(path, project_id))
        report["inputs"].append({"name": name, "size": size, "fps": fps, "sample_rate": audio_rate})
    # Verify supported software HEVC separately from unavailable hardware encoders.
    hevc = RUN / "hevc.mp4"
    ffmpeg(["-f", "lavfi", "-i", "color=c=orange:s=180x320:r=25:d=1.6", "-c:v", "libx265",
            "-preset", "ultrafast", "-x265-params", "log-level=error", str(hevc)])
    ids.append(register(hevc, project_id))
    report["inputs"].append({"name": "HEVC/libx265"})
    # A real >260 character Windows path, not merely a long display name.
    long_folder = RUN / ("a" * 80) / ("b" * 80)
    long_folder.mkdir(parents=True)
    long_path = long_folder / "длинный путь.mp4"
    import shutil
    shutil.copy2(hevc, long_path)
    ids.append(register(long_path, project_id))
    report["checks"].append({"long_path_characters": len(str(long_path))})
    export_cases = list(enumerate(("24", "25", "30", "50", "60", "source", "24"))) + [(1, "source")]
    for index, fps in export_cases:
        params = {"clips": [{"video_id": ids[index], "start_time": 0.2, "end_time": 1.2}],
                  "fps": fps, "quality": "high", "is_vertical": True}
        observed = []
        output, duration = render_sequence(ids[0], params, observed.append)
        meta = streams(output)
        video, audio = meta["streams"][:2]
        assert (video["width"], video["height"], video["codec_name"], video["pix_fmt"]) == (1080, 1920, "h264", "yuv420p")
        assert audio["codec_name"] == "aac" and abs(duration - 1) < 0.1
        assert observed == sorted(observed) and observed[-1] == 100
        if fps != "source":
            assert video["avg_frame_rate"] == f"{fps}/1"
        elif index == 1:
            assert video["avg_frame_rate"] == "30000/1001"
        data = Path(output).read_bytes()
        assert data.index(b"moov") < data.index(b"mdat")
        report["checks"].append({"export_fps": fps, "actual_fps": video["avg_frame_rate"], "duration": duration})
    # Invalid inputs must yield domain errors, not IndexError / JSON errors.
    audio_path = RUN / "audio-only.wav"
    ffmpeg(["-f", "lavfi", "-i", "sine=duration=1", str(audio_path)])
    corrupt = RUN / "corrupt.mp4"
    corrupt.write_bytes(b"not a video")
    for path in (audio_path, corrupt):
        try:
            probe_video_metadata(path)
        except VideoProcessingError:
            pass
        else:
            raise AssertionError(f"Accepted invalid video: {path}")
    report["checks"].append("audio-only and corrupt input rejected")
    with SessionLocal() as session:
        session.add(Transcript(video_id=ids[0], status="ready", text="Timed speech",
            segments=[TranscriptSegment(start_time=0.4, end_time=0.8, text="Timed speech")]))
        session.commit()
    # Mixed sources, trim, crop, dissolve, music, timed title and overlay share one graph.
    params = {"clips": [{"video_id": value, "start_time": 0.2, "end_time": 1.2} for value in ids[:3]],
              "fps": "25", "transition": "dissolve", "transition_duration": 0.2,
              "crop_position": 0.25, "is_vertical": True, "music_path": str(audio_path), "music_volume": 0.2,
              "subtitle_text": "Test", "font_size": 24, "auto_subtitles": True,
              "title_layers": [{"text": "Title", "start": 0.4, "end": 2.2, "font_size": 64,
                  "keyframes": [{"time": 0.4, "x": 0.2, "y": 0.3, "opacity": 0},
                                {"time": 2.2, "x": 0.8, "y": 0.7, "opacity": 1}]}],
              "video_layers": [{"video_id": ids[1], "start": 0.3, "end": 1.1, "source_start": 0,
                                 "width": 0.3, "x": 0.1, "y": 0.1, "opacity": 0.7}]}
    preview, preview_duration = render_preview(ids[0], params)
    output, duration = render_sequence(ids[0], params)
    assert abs(preview_duration - duration) < 0.05 and abs(duration - 2.6) < 0.1
    differences = []
    for timestamp in (0.1, 0.5, 0.9, 1.5, 2.4):
        first, second = frame(preview, timestamp), frame(output, timestamp)
        assert len(first) == len(second) == 160 * 284 * 3
        error = sum(abs(a-b) for a, b in zip(first, second)) / len(first)
        assert error < 12, (timestamp, error)
        differences.append(round(error, 3))
    report["checks"].append({"proxy_export_frame_MAE_255": differences})
    from array import array
    def audio_samples(path):
        data = subprocess.run([settings.ffmpeg_binary, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
            "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True, timeout=30).stdout
        result = array("h")
        result.frombytes(data)
        return result
    first_audio, second_audio = audio_samples(preview), audio_samples(output)
    assert abs(len(first_audio) - len(second_audio)) < 100
    audio_error = sum(abs(a-b) for a,b in zip(first_audio, second_audio)) / min(len(first_audio), len(second_audio)) / 32768
    assert audio_error < 0.01 and max(map(abs, first_audio)) > 500, audio_error
    report["checks"].append({"proxy_export_audio_MAE": round(audio_error, 6)})
    # Full 10-minute logical project across the supported 30 slots; preview lowers test cost.
    long_source = RUN / "long-source.mp4"
    ffmpeg(["-f", "lavfi", "-i", "color=c=gray:s=64x64:r=1:d=20", "-c:v", "libx264", str(long_source)])
    long_id = register(long_source, project_id)
    with SessionLocal() as session:
        retained = session.get(Video, long_id)
        retained.output_path = output
        retained.output_duration = duration
        retained.status = "ready"
        session.commit()
    long_params = {"clips": [{"video_id": long_id, "start_time": 0, "end_time": 20} for _ in range(30)],
                   "fps": "24", "is_vertical": False}
    long_output, long_duration = render_preview(long_id, long_params)
    assert abs(long_duration - 600) < 0.1, long_duration
    report["checks"].append({"30_clips_preview_duration": long_duration})
    short_params = {"clips": [{"video_id": ids[index % len(ids)], "start_time": 0.2, "end_time": 0.6}
                              for index in range(30)], "fps": "25", "is_vertical": True}
    short_output, short_duration = render_sequence(ids[0], short_params)
    assert abs(short_duration - 12) < 0.1, short_duration
    assert probe_video_metadata(short_output)[1:] == (1080, 1920)
    report["checks"].append({"30_mixed_clips_final_duration": short_duration})
    # Worker cancellation while the event loop continues servicing a timer.
    for worker_class in (RenderWorker, PreviewRenderWorker):
        worker_params = {**long_params, "clips": long_params["clips"][:1], "is_vertical": True, "fps": "60"}
        worker = worker_class(long_id, worker_params)
        beats, cancelled, errors = [], [], []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: beats.append(1))
        worker.cancelled.connect(lambda: cancelled.append(True))
        worker.error.connect(errors.append)
        before = set(settings.output_folder.glob("*.mp4"))
        timer.start()
        from unittest.mock import patch
        real_popen = subprocess.Popen
        encoders = []
        def spawn(command, *args, **kwargs):
            process = real_popen(command, *args, **kwargs)
            if "ffmpeg" in Path(command[0]).name.lower():
                encoders.append(process)
            return process
        with patch("app.media_process.subprocess.Popen", side_effect=spawn):
            worker.start()
            QTimer.singleShot(350, worker.cancel)
            deadline = time.monotonic() + 10
            while worker.isRunning():
                app.processEvents()
                time.sleep(0.01)
                assert time.monotonic() < deadline
        worker.wait()
        app.processEvents()
        timer.stop()
        assert cancelled and not errors and len(beats) >= 3, (cancelled, errors, len(beats))
        assert encoders and all(process.poll() is not None for process in encoders)
        assert set(settings.output_folder.glob("*.mp4")) == before
        assert not list(settings.output_folder.glob("sequence-*"))
        assert not list(settings.cache_folder.glob("sequence-*"))
        with SessionLocal() as session:
            retained = session.get(Video, long_id)
            assert retained.status == "ready" and retained.output_path == output and retained.error_message is None
        assert Path(output).is_file()
        report["checks"].append({"cancelled_worker": worker_class.__name__, "event_loop_ticks": len(beats)})
    report["status"] = "passed"
    (CHECK / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
