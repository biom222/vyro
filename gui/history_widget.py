from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItem, QStandardItemModel, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QTableView, QLineEdit, QSplitter,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models import Post, Project, SessionLocal, Video
from gui.worker import PublishWorker, RelinkWorker, LibraryWorker, MediaInfoWorker


class MediaFilter(QSortFilterProxyModel):
    project_id = None

    def set_project(self, project_id):
        self.project_id = project_id
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        return (self.project_id is None or self.sourceModel().index(row, 4, parent).data() == str(self.project_id)) and super().filterAcceptsRow(row, parent)


def display_date(value):
    if not value:
        return ""
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


class HistoryWidget(QWidget):
    log_message = pyqtSignal(str)
    open_requested = pyqtSignal(int)
    project_deleted = pyqtSignal(int)
    library_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.workers: dict[int, PublishWorker] = {}
        self.relink_workers: dict[int, RelinkWorker] = {}
        self.before_duplicate = None
        self.before_delete = None
        self.before_relink = None
        self.library_worker = None
        self.info_worker = None
        self._pending_refresh = False
        self._pending_info = None
        self.inventory = {"projects": [], "videos": []}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        heading = QLabel("Проекты и медиатека")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("Монтажные проекты, исходники и сохранённые результаты.")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(heading)
        title_box.addWidget(subtitle)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        header.addLayout(title_box, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        actions = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск в проектах и медиатеке")
        actions.addWidget(self.search, 1)
        self.project_buttons = []
        for label, handler in (("Открыть", self.open_selected_project), ("Название…", self.rename_selected_project),
                               ("Дублировать…", self.duplicate_selected_project), ("Удалить…", self.delete_selected_project),
                               ("Файлы проекта", self.show_project_files)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            self.project_buttons.append(button)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.all_videos_button = QPushButton("Показать все видео")
        self.all_videos_button.clicked.connect(self.show_all_videos)
        self.all_videos_button.hide()
        actions.addWidget(self.all_videos_button)

        self.tabs = QTabWidget()
        self.projects_table = QTableView()
        self.projects_model = QStandardItemModel(0, 7, self)
        self.projects_model.setHorizontalHeaderLabels(["ID", "Проект", "Создан", "Изменён", "Сек.", "Состояние", "Открыт"])
        self.projects_proxy = QSortFilterProxyModel(self)
        self.projects_proxy.setSourceModel(self.projects_model)
        self.projects_proxy.setFilterKeyColumn(-1)
        self.projects_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.projects_proxy.setSortRole(Qt.ItemDataRole.UserRole + 1)
        self.projects_table.setModel(self.projects_proxy)
        self.projects_table.setAlternatingRowColors(True)
        self.projects_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.projects_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.projects_table.verticalHeader().hide()
        project_header = self.projects_table.horizontalHeader()
        project_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        project_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4, 5, 6):
            project_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.projects_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.projects_table.setSortingEnabled(True)
        self.projects_table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.projects_table.doubleClicked.connect(lambda index: self.open_project_for_row(index.row()))
        self.projects_table.selectionModel().currentRowChanged.connect(self._selection_changed)
        self.tabs.addTab(self.projects_table, "Проекты")

        self.table = QTableView()
        self.videos_model = QStandardItemModel(0, 5, self)
        self.videos_model.setHorizontalHeaderLabels(["ID", "Имя файла", "Дата", "Статус", "Проект"])
        self.videos_proxy = MediaFilter(self)
        self.videos_proxy.setSourceModel(self.videos_model)
        self.videos_proxy.setFilterKeyColumn(-1)
        self.videos_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.videos_proxy.setSortRole(Qt.ItemDataRole.UserRole + 1)
        self.table.setModel(self.videos_proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
        self.table.doubleClicked.connect(lambda index: self.open_details_for_row(index.row()))
        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        self.tabs.addTab(self.table, "Видео и публикации")
        split = QSplitter()
        split.addWidget(self.tabs)
        details = QWidget()
        details.setMinimumWidth(220)
        details.setMaximumWidth(360)
        details_layout = QVBoxLayout(details)
        self.thumbnail = QLabel("Выберите проект или видео")
        self.thumbnail.setMinimumSize(220, 140)
        self.thumbnail.setMaximumHeight(240)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media_label = QLabel()
        self.media_label.setTextFormat(Qt.TextFormat.PlainText)
        self.media_label.setWordWrap(True)
        self.media_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(self.thumbnail)
        details_layout.addWidget(self.media_label)
        self.file_buttons = []
        for label, handler in (("Подробнее…", self.open_selected_details), ("Найти исходник…", self.relink_selected),
                               ("Показать исходник", lambda: self.reveal_selected(False)),
                               ("Показать экспорт", lambda: self.reveal_selected(True))):
            button = QPushButton(label)
            button.clicked.connect(handler)
            self.file_buttons.append(button)
            details_layout.addWidget(button)
        details_layout.addStretch()
        split.addWidget(details)
        split.setSizes([800, 260])
        layout.addWidget(split, 1)
        self.summary_label = QLabel("Нажмите «Обновить», чтобы прочитать локальную библиотеку.")
        layout.addWidget(self.summary_label)
        self.search.textChanged.connect(self.projects_proxy.setFilterFixedString)
        self.search.textChanged.connect(self.videos_proxy.setFilterFixedString)
        self.tabs.currentChanged.connect(self._selection_changed)
        self._selection_changed()

    def refresh(self) -> None:
        if self.library_worker is not None:
            self._pending_refresh = True
            return
        self.refresh_button.setEnabled(False)
        self.summary_label.setText("Чтение проектов и проверка файлов…")
        worker = LibraryWorker(self)
        self.library_worker = worker
        worker.succeeded.connect(self._inventory_ready)
        worker.error.connect(lambda message: self.summary_label.setText("Не удалось прочитать библиотеку: " + message))
        worker.finished.connect(self._inventory_finished)
        self._selection_changed()
        worker.start()

    def _inventory_ready(self, inventory) -> None:
        self.inventory = inventory
        self.projects_model.removeRows(0, self.projects_model.rowCount())
        self.videos_model.removeRows(0, self.videos_model.rowCount())
        for project in inventory["projects"]:
            values = (project["id"], project["name"], display_date(project["created_at"]),
                      display_date(project["updated_at"]), f"{project['duration']:.1f}",
                      project["status"], display_date(project["opened_at"]))
            items = [QStandardItem(str(value)) for value in values]
            for column, item in enumerate(items):
                item.setData(project["duration"] if column == 4 else values[column], Qt.ItemDataRole.UserRole + 1)
            items[0].setData(project["primary_id"], Qt.ItemDataRole.UserRole)
            items[1].setToolTip("\n".join(project["missing"]) or project["name"])
            self.projects_model.appendRow(items)
        for video in inventory["videos"]:
            items = [QStandardItem(str(value)) for value in (video["id"], video["filename"],
                display_date(video["created_at"]), "Нет исходника" if video["missing"] else video["status"],
                video["project_id"] or "—")]
            for item in items:
                item.setData(item.text(), Qt.ItemDataRole.UserRole + 1)
            items[0].setData(video["id"], Qt.ItemDataRole.UserRole + 1)
            items[0].setData(video["id"], Qt.ItemDataRole.UserRole)
            items[1].setToolTip(video["path"])
            self.videos_model.appendRow(items)
        self.summary_label.setText(f"Проектов: {len(inventory['projects'])} · Видео: {len(inventory['videos'])}")
        self.library_changed.emit()

    def _inventory_finished(self) -> None:
        self.library_worker.deleteLater()
        self.library_worker = None
        self.refresh_button.setEnabled(True)
        self._selection_changed()
        if self._pending_refresh:
            self._pending_refresh = False
            self.refresh()

    def selected_project(self):
        index = self.projects_table.currentIndex()
        if not index.isValid():
            return None
        project_id = int(index.siblingAtColumn(0).data())
        return next((p for p in self.inventory["projects"] if p["id"] == project_id), None)

    def selected_video_id(self):
        if self.tabs.currentIndex() == 0:
            project = self.selected_project()
            return project["primary_id"] if project else None
        index = self.table.currentIndex()
        return int(index.siblingAtColumn(0).data()) if index.isValid() else None

    def _selection_changed(self, *args) -> None:
        enabled = self.tabs.currentIndex() == 0 and self.selected_project() is not None and not self.is_busy()
        for button in self.project_buttons:
            button.setEnabled(enabled)
        video_id = self.selected_video_id()
        for button in self.file_buttons:
            button.setEnabled(video_id is not None)
        self._pending_info = None
        self.thumbnail.clear()
        self.thumbnail.setText("Выберите проект или видео")
        self.media_label.clear()
        if video_id is not None:
            video = next((v for v in self.inventory["videos"] if v["id"] == video_id), None)
            if video:
                self.file_buttons[2].setEnabled(not video["missing"])
                self.file_buttons[3].setEnabled(video["output_exists"])
                self.media_label.setText(f"{video['filename']}\n{video['duration']:.1f} с · {video['width']}×{video['height']}\n{video['path']}")
                self.thumbnail.setText("Исходник недоступен" if video["missing"] else "Чтение метаданных…")
                if not video["missing"]:
                    self._pending_info = video_id
                    self._start_info()

    def _start_info(self):
        if self.info_worker or self._pending_info is None:
            return
        worker = MediaInfoWorker(self._pending_info, self)
        self._pending_info = None
        self.info_worker = worker
        worker.succeeded.connect(self._info_ready)
        worker.error.connect(self._info_failed)
        worker.finished.connect(self._info_finished)
        worker.start()

    def _info_ready(self, video_id, info):
        if video_id != self.selected_video_id():
            return
        video = next((v for v in self.inventory["videos"] if v["id"] == video_id), None)
        if video is None or str(Path(video["path"]).resolve()) != info["path"]:
            return
        self.thumbnail.setPixmap(QPixmap(info["thumbnail"]))
        self.media_label.setText(f"{info['width']}×{info['height']} · {info['duration']:.2f} с\n"
            f"{info['codec']} · {info['pixel_format']} · FPS {info['fps']}\n"
            f"{info['size']/1024/1024:.1f} МБ · {'Со звуком' if info['audio'] else 'Без звука'}\n{info['path']}")

    def _info_finished(self):
        self.info_worker.deleteLater()
        self.info_worker = None
        self._start_info()
        for button in self.project_buttons:
            button.setEnabled(self.tabs.currentIndex() == 0 and self.selected_project() is not None and not self.is_busy())

    def _info_failed(self, message):
        if self.info_worker and self.info_worker.video_id == self.selected_video_id():
            self.thumbnail.setText("Метаданные недоступны")
        self.log_message.emit("Метаданные: " + message)

    def open_project_for_row(self, row: int) -> None:
        index = self.projects_proxy.index(row, 0)
        video_id = index.data(Qt.ItemDataRole.UserRole)
        if video_id is not None and not self.relink_workers:
            self.open_requested.emit(int(video_id))

    def open_selected_project(self):
        self.open_project_for_row(self.projects_table.currentIndex().row())

    def rename_selected_project(self):
        from app.services.library import rename_project
        project = self.selected_project()
        if not project:
            return
        name, accepted = QInputDialog.getText(self, "Название проекта", "Название:", text=project["name"])
        if accepted:
            try:
                rename_project(project["id"], name)
                self.refresh()
            except ValueError as exc:
                QMessageBox.warning(self, "Название не изменено", str(exc))
            except SQLAlchemyError:
                QMessageBox.warning(self, "Название не изменено", "База данных недоступна или занята. Повторите позже.")

    def delete_selected_project(self):
        from app.services.library import delete_project
        project = self.selected_project()
        if not project:
            return
        if self.before_delete is not None and not self.before_delete(project["id"]):
            return
        # Re-read the revision after saving the active draft, before consent.
        with SessionLocal() as session:
            row = session.get(Project, project["id"])
            if row is None:
                return
            revision = row.draft_revision
        if QMessageBox.question(self, "Удалить проект?",
            f"Удалить проект «{project['name']}» и историю его монтажа?\n"
            "Исходники, музыка, MP4 и публикации останутся в медиатеке. Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_project(project["id"], revision)
        except ValueError as exc:
            QMessageBox.warning(self, "Проект не удалён", str(exc))
            return
        except SQLAlchemyError:
            QMessageBox.warning(self, "Проект не удалён", "База данных недоступна или занята. Повторите позже.")
            return
        self.project_deleted.emit(project["id"])
        self.refresh()

    def show_project_files(self):
        project = self.selected_project()
        if project:
            self.tabs.setCurrentIndex(1)
            self.videos_proxy.set_project(project["id"])
            self.all_videos_button.show()
            self.search.clear()
            for row in range(self.videos_proxy.rowCount()):
                if self.videos_proxy.index(row, 4).data() == str(project["id"]):
                    self.table.selectRow(row)
                    break

    def show_all_videos(self):
        self.videos_proxy.set_project(None)
        self.all_videos_button.hide()

    def open_selected_details(self):
        video_id = self.selected_video_id()
        if video_id is not None:
            self.open_details(video_id)

    def relink_selected(self):
        video_id = self.selected_video_id()
        if video_id is not None:
            self.choose_replacement(video_id)

    def reveal_selected(self, output):
        from gui.local_files import reveal_file
        video = next((v for v in self.inventory["videos"] if v["id"] == self.selected_video_id()), None)
        if video:
            reveal_file(video["output_path"] if output else video["path"], self)

    def duplicate_selected_project(self) -> None:
        from app.services.projects import duplicate_project
        from sqlalchemy.exc import SQLAlchemyError
        if self.before_duplicate is not None and not self.before_duplicate():
            return
        project = self.selected_project()
        if project is None:
            QMessageBox.information(self, "Выберите проект", "Выберите проект в таблице.")
            return
        name, accepted = QInputDialog.getText(self, "Дублировать проект", "Название независимой копии:")
        if not accepted:
            return
        try:
            _project_id, video_id = duplicate_project(project["id"], name)
        except (ValueError, SQLAlchemyError):
            import logging
            logging.getLogger(__name__).exception("Could not duplicate project")
            QMessageBox.warning(self, "Копия не создана", "Не удалось создать копию. Сначала сохраните исходный проект.")
            return
        self.refresh()
        self.open_requested.emit(video_id)

    def open_details_for_row(self, row: int) -> None:
        video_id = self.videos_proxy.index(row, 0).data(Qt.ItemDataRole.UserRole)
        if video_id is not None:
            self.open_details(int(video_id))

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
        details = [f"Файл: {video.filename}", f"Исходник: {video.original_path}",
                   f"Длительность: {video.duration or 0:.1f} сек.",
                   f"Разрешение: {video.width or 0}×{video.height or 0}", f"Статус: {video.status}",
                   f"Результат: {video.output_path or '—'}"]
        label = QLabel("\n".join(details))
        label.setTextFormat(Qt.TextFormat.PlainText)
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
            and latest.status in {"error", "queued"}
            and latest.account_id is not None
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
        if self.before_relink is not None and not self.before_relink(video_id):
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
        self._selection_changed()

    def repeat_publish(self, post_id: int) -> None:
        if post_id in self.workers:
            return
        with SessionLocal() as session:
            post = session.get(Post, post_id)
            if post is None:
                return
            if post.platform == "youtube" and (post.external_id or (post.payload_json or {}).get("youtube_upload_attempted")):
                QMessageBox.warning(self, "Проверьте статус", "Эта операция уже отправлялась в YouTube. Повторная загрузка заблокирована; используйте проверку статуса в разделе публикации.")
                return
            if post.status not in {"error", "queued"} or post.account_id is None:
                QMessageBox.warning(self, "Повторная публикация",
                                    "Опубликованный или ожидающий ролик нельзя отправлять повторно: это создаст дубликат.")
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
        return (self.library_worker is not None or self.info_worker is not None
                or any(worker.isRunning() for worker in self.workers.values())
                or any(worker.isRunning() for worker in self.relink_workers.values()))
