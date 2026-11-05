"""Editor keyboard/selection/resize checks on isolated media; run --matrix for 3 DPI scales."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import faulthandler
from unittest.mock import patch
faulthandler.enable()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECK = ROOT / "work" / "editor-ui"
CHECK.mkdir(parents=True, exist_ok=True)


def matrix():
    for scale in ("1", "1.25", "1.5"):
        environment = {**os.environ, "QT_SCALE_FACTOR": scale, "QT_QPA_PLATFORM": "offscreen"}
        subprocess.run([sys.executable, str(Path(__file__).resolve())], env=environment, check=True, timeout=180)


def main():
    run = Path(tempfile.mkdtemp(prefix="ui-", dir=CHECK))
    for key, value in {"DATABASE_URL": f"sqlite:///{(run / 'test.sqlite3').as_posix()}",
        "UPLOAD_FOLDER": str(run / "uploads"), "OUTPUT_FOLDER": str(run / "outputs"),
        "DATA_FOLDER": str(run / "data"), "CACHE_FOLDER": str(run / "cache"),
        "AI_PROVIDER": "mock", "TRANSCRIPTION_PROVIDER": "mock", "TRENDS_MOCK_MODE": "true",
        "SCHEDULER_ENABLED": "false"}.items():
        os.environ[key] = value
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QFontDatabase
    from PyQt6.QtTest import QTest, QSignalSpy
    from PyQt6.QtWidgets import QApplication
    from app.models import SessionLocal, Video, init_db
    from app.config import settings
    from gui.main_window import MainWindow
    from gui.theme import apply_theme

    def wait(predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < deadline, "Editor UI operation timed out"
            QTest.qWait(20)

    init_db()
    app = QApplication([])
    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        for name in ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "arialbd.ttf", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"], "Fonts", name)))
    window = MainWindow()
    window.show()
    window.activateWindow()
    editor = window.editor_workspace
    QTest.qWait(100)
    fixture = run / "source.mp4"
    subprocess.run([settings.ffmpeg_binary, "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=s=320x180:r=25:d=5", "-c:v", "libx264", str(fixture)], check=True, timeout=30)
    empty_sizes = ((1040, 700),) if "--interactive" in sys.argv else ((1040, 700), (1380, 860), (1920, 1080))
    for width, height in empty_sizes:
        window.resize(width, height)
        QTest.qWait(50)
        assert window.width() == width and window.height() == height, (window.size(), width, height)
        window.grab().save(str(run / f"empty-{width}.png"))
    editor.upload_widget.load_video(str(fixture))
    wait(lambda: editor.video_id is not None and not editor.is_busy())
    wait(lambda: editor.source_path in editor._media_timing)
    first_id = editor.video_id
    with SessionLocal() as session:
        second = Video(project_id=editor.project_id, filename="Second source", original_path=str(fixture),
                       duration=5, width=320, height=180, status="uploaded")
        session.add(second)
        session.commit()
        second_id = second.id
    editor.sequence_widget.add_video(second_id, "Second source", 5)
    editor.layers_widget.add_title()
    editor.video_layers_widget.add_layer()
    editor.sequence_widget.set_music(str(fixture))  # Geometry only; no music decode in this check.
    if "--interactive" in sys.argv:
        window.setWindowTitle("vyro - Phase 3 UI check")
        window.resize(1040, 700)
        editor.editor_tabs.setCurrentIndex(1)
        print(f"Native UI fixture: {run}", flush=True)
        raise SystemExit(app.exec())
    editor.editor_tabs.setCurrentIndex(0)
    wait(lambda: not editor.is_busy())
    editor.seek_seconds(1)
    QTest.keyClick(editor.canvas, Qt.Key.Key_I)
    assert abs(editor.edit_widget.start_time.value() - 1) < 0.01
    editor.seek_seconds(3)
    QTest.keyClick(editor.canvas, Qt.Key.Key_O)
    assert abs(editor.edit_widget.end_time.value() - 3) < 0.01
    editor.sequence_widget.set_selected_range(0, 5)
    editor.seek_seconds(0)
    wait(lambda: not editor.is_busy())
    editor.seek_seconds(1)
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_Right)
    assert abs(editor.timeline.position - 1.04) < 0.001, editor.timeline.position
    QTest.keyClick(editor.canvas, Qt.Key.Key_Right)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Left)
    assert abs(editor.timeline.position - 1.04) < 0.001
    wait(lambda: not editor.is_busy())
    assert abs(editor._last_frame_time - 1.04) < 0.002
    editor.seek_seconds(4.96)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Right)
    assert abs(editor.timeline.position - 4.96) < 0.001
    QTest.keyClick(editor.canvas, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert editor.timeline.position == 0
    wait(lambda: not editor.is_busy())

    # Source selection maps output time into the correct trim and contextual properties.
    editor.editor_tabs.setCurrentIndex(1)
    QTest.qWait(50)
    second_item = next(item for item in editor.composition.items if item[:2] == ("video", 1))
    QTest.mouseClick(editor.composition, Qt.MouseButton.LeftButton,
                     pos=editor.composition.item_rect(second_item).center().toPoint())
    assert editor.sequence_widget.table.currentIndex().row() == 1
    assert editor.inspector_pages.currentIndex() == 1
    editor.seek_composition(6)
    assert abs(editor.timeline.position - 1) < 0.01
    title = next(item for item in editor.composition.items if item[0] == "title")
    QTest.mouseClick(editor.composition, Qt.MouseButton.LeftButton,
                     pos=editor.composition.item_rect(title).center().toPoint())
    assert editor.editor_tabs.currentIndex() == editor.inspector_pages.currentIndex() == 2
    original = editor.layers_widget.text.text()
    position = editor.timeline.position
    editor.layers_widget.text.setFocus()
    QTest.keyClicks(editor.layers_widget.text, " i o ")
    assert editor.layers_widget.text.text().endswith(" i o ")
    assert editor.timeline.position == position
    QTest.keyClick(editor.layers_widget.text, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor.layers_widget.text, Qt.Key.Key_Delete)
    assert len(editor.layers_widget.layers) == 1  # Text deletion must never delete a title layer.
    QTest.keyClick(editor.layers_widget.text, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert editor.layers_widget.text.text()
    QTest.keyClick(editor.layers_widget.text, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert not editor._unsaved_changes
    editor.layers_widget.key_table.selectRow(1)
    editor.layers_widget.key_table.setFocus()
    key_count = len(editor.layers_widget.layers[0]["keyframes"])
    QTest.keyClick(editor.layers_widget.key_table, Qt.Key.Key_Delete)
    assert len(editor.layers_widget.layers) == 1
    assert len(editor.layers_widget.layers[0]["keyframes"]) == key_count - 1

    # Overlapping layers get independent rows, with a scrollbar rather than hidden bars.
    from copy import deepcopy
    titles, overlays = deepcopy(editor.layers_widget.layers), deepcopy(editor.video_layers_widget.layers)
    for _ in range(7):
        editor.layers_widget.add_title()
    for _ in range(3):
        editor.video_layers_widget.add_layer()
    editor._refresh_composition()
    QTest.qWait(30)
    assert len(editor.composition.rows) == 14
    assert editor.composition_scroll.verticalScrollBar().maximum() > 0
    title_rects = [editor.composition.item_rect(item) for item in editor.composition.items if item[0] == "title"]
    assert len({rect.top() for rect in title_rects}) == 8
    window.grab().save(str(run / "all-layers.png"))
    editor.layers_widget.set_layers(titles, editor._sequence_duration())
    editor.video_layers_widget.set_layers(overlays, editor.sequence_widget.clips, editor._sequence_duration())
    editor._refresh_composition()

    # Window layout and fixed footer stay usable at each requested logical size.
    geometry = []
    for width, height in ((1040, 700), (1380, 860), (1920, 1080)):
        window.resize(width, height)
        QTest.qWait(70)
        for tab in range(4):
            editor.editor_tabs.setCurrentIndex(tab)
            QTest.qWait(40)
            assert (window.width(), window.height()) == (width, height), (window.size(), width, height, tab)
            assert editor.inspector_pages.currentIndex() == tab
            assert editor.canvas.width() >= 180 and editor.canvas.height() >= 96
            progress = editor.edit_widget.progress
            point = progress.mapTo(window, QPoint(0, 0))
            assert point.y() + progress.height() <= window.height() - 10
            assert editor.workspace_splitter.count() == 3
            window.grab().save(str(run / f"loaded-{width}-tab{tab}.png"))
        geometry.append({"window": [width, height], "canvas": [editor.canvas.width(), editor.canvas.height()],
                         "splitter": editor.vertical_splitter.sizes()})
    editor.workspace_splitter.setSizes([200, 800, 330])
    editor.vertical_splitter.setSizes([400, 400])
    QTest.qWait(50)
    before = editor.vertical_splitter.sizes()
    for tab in (2, 3, 1):
        editor.editor_tabs.setCurrentIndex(tab)
        QTest.qWait(20)
        assert all(abs(a-b) < 3 for a,b in zip(before, editor.vertical_splitter.sizes()))
    editor.zoom_combo.setCurrentIndex(2)
    QTest.qWait(30)
    assert editor.composition.width() >= editor.composition_scroll.viewport().width() * 3.9
    window.resize(1380, 860)
    QTest.qWait(50)
    assert editor.composition.width() >= editor.composition_scroll.viewport().width() * 3.9
    assert editor.composition_scroll.horizontalScrollBar().maximum() > 0
    editor.zoom_combo.setCurrentIndex(0)
    editor.editor_tabs.setCurrentIndex(2)
    editor.layers_widget.table.setFocus()
    QTest.keyClick(editor.layers_widget.table, Qt.Key.Key_Delete)
    assert not editor.layers_widget.layers
    editor.editor_tabs.setCurrentIndex(3)
    editor.video_layers_widget.table.setFocus()
    QTest.keyClick(editor.video_layers_widget.table, Qt.Key.Key_Delete)
    assert not editor.video_layers_widget.layers
    editor.sequence_widget.table.selectRow(1)
    editor.editor_tabs.setCurrentIndex(1)
    editor.sequence_widget.table.setFocus()
    QTest.keyClick(editor.sequence_widget.table, Qt.Key.Key_Delete)
    assert len(editor.sequence_widget.clips) == 1
    QTest.keyClick(editor.sequence_widget.table, Qt.Key.Key_Delete)
    assert len(editor.sequence_widget.clips) == 1 and editor.sequence_widget.clips[0]["video_id"] == first_id
    editor.sequence_widget.set_music("")
    editor.editor_tabs.setCurrentIndex(0)
    wait(lambda: not editor.is_busy())
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_Space)
    QTest.qWait(100)
    assert editor.player.playbackState() == editor.player.PlaybackState.PlayingState
    QTest.keyClick(editor.canvas, Qt.Key.Key_Space)
    assert editor.player.playbackState() != editor.player.PlaybackState.PlayingState
    wait(lambda: not editor.is_busy())
    with patch("gui.upload_widget.QFileDialog.getOpenFileName", return_value=("", "")) as dialog:
        QTest.keyClick(editor.canvas, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
        assert dialog.called
    QTest.keyClick(editor.canvas, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert editor.edit_widget.worker is not None
    cancelled = QSignalSpy(editor.edit_widget.worker.cancelled)
    QTest.qWait(100)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Period, Qt.KeyboardModifier.ControlModifier)
    wait(lambda: editor.edit_widget.worker is None, seconds=10)
    assert len(cancelled) == 1
    editor.editor_tabs.setCurrentIndex(3)
    editor.zoom_combo.setCurrentIndex(1)
    assert editor.save_project()
    saved_sizes = editor.workspace_splitter.sizes()
    # Unload the project before changing local controls: opening a currently active
    # project intentionally saves its latest UI state first.
    editor.project_id = None
    editor.video_id = None
    editor.editor_tabs.setCurrentIndex(0)
    editor.zoom_combo.setCurrentIndex(0)
    editor.open_existing(first_id)
    wait(lambda: not editor.is_busy())
    assert editor.editor_tabs.currentIndex() == 3 and editor.zoom_combo.currentData() == 2
    assert all(abs(a-b) <= 3 for a,b in zip(saved_sizes, editor.workspace_splitter.sizes()))
    apply_theme(window, True)
    window.grab().save(str(run / "light.png"))
    editor.shutdown_preview()
    wait(lambda: not editor.is_busy())
    assert window.close()
    report = {"status": "passed", "scale": os.environ.get("QT_SCALE_FACTOR", "native"),
              "device_pixel_ratio": window.devicePixelRatioF(), "geometry": geometry, "artifacts": str(run)}
    (CHECK / f"scale-{report['scale']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    matrix() if "--matrix" in sys.argv else main()
