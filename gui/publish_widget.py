from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QDateTime, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)

from app.config import settings
from sqlalchemy import select
from app.models import ConnectedAccount, Post, SessionLocal, Video
from app.services.accounts import SUPPORTED_PROVIDERS, get_active_account_id, set_active_account
from app.services.scheduler import schedule_post
from gui.worker import PublicationStatusWorker, PublishWorker, TikTokCreatorInfoWorker


class PublishWidget(QWidget):
    publication_completed = pyqtSignal()
    log_message = pyqtSignal(str)
    draft_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_id: int | None = None
        self.output_path: str | None = None
        self.output_duration: float | None = None
        self.publish_worker: PublishWorker | None = None
        self.creator_worker: TikTokCreatorInfoWorker | None = None
        self.status_worker: PublicationStatusWorker | None = None
        self.pending_post_id: int | None = None
        self.creator_account_id: int | None = None
        self.creator_info: dict = {}
        self.creator_error = False
        self._restoring_draft = False
        self._refreshing_account = False
        self._saved_options: dict = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        heading = QLabel("Публикация")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        hint = QLabel("Адресат определяется галочкой в верхнем меню «Аккаунты».")
        hint.setObjectName("pageSubtitle")
        layout.addWidget(hint)
        group = QGroupBox("Готовое видео")
        group_layout = QVBoxLayout(group)
        self.video_label = QLabel("Обработанное видео ещё не выбрано.")
        self.video_label.setWordWrap(True)
        group_layout.addWidget(self.video_label)
        layout.addWidget(group)
        form_group = QGroupBox("Параметры публикации")
        form = QFormLayout(form_group)
        self.form_layout = form
        self.account_label = QLabel("Аккаунт не выбран")
        form.addRow("Адресат:", self.account_label)
        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(255)
        self.title_edit.setPlaceholderText("Заголовок ролика")
        form.addRow("Заголовок:", self.title_edit)
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(100)
        self.description_edit.setPlaceholderText("Описание и хэштеги")
        form.addRow("Описание:", self.description_edit)
        self.privacy_combo = QComboBox()
        self.privacy_combo.setEnabled(False)
        form.addRow("Видимость:", self.privacy_combo)
        self.tiktok_options = QWidget()
        tiktok_layout = QHBoxLayout(self.tiktok_options)
        tiktok_layout.setContentsMargins(0, 0, 0, 0)
        self.disable_comment = QCheckBox("Отключить комментарии")
        self.disable_duet = QCheckBox("Отключить дуэты")
        self.disable_stitch = QCheckBox("Отключить Stitch")
        for checkbox in (self.disable_comment, self.disable_duet, self.disable_stitch):
            tiktok_layout.addWidget(checkbox)
        form.addRow("TikTok:", self.tiktok_options)
        self.commercial_options = QWidget()
        commercial_layout = QHBoxLayout(self.commercial_options)
        commercial_layout.setContentsMargins(0, 0, 0, 0)
        self.brand_content = QCheckBox("Платное партнёрство")
        self.brand_organic = QCheckBox("Продвижение своего бизнеса")
        self.ai_generated = QCheckBox("Создано ИИ")
        for checkbox in (self.brand_content, self.brand_organic, self.ai_generated):
            commercial_layout.addWidget(checkbox)
        form.addRow("Метки:", self.commercial_options)
        layout.addWidget(form_group)
        self.publish_button = QPushButton("Опубликовать")
        self.publish_button.clicked.connect(self.start_publish)
        self.schedule_time = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.schedule_time.setCalendarPopup(True)
        self.schedule_time.setDisplayFormat("dd.MM.yyyy HH:mm")
        self.schedule_button = QPushButton("Запланировать")
        self.schedule_button.setObjectName("secondaryButton")
        self.schedule_button.clicked.connect(self.schedule_publish)
        row = QHBoxLayout()
        row.addWidget(self.publish_button)
        row.addWidget(self.schedule_time)
        row.addWidget(self.schedule_button)
        layout.addLayout(row)
        self.status_label = QLabel("Подключите аккаунт через меню «Аккаунты».")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.upload_progress = QProgressBar()
        self.upload_progress.setRange(0, 100)
        self.upload_progress.setFormat("Загрузка не запущена")
        layout.addWidget(self.upload_progress)
        self.pending_combo = QComboBox()
        self.check_status_button = QPushButton("Проверить статус YouTube")
        self.check_status_button.clicked.connect(self.check_selected_status)
        layout.addWidget(self.pending_combo)
        layout.addWidget(self.check_status_button)
        self.remote_label = QLabel()
        self.remote_label.setOpenExternalLinks(True)
        layout.addWidget(self.remote_label)
        layout.addStretch()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(10000)
        self.status_timer.timeout.connect(self._poll_status)
        self.refresh_account()
        self.refresh_pending_posts()
        self.title_edit.textChanged.connect(self._emit_draft)
        self.description_edit.textChanged.connect(self._emit_draft)
        self.privacy_combo.currentIndexChanged.connect(self._emit_draft)
        for checkbox in (self.disable_comment, self.disable_duet, self.disable_stitch,
                         self.brand_content, self.brand_organic, self.ai_generated):
            checkbox.toggled.connect(self._emit_draft)

    def publication_draft(self) -> dict:
        options = dict(self._saved_options)
        privacy = self.privacy_combo.currentData()
        if privacy in {"private", "unlisted", "public"}:
            options["youtube_privacy"] = privacy
        elif privacy:
            options["privacy_level"] = privacy
        for checkbox, key in ((self.disable_comment, "disable_comment"), (self.disable_duet, "disable_duet"),
                              (self.disable_stitch, "disable_stitch"), (self.brand_content, "brand_content_toggle"),
                              (self.brand_organic, "brand_organic_toggle"), (self.ai_generated, "is_aigc")):
            options[key] = checkbox.isChecked()
        return {"account_id": get_active_account_id(), "title": self.title_edit.text(),
                "description": self.description_edit.toPlainText(), "options": options}

    def _emit_draft(self, *args) -> None:
        if not self._restoring_draft and not self._refreshing_account:
            state = self.publication_draft()
            self._saved_options = state["options"]
            self.draft_changed.emit(state)

    def restore_draft(self, state: dict) -> None:
        self._restoring_draft = True
        try:
            if "account_id" in state:
                with SessionLocal() as session:
                    selected = state["account_id"]
                    available = session.get(ConnectedAccount, selected) if selected else None
                set_active_account(selected if available and available.provider in SUPPORTED_PROVIDERS else None)
            self.title_edit.setText(str(state.get("title") or ""))
            self.description_edit.setPlainText(str(state.get("description") or ""))
            self._saved_options = dict(state.get("options") or {})
            for checkbox, key in ((self.disable_comment, "disable_comment"), (self.disable_duet, "disable_duet"),
                                  (self.disable_stitch, "disable_stitch"), (self.brand_content, "brand_content_toggle"),
                                  (self.brand_organic, "brand_organic_toggle"), (self.ai_generated, "is_aigc")):
                checkbox.setChecked(bool(self._saved_options.get(key)))
            self.refresh_account()
        finally:
            self._restoring_draft = False

    def set_video(self, video_id: int, output_path: str, duration: float) -> None:
        self.video_id, self.output_path, self.output_duration = video_id, output_path, duration
        self.video_label.setText(f"{Path(output_path).name} · {duration:.1f} сек.\n{output_path}")
        self.refresh_account()

    def clear_video(self) -> None:
        self.video_id = None
        self.output_path = None
        self.output_duration = None
        self.video_label.setText("Обработанное видео ещё не выбрано.")
        self.refresh_account()

    def refresh_account(self) -> None:
        self._refreshing_account = True
        account_id = get_active_account_id()
        with SessionLocal() as session:
            account = session.get(ConnectedAccount, account_id) if account_id else None
            provider = account.provider if account else None
            ready = bool(account and account.status == "connected" and account.credential_ref)
            label = (f"{provider.title()} · {account.display_name or account.username}"
                     if account else "Аккаунт не выбран")
        self.account_label.setText(label)
        self.form_layout.setRowVisible(self.tiktok_options, provider == "tiktok")
        self.form_layout.setRowVisible(self.commercial_options, provider == "tiktok")
        self.privacy_combo.clear()
        if provider == "youtube":
            for text, value in (("Приватное", "private"), ("По ссылке", "unlisted"), ("Публичное", "public")):
                self.privacy_combo.addItem(text, value)
            self.privacy_combo.setEnabled(ready)
        elif provider == "tiktok" and ready:
            if self.creator_account_id == account_id and self.creator_info:
                for value in self.creator_info.get("privacy_level_options") or []:
                    self.privacy_combo.addItem(value, value)
                self.privacy_combo.setEnabled(self.privacy_combo.count() > 0)
                for checkbox, key in ((self.disable_comment, "comment_disabled"),
                                      (self.disable_duet, "duet_disabled"),
                                      (self.disable_stitch, "stitch_disabled")):
                    disabled = bool(self.creator_info.get(key))
                    if disabled:
                        checkbox.setChecked(True)
                    checkbox.setEnabled(not disabled)
            elif self.creator_worker is None and not self.creator_error:
                self.privacy_combo.addItem("Получение настроек TikTok…")
                self.creator_worker = TikTokCreatorInfoWorker(account_id, self)
                self.creator_worker.succeeded.connect(lambda info, aid=account_id: self._creator_loaded(aid, info))
                self.creator_worker.error.connect(self._creator_failed)
                self.creator_worker.finished.connect(self._creator_finished)
                self.creator_worker.start()
        selected_privacy = self._saved_options.get("youtube_privacy" if provider == "youtube" else "privacy_level")
        if selected_privacy:
            index = self.privacy_combo.findData(selected_privacy)
            if index >= 0:
                self.privacy_combo.setCurrentIndex(index)
        valid = bool(self.video_id and self.output_duration is not None
                     and 3 <= self.output_duration <= settings.max_video_duration
                     and self.output_path and Path(self.output_path).is_file())
        enabled = valid and ready and not self.is_busy() and (provider != "tiktok" or self.privacy_combo.isEnabled())
        self.publish_button.setEnabled(enabled)
        self.schedule_button.setEnabled(enabled)
        if not ready:
            self.status_label.setText("Подключите и выберите аккаунт в верхнем меню «Аккаунты».")
        elif self.output_duration is not None and not valid:
            self.status_label.setText(f"Для публикации нужно готовое MP4 длительностью от 3 до {settings.max_video_duration:.0f} сек.")
        self._refreshing_account = False

    def _creator_loaded(self, account_id: int, info: dict) -> None:
        self.creator_account_id, self.creator_info = account_id, info
        self.creator_error = False
        self.refresh_account()

    def _creator_failed(self, message: str) -> None:
        self.creator_error = True
        self.status_label.setText(f"Не удалось получить настройки TikTok: {message}")
        self.log_message.emit(self.status_label.text())

    def _creator_finished(self) -> None:
        worker, self.creator_worker = self.creator_worker, None
        if worker:
            worker.deleteLater()
        self.refresh_account()

    def _new_post(self) -> int | None:
        account_id = get_active_account_id()
        with SessionLocal() as session:
            account = session.get(ConnectedAccount, account_id) if account_id else None
            video = session.get(Video, self.video_id) if self.video_id else None
            if not account or account.status != "connected" or not account.credential_ref:
                QMessageBox.warning(self, "Аккаунт", "Выберите подключённый аккаунт в меню «Аккаунты».")
                return None
            if not video or video.status != "ready" or not video.output_path or not Path(video.output_path).is_file():
                QMessageBox.warning(self, "Видео", "Сначала завершите обработку MP4.")
                return None
            duration = video.output_duration or self.output_duration or 0
            if not 3 <= duration <= settings.max_video_duration:
                QMessageBox.warning(self, "Длительность", "Длительность видео вне поддерживаемого диапазона.")
                return None
            options = {}
            if account.provider == "tiktok":
                privacy = self.privacy_combo.currentData()
                if not privacy or self.creator_account_id != account.id:
                    QMessageBox.warning(self, "TikTok", "Дождитесь настроек видимости аккаунта.")
                    return None
                maximum = self.creator_info.get("max_video_post_duration_sec")
                if maximum and duration > float(maximum):
                    QMessageBox.warning(self, "TikTok", f"Лимит этого аккаунта: {maximum} сек.")
                    return None
                options["privacy_level"] = privacy
                options.update({
                    "disable_comment": self.disable_comment.isChecked(),
                    "disable_duet": self.disable_duet.isChecked(),
                    "disable_stitch": self.disable_stitch.isChecked(),
                    "brand_content_toggle": self.brand_content.isChecked(),
                    "brand_organic_toggle": self.brand_organic.isChecked(),
                    "is_aigc": self.ai_generated.isChecked(),
                })
            elif account.provider == "youtube":
                options["youtube_privacy"] = self.privacy_combo.currentData() or "private"
                for previous in session.scalars(select(Post).where(Post.account_id == account.id, Post.video_id == video.id)):
                    old = previous.payload_json or {}
                    if old.get("media_path") == str(Path(video.output_path).resolve()) and (
                            previous.status in {"queued", "scheduled", "dispatching", "publishing", "pending", "published", "unknown"}
                            or old.get("youtube_upload_attempted")):
                        QMessageBox.warning(self, "Повторная отправка", f"Для этого экспорта уже есть отправка #{previous.id}. Проверьте её статус.")
                        return None
            options.update({"media_path": str(Path(video.output_path).resolve()), "media_duration": duration})
            post = Post(video_id=video.id, account_id=account.id, platform=account.provider,
                        title=self.title_edit.text().strip(),
                        description=self.description_edit.toPlainText().strip(),
                        status="queued", payload_json=options)
            session.add(post)
            session.commit()
            return post.id

    def start_publish(self) -> None:
        if self.is_busy():
            return
        if QMessageBox.question(self, "Подтвердить публикацию",
                                f"Отправить видео на {self.account_label.text()}?") != QMessageBox.StandardButton.Yes:
            return
        post_id = self._new_post()
        if post_id is None:
            return
        self.publish_button.setEnabled(False)
        self.schedule_button.setEnabled(False)
        self.status_label.setText("Видео отправляется в фоновом потоке…")
        self.upload_progress.setValue(0)
        self.upload_progress.setFormat("Отправка данных · %p%")
        self.publish_worker = PublishWorker(post_id, self)
        self.publish_worker.succeeded.connect(self._publish_succeeded)
        self.publish_worker.progress.connect(self.upload_progress.setValue)
        self.publish_worker.error.connect(self._publish_failed)
        self.publish_worker.finished.connect(self._publish_finished)
        self.publish_worker.start()

    def schedule_publish(self) -> None:
        if self.is_busy():
            return
        when = self.schedule_time.dateTime().toPyDateTime().astimezone()
        if when <= datetime.now().astimezone():
            QMessageBox.warning(self, "Время", "Выберите время в будущем.")
            return
        post_id = self._new_post()
        if post_id is None:
            return
        try:
            schedule_post(post_id, when)
        except Exception as exc:
            self.status_label.setText(f"Ошибка планирования: {exc}")
            return
        self.status_label.setText(f"Публикация запланирована на {when:%d.%m.%Y %H:%M}.")
        self.log_message.emit(f"Публикация #{post_id} запланирована.")
        self.publication_completed.emit()

    def _publish_succeeded(self, post_id: int) -> None:
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            status = post.status if post else "unknown"
        self.status_label.setText(f"Статус публикации: {status}")
        self.log_message.emit(f"Публикация #{post_id}: {status}.")
        self.publication_completed.emit()
        self.refresh_pending_posts()
        if status == "pending":
            self.upload_progress.setFormat("Данные приняты; сервер обрабатывает видео")
            self.pending_post_id = post_id
            self.status_timer.start()
        else:
            QMessageBox.information(self, "Публикация", f"Статус: {status}")

    def _publish_failed(self, message: str) -> None:
        self.refresh_pending_posts()
        self.status_label.setText(f"Ошибка публикации: {message}")
        self.log_message.emit(self.status_label.text())
        QMessageBox.critical(self, "Ошибка публикации", message)

    def _publish_finished(self) -> None:
        worker, self.publish_worker = self.publish_worker, None
        if worker:
            worker.deleteLater()
        self.refresh_account()

    def _poll_status(self) -> None:
        if self.pending_post_id is None or self.status_worker is not None:
            return
        self.status_worker = PublicationStatusWorker(self.pending_post_id, self)
        self.status_worker.succeeded.connect(self._status_loaded)
        self.status_worker.error.connect(self._status_failed)
        self.status_worker.finished.connect(self._status_finished)
        self.status_worker.start()

    def _status_loaded(self, post_id: int, status: str) -> None:
        self.status_label.setText(f"Публикация #{post_id}: {status}")
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            if post:
                import html
                details = post.payload_json or {}
                privacy = details.get("youtube_privacy_actual", "")
                self.remote_label.setText(f'<a href="{html.escape(post.external_url or "", quote=True)}">Открыть ролик</a> · {html.escape(privacy)}')
                if post.error_message:
                    self.status_label.setText(post.error_message)
                elif status == "published" and post.platform == "youtube":
                    self.status_label.setText(f"YouTube подтвердил обработку ролика #{post_id}. Видимость: {privacy}.")
        if status != "pending":
            self.pending_post_id = None
            self.status_timer.stop()
            self.publication_completed.emit()
            self.refresh_pending_posts()

    def refresh_pending_posts(self):
        self.pending_combo.clear()
        with SessionLocal() as session:
            rows = list(session.scalars(select(Post).where(Post.platform == "youtube",
                Post.status.in_(("pending", "unknown", "publishing", "published"))).order_by(Post.id.desc()).limit(100)))
        for row in rows:
            self.pending_combo.addItem(f"#{row.id} · {row.title or 'YouTube'} · {row.status}" + (" · нет ID, проверьте канал" if not row.external_id else ""), row.id)
        self.check_status_button.setEnabled(bool(rows))
        if not rows:
            self.pending_combo.addItem("Нет отправок YouTube")

    def check_selected_status(self):
        post_id = self.pending_combo.currentData()
        if post_id is None or self.status_worker:
            return
        self.pending_post_id = post_id
        self._poll_status()

    def _status_failed(self, message: str) -> None:
        self.status_timer.stop()
        self.status_label.setText(f"Проверка статуса: {message}")
        self.log_message.emit(self.status_label.text())

    def _status_finished(self) -> None:
        worker, self.status_worker = self.status_worker, None
        if worker:
            worker.deleteLater()

    def is_busy(self) -> bool:
        return any(worker is not None and worker.isRunning() for worker in (
            self.publish_worker, self.creator_worker, self.status_worker))
