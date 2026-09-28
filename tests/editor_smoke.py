"""Real media / Qt integration check, isolated from the user's database.

Run: python tests/editor_smoke.py
Creates screenshots and a rendered test clip in work/editor-check.
"""
from pathlib import Path
import os
import sys
import time
import subprocess
import sqlite3
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECK = ROOT / "work" / "editor-check"
CHECK.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["DATABASE_URL"] = f"sqlite:///{(CHECK / 'check.sqlite3').as_posix()}"
os.environ["OUTPUT_FOLDER"] = str(CHECK)
os.environ["UPLOAD_FOLDER"] = str(CHECK / "uploads")
os.environ["CACHE_FOLDER"] = str(CHECK / "cache")
os.environ["TAISLY_API_KEY"] = ""

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QApplication
from app.config import settings
from app.models import SessionLocal, Transcript, TranscriptSegment, init_db
from app.video_processor import probe_video_metadata, render_title_layers
from gui.main_window import MainWindow
from gui.theme import apply_theme


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for editor operation")
        QTest.qWait(25)


def main():
    black = CHECK / "title-base.mp4"
    moving_title = CHECK / "title-motion.mp4"
    subprocess.run([settings.ffmpeg_binary, "-hide_banner",
                    "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=black:s=320x180:r=25", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black)],
                   check=True, timeout=30)
    render_title_layers(black, moving_title, [{"text": "X", "start": 0, "end": 2,
        "font_size": 64, "color": "white", "keyframes": [
            {"time": 0, "x": 0.2, "y": 0.5, "opacity": 1},
            {"time": 2, "x": 0.8, "y": 0.5, "opacity": 1},
        ]}], 2)
    def bright_center(seconds: float) -> float:
        frame = subprocess.run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error",
            "-ss", str(seconds), "-i", str(moving_title), "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True, timeout=20).stdout
        bright = [index % 320 for index, value in enumerate(frame) if value > 190]
        assert bright
        return sum(bright) / len(bright)
    assert bright_center(1.5) - bright_center(0.3) > 80
    fixture = CHECK / "moving-test.mp4"
    if "--latest-source" in sys.argv:
        connection = sqlite3.connect(f"file:{(ROOT / 'video_editor.sqlite3').as_posix()}?mode=ro", uri=True)
        try:
            fixture = Path(connection.execute("SELECT original_path FROM videos ORDER BY id DESC LIMIT 1").fetchone()[0])
        finally:
            connection.close()
    else:
        subprocess.run([
            settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(fixture),
        ], check=True, timeout=30)
    init_db()
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "arialbd.ttf", "consola.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            print("font", name, QFontDatabase.addApplicationFont(str(path)))
    app.setStyle("Fusion")
    window = MainWindow()
    errors = []
    def on_exception(kind, value, tb):
        import traceback
        rendered = "".join(traceback.format_exception(kind, value, tb))
        errors.append(rendered)
        print(rendered, file=sys.stderr, flush=True)
    sys.excepthook = on_exception
    window.resize(1380, 860)
    window.show()
    editor = window.editor_workspace
    editor.upload_widget.load_video(str(fixture))
    wait_for(lambda: editor.video_id is not None and not editor.canvas.image.isNull() and not editor.is_busy())
    assert Path(editor.source_path).parent == settings.upload_folder
    editor.edit_widget.crop_position.setValue(15)
    crop = editor.canvas.source_rect()
    assert abs(crop.x() / (editor.canvas.image.width() - crop.width()) - 0.15) < 0.01
    editor.edit_widget.subtitle_edit.setText("Проверка монтажа")
    editor.edit_widget.font_size.setValue(92)
    editor.edit_widget.font_color.setCurrentIndex(1)
    editor.seek_seconds(1)
    wait_for(lambda: editor._last_frame_time == 1 and not editor.is_busy())
    assert editor.canvas.source_rect().width() / editor.canvas.source_rect().height() == 9 / 16
    frames = QSignalSpy(editor.video_sink.videoFrameChanged)
    editor.toggle_playback()
    wait_for(lambda: editor.player.position() > 1500)
    assert not editor._player_failed, "Qt playback failed"
    assert len(frames) > 2 and any(item[0].isValid() for item in frames), "Playback clock advanced without decoded video frames"
    editor.seek_seconds(2)
    wait_for(lambda: editor._last_frame_time == 2 and not editor.is_busy())
    timeline = editor.timeline
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(round(timeline._x_for_time(0)), 65))
    QTest.mouseMove(timeline, QPoint(round(timeline._x_for_time(1)), 65))
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(round(timeline._x_for_time(1)), 65))
    expected_start = editor.edit_widget.start_time.value()
    assert abs(expected_start - 1) < max(0.03, timeline.duration / timeline._content_width())
    editor.edit_widget.start_time.setValue(1)
    editor.edit_widget.end_time.setValue(4)
    assert timeline.end_time == 4
    editor.zoom_combo.setCurrentIndex(3)
    QTest.qWait(100)
    assert timeline.width() > editor.timeline_scroll.viewport().width() * 7
    assert timeline.end_time == 4
    editor.zoom_combo.setCurrentIndex(0)
    editor.edit_widget.edit_tabs.setCurrentIndex(1)
    QTest.qWait(200)
    assert window.grab().save(str(CHECK / "editor-wide.png"))
    apply_theme(window, light=True)
    QTest.qWait(150)
    assert window.grab().save(str(CHECK / "editor-light.png"))
    window.navigate("dashboard")
    QTest.qWait(150)
    assert window.grab().save(str(CHECK / "dashboard-light.png"))
    apply_theme(window)
    QTest.qWait(150)
    assert window.grab().save(str(CHECK / "dashboard-dark.png"))
    window.navigate("editor")
    window.resize(1040, 700)
    QTest.qWait(200)
    assert window.grab().save(str(CHECK / "editor-small.png"))
    print("window size", window.width(), window.height(), flush=True)
    assert window.width() <= 1040, "Layout exceeds the supported minimum window width"
    assert window.toolbar.isVisible()
    for key, _, label in window.PAGE_ORDER:
        assert window.page_actions[key].text() == label
    assert window.rect().contains(editor.edit_widget.render_button.mapTo(window, QPoint(0, 0))), "Export button is outside the window"
    window.resize(1380, 860)
    draft_id = editor.video_id
    editor.save_project()
    window.history_widget.refresh()
    assert window.history_widget.projects_table.rowCount() >= 1
    window.history_widget.open_project_for_row(0)
    wait_for(lambda: not editor.is_busy())
    assert editor.video_id == draft_id
    assert editor.edit_widget.output_path is None
    assert editor.edit_widget.subtitle_edit.text() == "Проверка монтажа"
    assert editor.edit_widget.font_size.value() == 92
    assert editor.edit_widget.font_color.currentData() == "yellow"
    assert editor.edit_widget.crop_position.value() == 15
    assert abs(editor.edit_widget.start_time.value() - 1) < 0.03
    editor.edit_widget.start_render()
    wait_for(lambda: editor.edit_widget.worker is None, seconds=90)
    output = editor.edit_widget.output_path
    assert output, "Render did not complete"
    duration, width, height = probe_video_metadata(output)
    assert abs(duration - 3) < 0.1 and (width, height) == (1080, 1920)
    assert window.pages.currentWidget() is editor, "Export navigated away from the editor"
    current_id = editor.video_id
    editor.edit_widget.subtitle_edit.setText("Temporary change")
    editor.save_project()
    editor.open_existing(current_id)
    wait_for(lambda: not editor.is_busy())
    assert editor.edit_widget.subtitle_edit.text() == "Temporary change"
    assert editor.edit_widget.font_size.value() == 92
    assert editor.edit_widget.font_color.currentData() == "yellow"
    assert abs(editor.edit_widget.start_time.value() - 1) < 0.03
    second = CHECK / "silent-second.mp4"
    subprocess.run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=green:s=640x360:r=25", "-t", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(second)],
                   check=True, timeout=30)
    music = CHECK / "music.wav"
    subprocess.run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100",
                    "-t", "6", str(music)], check=True, timeout=30)
    editor._append_next_video = True
    editor.upload_widget.load_video(str(second))
    wait_for(lambda: len(editor.sequence_widget.clips) == 2 and not editor.is_busy())
    wait_for(lambda: Path(editor.source_path).name.startswith("video-"))
    wait_for(lambda: not editor.canvas.image.isNull() and editor._last_frame_time == 0)
    editor.sequence_widget.move_selected(-1)
    assert editor.sequence_widget.clips[0]["name"] == second.name
    editor.sequence_widget.move_selected(1)
    assert editor.sequence_widget.clips[1]["name"] == second.name
    editor.sequence_widget.set_selected_range(0.5, 2.5)
    with patch("gui.sequence_widget.QFileDialog.getOpenFileName", return_value=(str(music), "")):
        editor.sequence_widget.choose_music()
    wait_for(lambda: editor.sequence_widget.music_import_worker is None)
    managed_music = editor.sequence_widget.music_path
    assert Path(managed_music).parent == settings.upload_folder
    wait_for(lambda: Path(editor.source_path).name.startswith("video-") and not editor.canvas.image.isNull()
             and editor._last_frame_time == 0)
    wait_for(lambda: not editor.is_busy())
    QTest.qWait(500)
    editor.open_existing(current_id)
    wait_for(lambda: not editor.is_busy())
    assert len(editor.sequence_widget.clips) == 2
    assert editor.sequence_widget.table.currentIndex().row() == 1
    assert editor.sequence_widget.music_path == managed_music
    assert abs(editor.sequence_widget.clips[1]["start_time"] - 0.5) < 0.02
    editor.play_sequence()
    wait_for(lambda: editor._sequence_index == 1, seconds=10)
    wait_for(lambda: not editor._sequence_playback, seconds=10)
    assert editor.sequence_widget.table.currentIndex().row() == 1
    editor.editor_tabs.setCurrentWidget(editor.sequence_scroll)
    QTest.qWait(100)
    assert window.grab().save(str(CHECK / "sequence-dark.png"))
    window.resize(1040, 700)
    QTest.qWait(100)
    assert window.grab().save(str(CHECK / "sequence-small.png"))
    window.resize(1380, 860)
    editor.edit_widget.start_render()
    wait_for(lambda: editor.edit_widget.worker is None, seconds=120)
    sequence_output = editor.edit_widget.output_path
    assert sequence_output, "Sequence export did not complete"
    sequence_duration, sequence_width, sequence_height = probe_video_metadata(sequence_output)
    assert abs(sequence_duration - 5) < 0.15 and (sequence_width, sequence_height) == (1080, 1920)
    editor.open_existing(current_id)
    wait_for(lambda: not editor.is_busy())
    assert len(editor.sequence_widget.clips) == 2
    assert editor.edit_widget.output_path == sequence_output
    assert editor.sequence_widget.music_path == managed_music
    assert abs(editor.sequence_widget.clips[1]["start_time"] - 0.5) < 0.02
    with SessionLocal() as session:
        for clip in editor.sequence_widget.clips:
            session.add(Transcript(video_id=clip["video_id"], status="ready", text="test speech",
                segments=[TranscriptSegment(start_time=1, end_time=1.5, text="test speech")]))
        session.commit()
    editor.sequence_widget.transition.setCurrentIndex(1)
    editor.edit_widget.auto_subtitles.setChecked(True)
    editor.layers_widget.add_title()
    assert len(editor.layers_widget.layers) == 1
    editor.layers_widget.text.setText("Animated test title")
    editor.layers_widget.key_table.selectRow(1)
    editor.layers_widget.key_x.setValue(30)
    editor.layers_widget.key_y.setValue(55)
    editor.save_project()
    editor.open_existing(current_id)
    wait_for(lambda: not editor.is_busy())
    assert editor.layers_widget.layers[0]["text"] == "Animated test title"
    assert editor.layers_widget.layers[0]["keyframes"][1]["x"] == 0.3
    overlay_source = editor.sequence_widget.clips[1]["video_id"]
    editor.video_layers_widget.source.setCurrentIndex(editor.video_layers_widget.source.findData(overlay_source))
    editor.video_layers_widget.add_layer()
    assert editor.video_layers_widget.layers[0]["video_id"] == overlay_source
    editor.video_layers_widget.start.setValue(1)
    editor.video_layers_widget.width.setValue(50)
    editor.video_layers_widget.opacity.setValue(80)
    editor.save_project()
    editor.open_existing(current_id)
    wait_for(lambda: not editor.is_busy())
    assert editor.video_layers_widget.layers[0]["video_id"] == overlay_source
    assert editor.video_layers_widget.layers[0]["start"] == 1
    editor.editor_tabs.setCurrentWidget(editor.layers_widget)
    QTest.qWait(100)
    assert window.grab().save(str(CHECK / "title-layers.png"))
    editor.editor_tabs.setCurrentWidget(editor.video_layers_widget)
    QTest.qWait(100)
    assert window.grab().save(str(CHECK / "video-layers.png"))
    editor.toggle_effect_preview()
    wait_for(lambda: editor._effect_preview_worker is None, seconds=120)
    assert editor._effect_preview_active
    proxy = editor.source_path
    assert proxy and Path(proxy).parent == settings.cache_folder
    proxy_duration, proxy_width, proxy_height = probe_video_metadata(proxy)
    assert abs(proxy_duration - 4.5) < 0.15 and (proxy_width, proxy_height) == (540, 960)
    pixel = subprocess.run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error",
                            "-ss", "1.5", "-i", proxy, "-frames:v", "1",
                            "-vf", "crop=2:2:270:120", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, check=True, timeout=20).stdout
    assert len(pixel) == 12 and pixel[1] > pixel[0] * 1.3 and pixel[1] > pixel[2] * 1.3, pixel
    editor.toggle_effect_preview()
    wait_for(lambda: not editor.is_busy())
    assert not editor._effect_preview_active
    editor.edit_widget.start_render()
    wait_for(lambda: editor.edit_widget.worker is None, seconds=120)
    dissolve_output = editor.edit_widget.output_path
    assert dissolve_output, "Dissolve export did not complete"
    dissolve_duration, _, _ = probe_video_metadata(dissolve_output)
    assert abs(dissolve_duration - 4.5) < 0.15
    editor.open_existing(current_id)
    wait_for(lambda: not editor.is_busy())
    assert editor.sequence_widget.transition.currentData() == "dissolve"
    assert editor.edit_widget.auto_subtitles.isChecked()
    assert editor.layers_widget.layers[0]["text"] == "Animated test title"
    assert editor.video_layers_widget.layers[0]["video_id"] == overlay_source
    editor.shutdown_preview()
    wait_for(lambda: not window.publish_widget.is_busy())
    if errors:
        raise AssertionError("\n".join(errors))
    window.close()
    print(f"PASS: {fixture.name}: playback, decoded frames, trim drag, live crop/text, render {duration:.2f}s {width}x{height}, screenshots", flush=True)


if __name__ == "__main__":
    main()
