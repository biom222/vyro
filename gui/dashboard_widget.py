from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QTableView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from PyQt6.QtGui import QStandardItem, QStandardItemModel

from app.models import SessionLocal, Video
from app.services.accounts import get_active_account_id, list_accounts, set_active_account
from app.services.dashboard import get_dashboard_summary
from gui.components import page_header
from gui.worker import AnalyticsSyncWorker


class DashboardWidget(QWidget):
    navigate_requested = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sync_worker: AnalyticsSyncWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        refresh = QPushButton("Обновить")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(
            page_header(
                "Обзор",
                "Контент, публикации и статистика активного аккаунта в одном месте.",
                refresh,
            )
        )

        account_row = QHBoxLayout()
        account_row.addWidget(QLabel("Активный аккаунт"))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(260)
        self.account_combo.currentIndexChanged.connect(self._account_changed)
        account_row.addWidget(self.account_combo)
        self.sync_button = QPushButton("Синхронизировать аналитику")
        self.sync_button.setObjectName("secondaryButton")
        self.sync_button.clicked.connect(self.sync_analytics)
        account_row.addWidget(self.sync_button)
        account_row.addStretch()
        layout.addLayout(account_row)

        self.metrics = QTableView()
        self.metrics_model = QStandardItemModel(0, 3, self)
        self.metrics_model.setHorizontalHeaderLabels(["Показатель", "Значение", "Примечание"])
        self.metrics.setModel(self.metrics_model)
        self.metrics.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.metrics.setShowGrid(False)
        self.metrics.verticalHeader().hide()
        self.metrics.verticalHeader().setDefaultSectionSize(24)
        self.metrics.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics.setMaximumHeight(180)
        layout.addWidget(self.metrics)

        quick = QHBoxLayout()
        for text, target in (
            ("+ Новый проект", "editor"),
            ("Найти AI-клипы", "ai"),
            ("Посмотреть тренды", "trends"),
            ("Календарь", "calendar"),
        ):
            button = QPushButton(text)
            if target != "editor":
                button.setObjectName("secondaryButton")
            button.clicked.connect(
                lambda checked=False, page=target: self.navigate_requested.emit(page)
            )
            quick.addWidget(button)
        quick.addStretch()
        layout.addLayout(quick)

        recent_title = QLabel("Последние видео")
        recent_title.setObjectName("sectionTitle")
        layout.addWidget(recent_title)
        self.recent_table = QTableWidget(0, 4)
        self.recent_table.setHorizontalHeaderLabels(
            ["Файл", "Длительность", "Статус", "Создано"]
        )
        self.recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in (1, 2, 3):
            self.recent_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self.recent_table, 1)
        self.refresh()

    def refresh(self) -> None:
        active_id = get_active_account_id()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("Аккаунт не подключён", None)
        selected = 0
        accounts = list_accounts()
        for account in accounts:
            label = f"{account.provider.title()} · {account.display_name or account.username}"
            self.account_combo.addItem(label, account.id)
            if account.id == active_id:
                selected = self.account_combo.count() - 1
        self.account_combo.setCurrentIndex(selected)
        self.account_combo.blockSignals(False)
        active_account = next((account for account in accounts if account.id == active_id), None)
        self.sync_button.setEnabled(bool(active_account and active_account.provider == "youtube"
                                         and self.sync_worker is None))

        summary = get_dashboard_summary()
        change = f"{summary.views_change:+,} к прошлому периоду" if summary.views_change else "Нет предыдущего периода"
        self.metrics_model.removeRows(0, self.metrics_model.rowCount())
        for row in (
            ("Просмотры", f"{summary.views:,}", change),
            ("Лайки", f"{summary.likes:,}", f"{summary.shares:,} репостов"),
            ("Комментарии", f"{summary.comments:,}", f"Подписчики: {summary.subscribers_net:+,}"),
            ("Время просмотра", f"{summary.watch_time_minutes / 60:.1f} ч", "За последний синк"),
            ("Проекты", str(summary.projects), f"{summary.ready_videos} роликов готово"),
            ("Опубликовано", str(summary.published_posts), f"{summary.scheduled_posts} запланировано"),
        ):
            self.metrics_model.appendRow([QStandardItem(value) for value in row])

        with SessionLocal() as session:
            videos = list(
                session.scalars(select(Video).order_by(Video.created_at.desc()).limit(8))
            )
        self.recent_table.setRowCount(len(videos))
        for row, video in enumerate(videos):
            self.recent_table.setItem(row, 0, QTableWidgetItem(video.filename))
            self.recent_table.setItem(
                row, 1, QTableWidgetItem(f"{video.duration:.1f} с" if video.duration else "—")
            )
            self.recent_table.setItem(row, 2, QTableWidgetItem(video.status))
            self.recent_table.setItem(
                row, 3, QTableWidgetItem(video.created_at.strftime("%d.%m.%Y %H:%M"))
            )

    def _account_changed(self) -> None:
        set_active_account(self.account_combo.currentData())
        self.refresh()

    def sync_analytics(self) -> None:
        account_id = get_active_account_id()
        account = next((item for item in list_accounts() if item.id == account_id), None)
        if account is None or account.provider != "youtube" or self.sync_worker is not None:
            return
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Синхронизация…")
        today = date.today()
        self.sync_worker = AnalyticsSyncWorker(
            account_id, today - timedelta(days=28), today, self
        )
        self.sync_worker.succeeded.connect(self._sync_succeeded)
        self.sync_worker.error.connect(self._sync_failed)
        self.sync_worker.finished.connect(self._sync_finished)
        self.sync_worker.start()

    def _sync_succeeded(self, snapshot_id: int) -> None:
        self.log_message.emit(f"Аналитика обновлена, snapshot #{snapshot_id}.")
        self.refresh()

    def _sync_failed(self, message: str) -> None:
        self.log_message.emit(f"Ошибка синхронизации аналитики: {message}")

    def _sync_finished(self) -> None:
        if self.sync_worker:
            self.sync_worker.deleteLater()
        self.sync_worker = None
        self.sync_button.setText("Синхронизировать аналитику")
        self.refresh()

    def is_busy(self) -> bool:
        return self.sync_worker is not None and self.sync_worker.isRunning()
