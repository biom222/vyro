"""Top menu for connecting and selecting direct publishing accounts."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QMessageBox

from app.config import settings
from app.services.accounts import get_active_account_id, list_accounts, set_active_account
from gui.theme import service_icon
from gui.worker import AccountConnectWorker


SERVICES = (("youtube", "YouTube"), ("tiktok", "TikTok"), ("instagram", "Instagram"))


class AccountsMenu(QObject):
    account_changed = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.menu = parent.menuBar().addMenu("Аккаунты")
        self.menu.aboutToShow.connect(self.refresh)
        self.connect_worker: AccountConnectWorker | None = None
        self.action_group: QActionGroup | None = None
        self.refresh()

    def refresh(self) -> None:
        self.menu.clear()
        if self.action_group is not None:
            self.action_group.deleteLater()
        active = get_active_account_id()
        accounts = list_accounts()
        group = QActionGroup(self.menu)
        group.setExclusive(True)
        self.action_group = group
        for provider, title in SERVICES:
            service = self.menu.addMenu(service_icon(provider), title)
            matches = [account for account in accounts if account.provider == provider]
            if matches:
                for account in matches:
                    label = account.display_name or account.username or account.external_id
                    if account.username and account.username != label:
                        label += f" (@{account.username.lstrip('@')})"
                    action = QAction(label, service, checkable=True)
                    action.setChecked(account.id == active)
                    action.setEnabled(account.status == "connected" and bool(account.credential_ref))
                    action.setToolTip("Текущий адресат публикации" if account.id == active else "Выбрать адресата")
                    action.triggered.connect(
                        lambda checked=False, account_id=account.id: self.select_account(account_id)
                    )
                    group.addAction(action)
                    service.addAction(action)
                service.addSeparator()
            else:
                empty = service.addAction("Нет подключённых аккаунтов")
                empty.setEnabled(False)
            add = service.addAction("Добавить аккаунт…")
            add.setEnabled(self.connect_worker is None)
            add.triggered.connect(
                lambda checked=False, selected=provider: self.connect_account(selected)
            )
        self.menu.addSeparator()
        current = next((account for account in accounts if account.id == active), None)
        info = self.menu.addAction(
            f"Выбрано: {current.provider.title()} · {current.display_name}" if current else "Аккаунт не выбран"
        )
        info.setEnabled(False)

    def select_account(self, account_id: int) -> None:
        account = next((item for item in list_accounts() if item.id == account_id), None)
        if account is None or account.status != "connected" or not account.credential_ref:
            QMessageBox.warning(self.menu.parentWidget(), "Аккаунт",
                                "Этот аккаунт недоступен. Подключите его повторно.")
            return
        set_active_account(account_id)
        self.refresh()
        self.account_changed.emit()

    def connect_account(self, provider: str) -> None:
        if self.connect_worker is not None:
            return
        required = {
            "youtube": bool(settings.youtube_client_id and settings.youtube_client_secret),
            "tiktok": bool(settings.tiktok_client_key and settings.tiktok_client_secret),
            "instagram": bool(settings.instagram_app_id and settings.instagram_app_secret),
        }
        if not required[provider]:
            QMessageBox.warning(
                self.menu.parentWidget(), "Настройка API",
                f"Сначала добавьте OAuth-данные {provider.title()} в локальный .env и перезапустите vyro."
            )
            return
        self.connect_worker = AccountConnectWorker(provider, self)
        self.connect_worker.succeeded.connect(self._connected)
        self.connect_worker.error.connect(self._failed)
        self.connect_worker.finished.connect(self._finished)
        self.connect_worker.start()
        self.refresh()
        self.log_message.emit(f"Ожидание подключения {provider.title()} в браузере…")

    def _connected(self, provider: str, account_ids: object) -> None:
        self.refresh()
        self.account_changed.emit()
        self.log_message.emit(f"Подключено аккаунтов {provider.title()}: {len(account_ids)}.")
        QMessageBox.information(self.menu.parentWidget(), "Аккаунт подключён",
                                f"{provider.title()}: {len(account_ids)} аккаунт(ов).")

    def _failed(self, message: str) -> None:
        self.log_message.emit(f"Подключение аккаунта: {message}")
        QMessageBox.critical(self.menu.parentWidget(), "Ошибка подключения", message)

    def _finished(self) -> None:
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if worker is self.connect_worker:
            self.connect_worker = None
        self.refresh()

    def is_busy(self) -> bool:
        return self.connect_worker is not None and self.connect_worker.isRunning()
