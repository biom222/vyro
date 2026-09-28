from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.config import settings
from app.models import SessionLocal, Video
from sqlalchemy import select
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from gui.worker import ProbeWorker


class UploadWidget(QFrame):
    video_ready = pyqtSignal(int, float, int, int, str)
    log_message = pyqtSignal(str)
    existing_selected = pyqtSignal(int)
    probe_failed = pyqtSignal(str)

    ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaBin")
        self.video_id: int | None = None
        self.worker: ProbeWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        heading = QLabel("Медиатека")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Видео ещё не выбрано")
        self.choose_button = QPushButton("+ Добавить видео")
        self.choose_button.clicked.connect(self.choose_video)

        self.metadata_label = QLabel("Поддерживаются MP4, MOV, M4V, WEBM и MKV до 500 МБ.")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setMinimumHeight(64)
        self.metadata_label.setObjectName("muted")

        layout.addWidget(self.choose_button)
        layout.addWidget(self.path_edit)
        layout.addWidget(self.metadata_label)
        recent_label = QLabel("Недавние видео\nДвойной клик — открыть")
        recent_label.setObjectName("muted")
        layout.addWidget(recent_label)
        self.library = QListView()
        self.library_model = QStandardItemModel(self)
        self.library.setModel(self.library_model)
        self.library.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.library.setMinimumWidth(0)
        self.library.setMinimumHeight(90)
        self.library.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library.doubleClicked.connect(
            lambda item: self.existing_selected.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.library, 1)
        self.refresh_library()

    def refresh_library(self) -> None:
        self.library_model.clear()
        with SessionLocal() as session:
            videos = session.scalars(select(Video).where(Video.duration > 0).order_by(Video.id.desc()).limit(30))
            for video in videos:
                item = QStandardItem(f"{video.filename}\n{video.duration:.1f} сек. · #{video.id}")
                item.setData(video.id, Qt.ItemDataRole.UserRole)
                item.setToolTip(video.original_path)
                self.library_model.appendRow(item)

    def choose_video(self) -> bool:
        if self.is_busy():
            return False
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите видео",
            "",
            "Video files (*.mp4 *.mov *.m4v *.webm *.mkv);;All files (*)",
        )
        if not filename:
            return False
        self.load_video(filename)
        return True

    def load_video(self, filename: str) -> None:
        if self.is_busy() or not self.isEnabled():
            return
        path = Path(filename).resolve()
        if not path.is_file():
            QMessageBox.warning(self, "Файл не найден", "Выбранный файл недоступен.")
            return
        if path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            QMessageBox.warning(self, "Неверный формат", "Выберите поддерживаемый видеофайл.")
            return
        if path.stat().st_size > settings.max_file_size:
            QMessageBox.warning(
                self,
                "Файл слишком большой",
                f"Максимальный размер — {settings.max_file_size // 1024 // 1024} МБ.",
            )
            return

        with SessionLocal() as session:
            video = Video(
                filename=path.name[:255],
                original_path=str(path),
                status="queued",
            )
            session.add(video)
            session.commit()
            session.refresh(video)
            self.video_id = video.id

        self.path_edit.setText(path.name)
        self.path_edit.setToolTip(str(path))
        self.metadata_label.setText("Анализ видео через FFprobe…")
        self.choose_button.setEnabled(False)
        self.log_message.emit(f"Анализ файла «{path.name}» запущен.")

        self.worker = ProbeWorker(self.video_id, self)
        self.worker.copy_progress.connect(
            lambda percent: self.metadata_label.setText(f"Копирование в проект… {percent}%")
        )
        self.worker.succeeded.connect(
            lambda duration, width, height: self._probe_succeeded(
                path, duration, width, height
            )
        )
        self.worker.error.connect(self._probe_failed)
        self.worker.finished.connect(self._probe_finished)
        self.worker.start()

    def _probe_succeeded(
        self,
        path: Path,
        duration: float,
        width: int,
        height: int,
    ) -> None:
        with SessionLocal() as session:
            video = session.get(Video, self.video_id)
            if video is None:
                raise RuntimeError("Imported video was not saved")
            path = Path(video.original_path)
            display_name = video.filename
        size_mb = path.stat().st_size / 1024 / 1024
        self.metadata_label.setText(
            f"Длительность: {duration:.1f} сек.  •  Разрешение: {width}×{height}  •  "
            f"Размер: {size_mb:.1f} МБ"
        )
        self.log_message.emit(
            f"Видео #{self.video_id} ({display_name}) готово: {duration:.1f} сек., {width}×{height}."
        )
        self.video_ready.emit(
            self.video_id or 0,
            duration,
            width,
            height,
            str(path),
        )

    def _probe_failed(self, message: str) -> None:
        self.probe_failed.emit(message)
        self.metadata_label.setText(f"Ошибка анализа: {message}")
        self.log_message.emit(f"Ошибка FFprobe: {message}")
        QMessageBox.critical(self, "Не удалось прочитать видео", message)

    def _probe_finished(self) -> None:
        self.choose_button.setEnabled(True)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None
        self.refresh_library()

    def is_busy(self) -> bool:
        return self.worker is not None
