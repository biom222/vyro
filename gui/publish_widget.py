from __future__ import annotations

from pathlib import Path
from datetime import datetime

from PyQt6.QtCore import QDateTime, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import Post, SessionLocal, Video
from app.publisher import is_mock_mode
from app.services.scheduler import schedule_post
from gui.worker import PlatformWorker, PublishWorker


class PublishWidget(QWidget):
    publication_completed = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_id: int | None = None
        self.output_path: str | None = None
        self.output_duration: float | None = None
        self.platform_worker: PlatformWorker | None = None
        self.publish_worker: PublishWorker | None = None
        self.platforms_loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        heading = QLabel("Публикация")
        heading.setObjectName("pageTitle")
        subtitle = QLabel(
            "Выберите подключённый аккаунт Taisly и отправьте готовый ролик."
        )
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        video_group = QGroupBox("Готовое видео")
        video_layout = QVBoxLayout(video_group)
        self.video_label = QLabel("Обработанное видео ещё не выбрано.")
        self.video_label.setWordWrap(True)
        video_layout.addWidget(self.video_label)
        layout.addWidget(video_group)

        form_group = QGroupBox("Параметры публикации")
        form_layout = QFormLayout(form_group)
        platform_row = QHBoxLayout()
        self.platform_combo = QComboBox()
        self.platform_combo.setPlaceholderText("Загрузка платформ…")
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(lambda: self.load_platforms(force=True))
        platform_row.addWidget(self.platform_combo, 1)
        platform_row.addWidget(self.refresh_button)
        form_layout.addRow("Платформа:", platform_row)

        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(255)
        self.title_edit.setPlaceholderText("Заголовок ролика")
        form_layout.addRow("Заголовок:", self.title_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(120)
        self.description_edit.setPlaceholderText("Описание, хэштеги и дополнительный контекст")
        form_layout.addRow("Описание:", self.description_edit)
        layout.addWidget(form_group)

        self.publish_button = QPushButton("Опубликовать")
        self.publish_button.clicked.connect(self.start_publish)
        self.publish_button.setEnabled(False)
        self.schedule_time = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.schedule_time.setCalendarPopup(True)
        self.schedule_time.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.schedule_button = QPushButton("Запланировать")
        self.schedule_button.setObjectName("secondaryButton")
        self.schedule_button.clicked.connect(self.schedule_publish)
        self.schedule_button.setEnabled(False)
        action_row = QHBoxLayout()
        action_row.addWidget(self.publish_button)
        action_row.addWidget(self.schedule_time)
        action_row.addWidget(self.schedule_button)
        layout.addLayout(action_row)

        self.status_label = QLabel(
            "Mock-режим: внешняя публикация отключена."
            if is_mock_mode()
            else "Taisly API настроен."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)
        layout.addStretch()

    def set_video(self, video_id: int, output_path: str, duration: float) -> None:
        self.video_id = video_id
        self.output_path = output_path
        self.output_duration = duration
        self.video_label.setText(
            f"{Path(output_path).name}  •  {duration:.1f} сек.\n{output_path}"
        )
        self.publish_button.setEnabled(3 <= duration <= 90)
        self.schedule_button.setEnabled(3 <= duration <= 90)
        if not 3 <= duration <= 90:
            self.status_label.setText(
                "Taisly принимает ролики длительностью от 3 до 90 секунд."
            )
        self.load_platforms()

    def load_platforms(self, force: bool = False) -> None:
        if self.platforms_loaded and not force:
            return
        # Keep one worker object until its finished signal is handled. A mock worker can
        # finish between set_video() and page navigation; replacing that object here
        # would let the first worker's queued cleanup delete the second running thread.
        if self.platform_worker is not None:
            return
        self.platform_combo.clear()
        self.platform_combo.setPlaceholderText("Загрузка платформ…")
        self.refresh_button.setEnabled(False)
        self.platform_worker = PlatformWorker(self)
        self.platform_worker.succeeded.connect(self._platforms_succeeded)
        self.platform_worker.error.connect(self._platforms_failed)
        self.platform_worker.finished.connect(self._platforms_finished)
        self.platform_worker.start()

    def _platforms_succeeded(self, platforms: list[dict]) -> None:
        for platform in platforms:
            platform_id = str(platform.get("id") or platform.get("_id") or "")
            if not platform_id:
                continue
            network = str(platform.get("platform") or "Platform")
            account = str(
                platform.get("displayName") or platform.get("username") or "account"
            )
            self.platform_combo.addItem(f"{network} — {account}", platform_id)
        self.platforms_loaded = self.platform_combo.count() > 0
        if self.platforms_loaded:
            self.log_message.emit(
                f"Получено платформ: {self.platform_combo.count()}."
            )
        else:
            self.status_label.setText("Подключённые платформы не найдены.")

    def _platforms_failed(self, message: str) -> None:
        self.platforms_loaded = False
        self.status_label.setText(f"Не удалось получить платформы: {message}")
        self.log_message.emit(f"Ошибка Taisly: {message}")

    def _platforms_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is self.platform_worker:
            self.platform_worker = None

    def start_publish(self) -> None:
        if self.video_id is None or self.is_busy():
            return
        platform_id = self.platform_combo.currentData()
        if not platform_id:
            QMessageBox.warning(self, "Платформа не выбрана", "Выберите аккаунт Taisly.")
            return
        if self.output_duration is None or not 3 <= self.output_duration <= 90:
            QMessageBox.warning(
                self,
                "Неверная длительность",
                "Taisly принимает видео длительностью от 3 до 90 секунд.",
            )
            return

        with SessionLocal() as session:
            video = session.get(Video, self.video_id)
            if video is None or video.status != "ready":
                QMessageBox.warning(self, "Видео не готово", "Сначала завершите обработку.")
                return
            post = Post(
                video_id=video.id,
                platform=str(platform_id),
                title=self.title_edit.text().strip(),
                description=self.description_edit.toPlainText().strip(),
                status="queued",
            )
            session.add(post)
            session.commit()
            session.refresh(post)
            post_id = post.id

        self.publish_button.setEnabled(False)
        self.status_label.setText("Публикация выполняется в фоновом потоке…")
        self.log_message.emit(f"Публикация #{post_id} запущена.")
        self.publish_worker = PublishWorker(post_id, self)
        self.publish_worker.succeeded.connect(self._publish_succeeded)
        self.publish_worker.error.connect(self._publish_failed)
        self.publish_worker.finished.connect(self._publish_finished)
        self.publish_worker.start()

    def schedule_publish(self) -> None:
        if self.video_id is None or self.is_busy():
            return
        platform_id = self.platform_combo.currentData()
        if not platform_id:
            QMessageBox.warning(self, "Платформа не выбрана", "Выберите аккаунт Taisly.")
            return
        if self.output_duration is None or not 3 <= self.output_duration <= 90:
            QMessageBox.warning(
                self,
                "Неверная длительность",
                "Taisly принимает видео длительностью от 3 до 90 секунд.",
            )
            return
        when = self.schedule_time.dateTime().toPyDateTime().astimezone()
        if when <= datetime.now().astimezone():
            QMessageBox.warning(self, "Неверное время", "Выберите время в будущем.")
            return
        with SessionLocal() as session:
            video = session.get(Video, self.video_id)
            if video is None or video.status != "ready":
                QMessageBox.warning(self, "Видео не готово", "Сначала завершите обработку.")
                return
            post = Post(
                video_id=video.id,
                platform=str(platform_id),
                title=self.title_edit.text().strip(),
                description=self.description_edit.toPlainText().strip(),
                status="queued",
            )
            session.add(post)
            session.commit()
            session.refresh(post)
            post_id = post.id
        try:
            schedule_post(post_id, when)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка планирования", str(exc))
            return
        self.status_label.setText(f"Публикация запланирована на {when:%d.%m.%Y %H:%M}.")
        self.log_message.emit(
            f"Публикация #{post_id} запланирована на {when:%d.%m.%Y %H:%M}."
        )
        self.publication_completed.emit()
        QMessageBox.information(
            self,
            "Публикация запланирована",
            f"Локальный планировщик отправит ролик {when:%d.%m.%Y в %H:%M}.",
        )

    def _publish_succeeded(self, post_id: int) -> None:
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            status = post.status if post else "unknown"
        self.status_label.setText(f"Статус публикации: {status}")
        self.log_message.emit(f"Публикация #{post_id}: {status}.")
        self.publication_completed.emit()
        QMessageBox.information(
            self,
            "Публикация отправлена",
            f"Текущий статус: {status}",
        )

    def _publish_failed(self, message: str) -> None:
        self.status_label.setText(f"Ошибка публикации: {message}")
        self.log_message.emit(f"Ошибка публикации: {message}")
        QMessageBox.critical(self, "Ошибка публикации", message)

    def _publish_finished(self) -> None:
        valid_duration = self.output_duration is not None and 3 <= self.output_duration <= 90
        self.publish_button.setEnabled(bool(self.video_id and valid_duration))
        self.schedule_button.setEnabled(bool(self.video_id and valid_duration))
        if self.publish_worker:
            self.publish_worker.deleteLater()
        self.publish_worker = None

    def is_busy(self) -> bool:
        workers = (self.platform_worker, self.publish_worker)
        return any(worker is not None and worker.isRunning() for worker in workers)
