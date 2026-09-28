from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent
from PyQt6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QStyle,
)

from app.config import settings
from gui.ai_clips_widget import AIClipsWidget
from gui.calendar_widget import CalendarWidget
from gui.dashboard_widget import DashboardWidget
from gui.editor_workspace import EditorWorkspace
from gui.history_widget import HistoryWidget
from gui.publish_widget import PublishWidget
from gui.settings_widget import SettingsWidget
from gui.trends_widget import TrendsWidget
from gui.theme import apply_theme, set_flat_icon


class MainWindow(QMainWindow):
    PAGE_ORDER = (
        ("dashboard", "", "Обзор"),
        ("editor", "", "Редактор"),
        ("ai", "", "AI-клипы"),
        ("trends", "", "Тренды"),
        ("calendar", "", "Календарь"),
        ("publish", "", "Публикация"),
        ("history", "", "История"),
        ("settings", "", "Настройки"),
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle(settings.app_name)
        self.resize(1380, 880)
        self.setMinimumSize(1040, 700)

        self.page_indexes: dict[str, int] = {}
        self.pages = QStackedWidget()
        self.tabs = self.pages
        self.setCentralWidget(self.pages)

        self.dashboard_widget = DashboardWidget()
        self.editor_workspace = EditorWorkspace()
        self.upload_widget = self.editor_workspace.upload_widget
        self.edit_widget = self.editor_workspace.edit_widget
        self.ai_widget = AIClipsWidget()
        self.trends_widget = TrendsWidget()
        self.calendar_widget = CalendarWidget()
        self.publish_widget = PublishWidget()
        self.history_widget = HistoryWidget()
        self.settings_widget = SettingsWidget()

        page_widgets = (
            self.dashboard_widget,
            self.editor_workspace,
            self.ai_widget,
            self.trends_widget,
            self.calendar_widget,
            self.publish_widget,
            self.history_widget,
            self.settings_widget,
        )
        for index, ((page_id, _, _), widget) in enumerate(zip(self.PAGE_ORDER, page_widgets)):
            self.page_indexes[page_id] = index
            self.pages.addWidget(widget)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(165)
        self.log_view.document().setMaximumBlockCount(400)
        log_dock = QDockWidget("Журнал операций", self)
        log_dock.setObjectName("logDock")
        log_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        log_dock.setWidget(self.log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, log_dock)
        self.log_dock = log_dock
        log_dock.hide()
        log_toggle = QPushButton("Журнал")
        log_toggle.setObjectName("secondaryButton")
        log_toggle.clicked.connect(lambda: log_dock.setVisible(not log_dock.isVisible()))
        self.statusBar().addPermanentWidget(log_toggle)

        self.dashboard_widget.navigate_requested.connect(self.navigate)
        self.editor_workspace.video_ready.connect(self._on_video_ready)
        self.editor_workspace.render_completed.connect(self._on_render_completed)
        self.editor_workspace.publish_requested.connect(lambda: self.navigate("publish"))
        self.editor_workspace.ai_requested.connect(lambda: self.navigate("ai"))
        self.history_widget.open_requested.connect(self._open_project)
        self.ai_widget.edit_clip_requested.connect(self._edit_ai_clip)
        self.publish_widget.publication_completed.connect(self._publication_completed)
        self.settings_widget.account_changed.connect(self.dashboard_widget.refresh)
        for widget in page_widgets:
            if hasattr(widget, "log_message"):
                widget.log_message.connect(self.log)

        self.pages.currentChanged.connect(self._page_changed)
        self._build_menus()
        apply_theme(self)
        self.statusBar().showMessage("Готово")
        self.navigate("editor")
        self.log("vyro запущен. Создайте проект или откройте существующие данные.")


    def _build_menus(self) -> None:
        self.menuBar().setNativeMenuBar(False)
        file_menu = self.menuBar().addMenu("Файл")
        edit_menu = self.menuBar().addMenu("Монтаж")
        view_menu = self.menuBar().addMenu("Вид")
        tools_menu = self.menuBar().addMenu("Инструменты")

        self.toolbar = QToolBar("Основные действия", self)
        self.toolbar.setObjectName("mainToolbar")
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(self.toolbar)

        def action(menu, label, icon, callback, shortcut=None):
            item = QAction(label, self)
            set_flat_icon(item, icon)
            item.triggered.connect(callback)
            if shortcut:
                item.setShortcut(shortcut)
            menu.addAction(item)
            self.toolbar.addAction(item)
            return item

        action(file_menu, "Добавить видео", QStyle.StandardPixmap.SP_DialogOpenButton,
               self._import_video, "Ctrl+O")
        self.save_project_action = action(file_menu, "Сохранить проект", QStyle.StandardPixmap.SP_DialogSaveButton,
                                          self.editor_workspace.save_project, "Ctrl+S")
        file_menu.addAction("Открыть проект…").triggered.connect(lambda: self.navigate("history"))
        self.export_action = action(file_menu, "Экспорт MP4", QStyle.StandardPixmap.SP_DialogSaveButton,
                                   self.edit_widget.start_render, "Ctrl+E")
        self.save_action = action(file_menu, "Сохранить копию", QStyle.StandardPixmap.SP_DialogSaveButton,
                                 self.edit_widget.save_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Выход")
        exit_action.triggered.connect(self.close)
        self.toolbar.addSeparator()
        action(edit_menu, "Воспроизведение / пауза", QStyle.StandardPixmap.SP_MediaPlay,
               self.editor_workspace.toggle_playback)
        action(edit_menu, "AI-клипы", QStyle.StandardPixmap.SP_FileDialogDetailedView,
               lambda: self.navigate("ai"))
        for label, callback in (
            ("Начало фрагмента в текущей позиции", lambda: self.editor_workspace._set_mark(True)),
            ("Конец фрагмента в текущей позиции", lambda: self.editor_workspace._set_mark(False)),
        ):
            edit_menu.addAction(label).triggered.connect(callback)

        self.page_actions = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, _, label in self.PAGE_ORDER:
            item = QAction(label, self, checkable=True)
            item.triggered.connect(lambda checked=False, page=key: self.navigate(page))
            group.addAction(item)
            view_menu.addAction(item)
            self.page_actions[key] = item
        view_menu.addSeparator()
        view_menu.addAction(self.log_dock.toggleViewAction())
        view_menu.addAction(self.toolbar.toggleViewAction())
        themes = view_menu.addMenu("Тема")
        theme_group = QActionGroup(self)
        for label, light in (("Тёмная", False), ("Светлая", True)):
            item = QAction(label, self, checkable=True)
            item.setChecked(not light)
            item.triggered.connect(lambda checked=False, value=light: apply_theme(self, value))
            theme_group.addAction(item)
            themes.addAction(item)
        tools_menu.addAction("Настройки и аккаунты").triggered.connect(lambda: self.navigate("settings"))
        self.mode_label = QLabel("Публикация: тестовый режим" if not settings.taisly_api_key else "Публикация: Taisly")
        self.mode_label.setObjectName("muted")
        self.statusBar().addPermanentWidget(self.mode_label)
        self.editor_workspace.video_ready.connect(self._sync_actions)
        self.edit_widget.busy_changed.connect(self._sync_actions)
        self.edit_widget.render_completed.connect(self._sync_actions)
        self._sync_actions()

    def _sync_actions(self, *args) -> None:
        self.save_project_action.setEnabled(self.editor_workspace.project_id is not None and not self.edit_widget.is_busy())
        self.export_action.setEnabled(self.edit_widget.video_id is not None and not self.edit_widget.is_busy())
        self.save_action.setEnabled(bool(self.edit_widget.output_path) and not self.edit_widget.is_busy())

    def _import_video(self) -> None:
        self.navigate("editor")
        self.upload_widget.choose_video()

    def _open_project(self, video_id: int) -> None:
        self.editor_workspace.open_existing(video_id)
        self.navigate("editor")

    def navigate(self, page_id: str) -> None:
        index = self.page_indexes.get(page_id)
        if index is None:
            return
        self.pages.setCurrentIndex(index)
        self.page_actions[page_id].setChecked(True)

    def _page_changed(self, index: int) -> None:
        page_id = self.PAGE_ORDER[index][0]
        if page_id == "dashboard":
            self.dashboard_widget.refresh()
        elif page_id == "ai":
            self.ai_widget.refresh()
        elif page_id == "trends":
            self.trends_widget.refresh()
        elif page_id == "calendar":
            self.calendar_widget.refresh()
        elif page_id == "publish" and self.publish_widget.video_id:
            self.publish_widget.load_platforms()
        elif page_id == "history":
            self.history_widget.refresh()
        elif page_id == "settings":
            self.settings_widget.refresh_accounts()
            self.settings_widget.refresh_health()

    def _on_video_ready(self, project_id: int, video_id: int) -> None:
        self.ai_widget.set_context(project_id, video_id)
        self.history_widget.refresh()
        self.dashboard_widget.refresh()
        self.statusBar().showMessage(f"Проект #{project_id} готов к монтажу")

    def _on_render_completed(self, video_id: int, output_path: str, duration: float) -> None:
        self.publish_widget.set_video(video_id, output_path, duration)
        self.history_widget.refresh()
        self.dashboard_widget.refresh()
        self.statusBar().showMessage("Рендер завершён")

    def _edit_ai_clip(
        self, video_id: int, project_id: int, start_time: float, end_time: float
    ) -> None:
        self.editor_workspace.load_clip(video_id, project_id, start_time, end_time)
        self.navigate("editor")
        self.log(f"AI-фрагмент {start_time:.1f}–{end_time:.1f} сек. открыт в редакторе.")

    def _publication_completed(self) -> None:
        self.history_widget.refresh()
        self.calendar_widget.refresh()
        self.dashboard_widget.refresh()

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f"[{timestamp}] {message}")

    def closeEvent(self, event: QCloseEvent) -> None:
        widgets = (
            self.dashboard_widget,
            self.editor_workspace,
            self.ai_widget,
            self.trends_widget,
            self.calendar_widget,
            self.publish_widget,
            self.history_widget,
            self.settings_widget,
        )
        if any(widget.is_busy() for widget in widgets):
            QMessageBox.warning(
                self,
                "Операция выполняется",
                "Дождитесь завершения фоновой операции перед закрытием приложения.",
            )
            event.ignore()
            return
        self.editor_workspace.save_project(silent=True)
        self.editor_workspace.player.stop()
        event.accept()
