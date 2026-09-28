from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import faulthandler
import sys
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox

from app.config import settings
from app.models import init_db
from app.services.scheduler_runner import LocalScheduler
from app.tasks import run_scheduled_publications
from gui.main_window import MainWindow


def run() -> int:
    settings.ensure_directories()
    log_path = settings.data_folder / "vyro.log"
    log_format = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)
    if not any(
        isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers
    ):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)

    crash_log = (settings.data_folder / "native-crash.log").open(
        "a", encoding="utf-8"
    )
    faulthandler.enable(file=crash_log, all_threads=True)
    init_db()

    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setApplicationName(settings.app_name)
    qt_app.setOrganizationName("vyro")

    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        logging.getLogger(__name__).critical(
            "Unhandled GUI exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        message = "".join(
            traceback.format_exception_only(exc_type, exc_value)
        ).strip()
        QMessageBox.critical(None, "Неожиданная ошибка", message)

    sys.excepthook = handle_exception
    window = MainWindow()
    window.show()
    scheduler = LocalScheduler(
        run_scheduled_publications,
        interval_seconds=settings.scheduler_poll_seconds,
    )
    if settings.scheduler_enabled:
        scheduler.start()
    try:
        return qt_app.exec()
    finally:
        scheduler.stop()
        faulthandler.disable()
        crash_log.close()


def self_test() -> int:
    """Check bundled imports, migrations, and the main window without user data."""
    def stage(name: str) -> None:
        (settings.data_folder / "self-test-stage.txt").write_text(name, encoding="utf-8")

    settings.ensure_directories()
    stage("directories")
    init_db()
    stage("database")
    qt_app = QApplication.instance() or QApplication([])
    qt_app.setStyle("Fusion")
    stage("qt")
    window = MainWindow()
    stage("window")
    window.close()
    stage("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else run())
