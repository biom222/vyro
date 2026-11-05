from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import faulthandler
import sys
import traceback

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models import init_db
from app.services.scheduler_runner import LocalScheduler
from app.tasks import run_scheduled_publications
from gui.main_window import MainWindow


def initialize_database_with_recovery() -> bool:
    from app.database import DatabaseSafetyError, restore_database
    while True:
        try:
            init_db()
            return True
        except (DatabaseSafetyError, SQLAlchemyError, OSError):
            logging.getLogger(__name__).exception("Database startup failed")
            answer = QMessageBox.question(None, "База данных недоступна",
                "Не удалось безопасно открыть или обновить базу данных. Исходный файл и резервные копии сохранены. "
                "Восстановить базу из проверенной резервной копии?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
            filename, _filter = QFileDialog.getOpenFileName(None, "Выберите резервную копию базы",
                str(settings.data_folder / "backups"), "SQLite backup (*.bak *.sqlite3);;All files (*)")
            if not filename:
                return False
            try:
                from pathlib import Path
                restore_database(Path(filename))
            except (DatabaseSafetyError, OSError):
                logging.getLogger(__name__).exception("Database restore failed")
                QMessageBox.warning(None, "Восстановление не выполнено",
                    "Выбранная копия не прошла проверку или недоступна. Текущий файл сохранён.")


def run() -> int:
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setApplicationName(settings.app_name)
    qt_app.setOrganizationName("vyro")
    try:
        settings.ensure_directories()
    except OSError:
        QMessageBox.critical(None, "Папка данных недоступна",
            "Не удалось открыть папку проектов. Проверьте доступ и свободное место. Существующие данные не удалены.")
        return 1
    instance_lock = QLockFile(str(settings.data_folder / "vyro.lock"))
    if not instance_lock.tryLock(0):
        QMessageBox.information(None, "vyro уже запущен", "Откройте существующее окно vyro. Повторный запуск не изменяет проекты.")
        return 1
    log_path = settings.data_folder / "vyro.log"
    log_format = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # HTTP client request logs can contain resumable-session URLs and OAuth queries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
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
    if not initialize_database_with_recovery():
        faulthandler.disable()
        crash_log.close()
        instance_lock.unlock()
        return 1
    from app.services.storage import cleanup_stale_artifacts
    removed = cleanup_stale_artifacts()
    if removed:
        logging.getLogger(__name__).info("Removed %s stale disposable artifacts; media files retained", len(removed))

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
        instance_lock.unlock()


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
