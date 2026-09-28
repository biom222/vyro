from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from app.models import AppPreference, Post, Project, SessionLocal, Video
from gui.worker import PublishWorker, RelinkWorker


class HistoryWidget(QWidget):
    log_message = pyqtSignal(str)
    open_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.workers: dict[int, PublishWorker] = {}
        self.relink_workers: dict[int, RelinkWorker] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        heading = QLabel("История проектов")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("Локальные записи SQLite и результаты обработки.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(heading)
        title_box.addWidget(subtitle)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        header.addLayout(title_box, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.projects_table = QTableWidget(0, 5)
        self.projects_table.setHorizontalHeaderLabels(["ID", "Проект", "Изменён", "Состояние", "Действие"])
        self.projects_table.setAlternatingRowColors(True)
        self.projects_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.projects_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.projects_table.verticalHeader().hide()
        project_header = self.projects_table.horizontalHeader()
        project_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        project_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            project_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.projects_table.cellDoubleClicked.connect(lambda row, _column: self.open_project_for_row(row))
        self.tabs.addTab(self.projects_table, "Проекты")

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Имя файла", "Дата", "Статус", "Действия"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda row, _: self.open_details_for_row(row))
        self.tabs.addTab(self.table, "Видео и публикации")
        layout.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        with SessionLocal() as session:
            projects = list(session.scalars(select(Project).order_by(Project.updated_at.desc())))
            project_rows = []
            for project in projects:
                preference = session.get(AppPreference, f"editor.project.{project.id}.sequence")
                state = preference.value_json if preference and isinstance(preference.value_json, dict) else {}
                members = list(session.scalars(select(Video).where(Video.project_id == project.id).order_by(Video.id)))
                primary_id = state.get("primary_id") or (members[0].id if members else None)
                project_rows.append((project, primary_id, state))
            videos = list(
                session.scalars(select(Video).order_by(Video.created_at.desc()))
            )
        self.projects_table.setRowCount(len(project_rows))
        for row, (project, primary_id, state) in enumerate(project_rows):
            id_item = QTableWidgetItem(str(project.id))
            id_item.setData(Qt.ItemDataRole.UserRole, primary_id)
            self.projects_table.setItem(row, 0, id_item)
            self.projects_table.setItem(row, 1, QTableWidgetItem(project.name))
            self.projects_table.setItem(row, 2, QTableWidgetItem(project.updated_at.strftime("%d.%m.%Y %H:%M")))
            self.projects_table.setItem(row, 3, QTableWidgetItem("Черновик" if state.get("dirty", True) else "Экспортирован"))
            button = QPushButton("Открыть")
            button.setObjectName("secondaryButton")
            button.setEnabled(primary_id is not None)
            button.clicked.connect(lambda checked=False, video_id=primary_id: self.open_requested.emit(video_id))
            self.projects_table.setCellWidget(row, 4, button)
        self.projects_table.resizeRowsToContents()
        self.table.setRowCount(len(videos))
        for row, video in enumerate(videos):
            id_item = QTableWidgetItem(str(video.id))
            id_item.setData(Qt.ItemDataRole.UserRole, video.id)
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(video.filename))
            self.table.setItem(
                row,
                2,
                QTableWidgetItem(video.created_at.strftime("%d.%m.%Y %H:%M")),
            )
            self.table.setItem(row, 3, QTableWidgetItem(video.status))
            details_button = QPushButton("Подробнее")
            details_button.setObjectName("secondaryButton")
            details_button.clicked.connect(
                lambda checked=False, video_id=video.id: self.open_details(video_id)
            )
            self.table.setCellWidget(row, 4, details_button)
        self.table.resizeRowsToContents()

    def open_project_for_row(self, row: int) -> None:
        item = self.projects_table.item(row, 0)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) is not None:
            self.open_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def open_details_for_row(self, row: int) -> None:
        item = self.table.item(row, 0)
        if item is not None:
            self.open_details(int(item.data(Qt.ItemDataRole.UserRole)))

    def open_details(self, video_id: int) -> None:
        with SessionLocal() as session:
            video = session.get(Video, video_id)
            if video is None:
                return
            posts = list(
                session.scalars(
                    select(Post)
                    .where(Post.video_id == video_id)
                    .order_by(Post.created_at.desc())
                )
            )

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Видео #{video_id}")
        dialog.resize(560, 360)
        layout = QVBoxLayout(dialog)
        details = [
            f"<b>Файл:</b> {video.filename}",
            f"<b>Исходник:</b> {video.original_path}",
            f"<b>Длительность:</b> {video.duration or 0:.1f} сек.",
            f"<b>Разрешение:</b> {video.width or 0}×{video.height or 0}",
            f"<b>Статус:</b> {video.status}",
            f"<b>Результат:</b> {video.output_path or '—'}",
        ]
        label = QLabel("<br>".join(details))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label)

        if posts:
            latest = posts[0]
            post_label = QLabel(
                f"Последняя публикация: {latest.platform} • {latest.status}"
                + (f"\n{latest.error_message}" if latest.error_message else "")
            )
            post_label.setWordWrap(True)
            layout.addWidget(post_label)
        else:
            latest = None
            layout.addWidget(QLabel("Публикаций для этого видео ещё нет."))
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        repeat_button = buttons.addButton(
            "Повторить публикацию",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        repeat_button.setEnabled(
            latest is not None
            and video.status == "ready"
            and bool(video.output_path)
            and Path(video.output_path).is_file()
        )
        if latest is not None:
            repeat_button.clicked.connect(
                lambda: (dialog.accept(), self.repeat_publish(latest.id))
            )
        relink_button = buttons.addButton("Перепривязать исходник…", QDialogButtonBox.ButtonRole.ActionRole)
        relink_button.clicked.connect(lambda: (dialog.accept(), self.choose_replacement(video_id)))
        layout.addWidget(buttons)
        dialog.exec()

    def choose_replacement(self, video_id: int) -> None:
        if video_id in self.relink_workers:
            return
        replacement, _ = QFileDialog.getOpenFileName(
            self, "Выберите исходное видео", "", "Video files (*.mp4 *.mov *.m4v *.webm *.mkv)")
        if not replacement:
            return
        worker = RelinkWorker(video_id, replacement, self)
        self.relink_workers[video_id] = worker
        worker.succeeded.connect(self._relink_succeeded)
        worker.error.connect(lambda message, vid=video_id: self._relink_failed(vid, message))
        worker.finished.connect(lambda vid=video_id: self._relink_finished(vid))
        self.log_message.emit(f"Проверка нового исходника видео #{video_id} запущена.")
        worker.start()

    def _relink_succeeded(self, video_id: int, path: str) -> None:
        self.log_message.emit(f"Исходник видео #{video_id} сохранён в медиатеке: {path}")
        self.refresh()
        QMessageBox.information(self, "Исходник восстановлен", "Теперь проект можно открыть снова.")

    def _relink_failed(self, video_id: int, message: str) -> None:
        self.log_message.emit(f"Ошибка перепривязки видео #{video_id}: {message}")
        QMessageBox.warning(self, "Исходник не заменён", message)

    def _relink_finished(self, video_id: int) -> None:
        worker = self.relink_workers.pop(video_id, None)
        if worker:
            worker.deleteLater()

    def repeat_publish(self, post_id: int) -> None:
        if post_id in self.workers:
            return
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            if post is None:
                return
            post.status = "queued"
            post.error_message = None
            post.external_id = None
            session.commit()

        worker = PublishWorker(post_id, self)
        self.workers[post_id] = worker
        worker.succeeded.connect(self._repeat_succeeded)
        worker.error.connect(lambda message, pid=post_id: self._repeat_failed(pid, message))
        worker.finished.connect(lambda pid=post_id: self._repeat_finished(pid))
        self.log_message.emit(f"Повторная публикация #{post_id} запущена.")
        worker.start()

    def _repeat_succeeded(self, post_id: int) -> None:
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            status = post.status if post else "unknown"
        self.log_message.emit(f"Повторная публикация #{post_id}: {status}.")
        self.refresh()
        QMessageBox.information(
            self,
            "Публикация отправлена",
            f"Текущий статус: {status}",
        )

    def _repeat_failed(self, post_id: int, message: str) -> None:
        self.log_message.emit(f"Ошибка повторной публикации #{post_id}: {message}")
        self.refresh()
        QMessageBox.critical(self, "Ошибка публикации", message)

    def _repeat_finished(self, post_id: int) -> None:
        worker = self.workers.pop(post_id, None)
        if worker:
            worker.deleteLater()

    def is_busy(self) -> bool:
        return (any(worker.isRunning() for worker in self.workers.values())
                or any(worker.isRunning() for worker in self.relink_workers.values()))
