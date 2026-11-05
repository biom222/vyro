"""Real-media multi-project lifecycle and GUI confirmation checks on an isolated DB."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECK = ROOT / "work" / "library-check"
CHECK.mkdir(parents=True, exist_ok=True)
RUN = Path(tempfile.mkdtemp(prefix="run-", dir=CHECK))
for key, value in {"DATABASE_URL": f"sqlite:///{(RUN / 'test.sqlite3').as_posix()}",
    "UPLOAD_FOLDER": str(RUN / "uploads"), "OUTPUT_FOLDER": str(RUN / "outputs"),
    "DATA_FOLDER": str(RUN / "data"), "CACHE_FOLDER": str(RUN / "cache"),
    "AI_PROVIDER": "mock", "TRANSCRIPTION_PROVIDER": "mock", "TRENDS_MOCK_MODE": "true",
    "SCHEDULER_ENABLED": "false", "QT_QPA_PLATFORM": "offscreen"}.items():
    os.environ[key] = value

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
from app.config import settings
from app.models import Project, SessionLocal, Video, init_db
from app.services.library import library_inventory, preference, recent_projects
from app.services.media_library import inspect_media
from app.services.project_state import load_project_state
from gui.main_window import MainWindow


def wait(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Library check timed out"
        QTest.qWait(20)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    init_db()
    app = QApplication([])
    if sys.platform == "win32":
        for name in ("segoeui.ttf", "segoeuib.ttf", "arial.ttf", "arialbd.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"], "Fonts", name)))
    source = RUN / "Русский исходник.mp4"
    subprocess.run([settings.ffmpeg_binary, "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=s=320x180:r=25:d=3", "-c:v", "libx264", str(source)], check=True, timeout=30)
    original_hash = digest(source)
    window = MainWindow()
    window.show()
    editor, history = window.editor_workspace, window.history_widget
    editor.upload_widget.load_video(str(source))
    wait(lambda: editor.video_id is not None and not editor.is_busy() and not history.is_busy())
    assert editor.save_project()
    original_project, original_video = editor.project_id, editor.video_id
    editor.edit_widget.start_render()
    wait(lambda: not editor.edit_widget.is_busy(), 90)
    wait(lambda: not history.is_busy())
    output = editor.edit_widget.output_path
    assert output
    output_hash = digest(output)
    window.navigate("history")
    wait(lambda: not history.is_busy())

    def select_project(project_id):
        history.search.clear()
        history.tabs.setCurrentIndex(0)
        for row in range(history.projects_proxy.rowCount()):
            if history.projects_proxy.index(row, 0).data() == str(project_id):
                history.projects_table.selectRow(row)
                wait(lambda: not history.is_busy())
                return
        raise AssertionError(f"Project missing from table: {project_id}")

    select_project(original_project)
    assert not history.thumbnail.pixmap().isNull()
    assert "h264" in history.media_label.text()
    cached = inspect_media(original_video)
    stamp = Path(cached["thumbnail"]).stat().st_mtime_ns
    assert inspect_media(original_video) == cached
    assert Path(cached["thumbnail"]).stat().st_mtime_ns == stamp
    with patch("gui.history_widget.QInputDialog.getText", return_value=("Русский проект", True)):
        history.rename_selected_project()
    wait(lambda: not history.is_busy())
    history.search.setText("РУССКИЙ ПРОЕКТ")
    assert history.projects_proxy.rowCount() == 1
    history.search.clear()
    select_project(original_project)
    with patch("gui.history_widget.QInputDialog.getText", return_value=("Independent copy", True)):
        history.duplicate_selected_project()
    wait(lambda: not editor.is_busy() and not history.is_busy())
    copied_project, copied_video = editor.project_id, editor.video_id
    assert copied_project != original_project
    assert editor.edit_widget.output_path is None
    assert not editor.edit_widget.reveal_button.isVisible()
    window._refresh_recent_menu()
    assert len(window.recent_menu.actions()) >= 2
    assert recent_projects()[0]["id"] == copied_project
    window.navigate("history")
    wait(lambda: not history.is_busy())
    select_project(copied_project)
    with patch("gui.history_widget.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
        history.delete_selected_project()
    with SessionLocal() as session:
        assert session.get(Project, copied_project) is not None
    with patch("gui.history_widget.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        history.delete_selected_project()
    wait(lambda: not history.is_busy())
    assert editor.project_id is None and window.publish_widget.video_id is None
    assert window.ai_widget.project_id is None
    assert "Проект удалён" in window.statusBar().currentMessage()
    with SessionLocal() as session:
        assert session.get(Project, copied_project) is None
        assert session.get(Video, copied_video).project_id is None
        managed_source = Path(session.get(Video, original_video).original_path)
    assert digest(output) == output_hash and digest(source) == original_hash
    assert managed_source.is_file()

    # Losing a managed source marks its project, without destroying another export.
    moved = RUN / "relocated.mp4"
    managed_source.rename(moved)
    history.refresh()
    wait(lambda: not history.is_busy())
    select_project(original_project)
    assert history.selected_project()["status"] == "Нет исходников"
    window.resize(1040, 700)
    QTest.qWait(80)
    window.grab().save(str(RUN / "missing-small.png"))
    revision = load_project_state(original_project).revision
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    with patch("gui.history_widget.QFileDialog.getOpenFileName", return_value=(str(moved), "")), \
         patch("gui.history_widget.QMessageBox.information"):
        history.choose_replacement(original_video)
        wait(lambda: not history.is_busy())
    timer.stop()
    assert len(ticks) > 3
    assert load_project_state(original_project).revision == revision + 1
    assert load_project_state(original_project).state["dirty"]
    with SessionLocal() as session:
        new_path = Path(session.get(Video, original_video).original_path)
        assert session.get(Video, original_video).output_path is None
    assert new_path.is_file() and new_path != moved
    assert digest(moved) == original_hash == digest(new_path)
    assert digest(output) == output_hash
    window._open_last_project()
    wait(lambda: not editor.is_busy() and not history.is_busy())
    assert editor.project_id == original_project
    editor.edit_widget.start_render()
    wait(lambda: not editor.edit_widget.is_busy(), 90)
    wait(lambda: not history.is_busy())
    export_directory = RUN / "saved copies"
    export_directory.mkdir()
    target = export_directory / "result.mp4"
    with patch("gui.edit_widget.QFileDialog.getSaveFileName", return_value=(str(target), "")), \
         patch("gui.edit_widget.QMessageBox.information"):
        editor.edit_widget.save_as()
        wait(lambda: not editor.edit_widget.is_busy())
    assert target.is_file() and digest(target) == digest(editor.edit_widget.output_path)
    assert preference("export.directory") == str(export_directory)
    with patch("gui.local_files.subprocess.Popen") as opener:
        editor.edit_widget.reveal_output()
        if sys.platform == "win32":
            assert opener.called and opener.call_args.args[0][0] == "explorer.exe"
    window.navigate("history")
    wait(lambda: not history.is_busy())
    select_project(original_project)
    window.resize(1380, 860)
    QTest.qWait(80)
    window.grab().save(str(RUN / "library.png"))
    history.show_project_files()
    assert history.videos_proxy.rowCount() == 1
    history.show_all_videos()
    assert history.videos_proxy.rowCount() == 2
    for row in range(history.videos_proxy.rowCount()):
        if history.videos_proxy.index(row, 0).data() == str(original_video):
            history.table.selectRow(row)
    wait(lambda: not history.is_busy())
    window.grab().save(str(RUN / "metadata.png"))
    editor.shutdown_preview()
    wait(lambda: not editor.is_busy() and not history.is_busy())
    assert window.close()
    # A new process reads retained recency/export preferences and the original project.
    script = "import json; from app.services.library import recent_projects,preference; print(json.dumps([recent_projects()[0]['id'],preference('export.directory')]))"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True, timeout=20)
    assert json.loads(result.stdout) == [original_project, str(export_directory)]
    report = {"status": "passed", "artifacts": str(RUN), "projects": len(library_inventory()["projects"]),
              "relink_event_loop_ticks": len(ticks), "checks": ["real export", "thumbnail cache", "Unicode search", "rename",
              "independent duplicate", "cancelled and confirmed deletion", "shared file retention", "missing source",
              "atomic relink", "last project", "background export copy", "remembered destination", "reveal contract", "new-process preferences"]}
    (CHECK / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    def unexpected_dialog(*args, **kwargs):
        raise AssertionError("Unexpected GUI warning: " + " | ".join(str(v) for v in args[1:3]))
    with patch.object(QMessageBox, "warning", side_effect=unexpected_dialog), \
         patch.object(QMessageBox, "critical", side_effect=unexpected_dialog), \
         patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
        main()
