from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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


class SettingsWidget(QWidget):
    account_changed = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        row.addWidget(self.account_combo, 1)
        account_layout.addLayout(row)
        oauth_hint = QLabel(
            "Добавление и выбор аккаунтов YouTube, TikTok и Instagram — в верхнем меню «Аккаунты». "
            "OAuth-ключи задаются в .env; токены сохраняются в системном хранилище."
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
            "Публикация:", QLabel("Прямые API YouTube, TikTok и Instagram")
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

    def is_busy(self) -> bool:
        return False
