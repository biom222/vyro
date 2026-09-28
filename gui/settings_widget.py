from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import settings
from app.services.accounts import get_active_account_id, list_accounts, set_active_account
from app.services.health import run_health_checks
from gui.components import page_header
from gui.worker import YouTubeConnectWorker


class SettingsWidget(QWidget):
    account_changed = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.oauth_worker: YouTubeConnectWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(
            page_header(
                "Настройки",
                "Состояние локального окружения, AI-провайдеров и подключённых аккаунтов.",
            )
        )

        account_group = QGroupBox("Аккаунты")
        account_layout = QVBoxLayout(account_group)
        row = QHBoxLayout()
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._select_account)
        self.connect_button = QPushButton("Подключить YouTube")
        self.connect_button.clicked.connect(self.connect_youtube)
        self.connect_button.setEnabled(bool(settings.youtube_client_id))
        row.addWidget(self.account_combo, 1)
        row.addWidget(self.connect_button)
        account_layout.addLayout(row)
        oauth_hint = QLabel(
            "Для OAuth задайте YOUTUBE_CLIENT_ID и YOUTUBE_CLIENT_SECRET в .env. "
            "Секреты сохраняются через системное хранилище учётных данных."
        )
        oauth_hint.setObjectName("muted")
        oauth_hint.setWordWrap(True)
        account_layout.addWidget(oauth_hint)
        layout.addWidget(account_group)

        config_group = QGroupBox("Режимы приложения")
        config = QFormLayout(config_group)
        config.addRow("AI:", QLabel(f"{settings.ai_provider} · {settings.openai_model}"))
        config.addRow(
            "Распознавание речи:",
            QLabel(f"{settings.transcription_provider} · {settings.whisper_model}"),
        )
        config.addRow(
            "Тренды:", QLabel("mock" if settings.trends_mock_mode else "YouTube API")
        )
        config.addRow(
            "Публикация:", QLabel("Taisly API" if settings.taisly_api_key else "mock")
        )
        config.addRow("База данных:", QLabel(settings.database_url))
        layout.addWidget(config_group)

        health_header = QHBoxLayout()
        title = QLabel("Диагностика")
        title.setObjectName("sectionTitle")
        refresh = QPushButton("Проверить снова")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.refresh_health)
        health_header.addWidget(title)
        health_header.addStretch()
        health_header.addWidget(refresh)
        layout.addLayout(health_header)
        self.health_table = QTableWidget(0, 3)
        self.health_table.setHorizontalHeaderLabels(["Компонент", "Статус", "Детали"])
        self.health_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.health_table.verticalHeader().setVisible(False)
        self.health_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.health_table, 1)
        self.refresh_accounts()
        self.refresh_health()

    def refresh_accounts(self) -> None:
        active = get_active_account_id()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("Аккаунт не выбран", None)
        selected = 0
        for account in list_accounts():
            self.account_combo.addItem(
                f"{account.provider.title()} · {account.display_name or account.username}",
                account.id,
            )
            if account.id == active:
                selected = self.account_combo.count() - 1
        self.account_combo.setCurrentIndex(selected)
        self.account_combo.blockSignals(False)

    def refresh_health(self) -> None:
        checks = run_health_checks()
        self.health_table.setRowCount(len(checks))
        for row, check in enumerate(checks):
            self.health_table.setItem(row, 0, QTableWidgetItem(check.name))
            status = QTableWidgetItem("Готово" if check.ok else "Требует внимания")
            self.health_table.setItem(row, 1, status)
            self.health_table.setItem(row, 2, QTableWidgetItem(check.detail))
        self.health_table.resizeColumnsToContents()

    def _select_account(self) -> None:
        set_active_account(self.account_combo.currentData())
        self.account_changed.emit()

    def connect_youtube(self) -> None:
        if self.oauth_worker is not None:
            return
        self.connect_button.setEnabled(False)
        self.connect_button.setText("Ожидание браузера…")
        self.oauth_worker = YouTubeConnectWorker(self)
        self.oauth_worker.succeeded.connect(self._oauth_succeeded)
        self.oauth_worker.error.connect(self._oauth_failed)
        self.oauth_worker.finished.connect(self._oauth_finished)
        self.oauth_worker.start()

    def _oauth_succeeded(self, result) -> None:
        self.log_message.emit(f"YouTube-канал «{result.display_name}» подключён.")
        self.refresh_accounts()
        self.account_changed.emit()
        QMessageBox.information(self, "YouTube подключён", result.display_name)

    def _oauth_failed(self, message: str) -> None:
        self.log_message.emit(f"OAuth YouTube: {message}")
        QMessageBox.critical(self, "Ошибка OAuth", message)

    def _oauth_finished(self) -> None:
        if self.oauth_worker:
            self.oauth_worker.deleteLater()
        self.oauth_worker = None
        self.connect_button.setText("Подключить YouTube")
        self.connect_button.setEnabled(bool(settings.youtube_client_id))

    def is_busy(self) -> bool:
        return self.oauth_worker is not None and self.oauth_worker.isRunning()
