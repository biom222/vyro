from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class CredentialStore(ABC):
    @abstractmethod
    def set(self, key: str, value: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get(self, reference: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, reference: str) -> None:
        raise NotImplementedError


class MemoryCredentialStore(CredentialStore):
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, key: str, value: str) -> str:
        self._values[key] = value
        return key

    def get(self, reference: str) -> str | None:
        return self._values.get(reference)

    def delete(self, reference: str) -> None:
        self._values.pop(reference, None)


class KeyringCredentialStore(CredentialStore):
    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("keyring is required for persistent account credentials") from exc
        self._keyring = keyring
        self._service = f"{settings.app_name}.credentials"

    def set(self, key: str, value: str) -> str:
        self._keyring.set_password(self._service, key, value)
        return key

    def get(self, reference: str) -> str | None:
        return self._keyring.get_password(self._service, reference)

    def delete(self, reference: str) -> None:
        try:
            self._keyring.delete_password(self._service, reference)
        except self._keyring.errors.PasswordDeleteError:
            pass


_memory_store = MemoryCredentialStore()


def get_credential_store(backend: str | None = None) -> CredentialStore:
    selected = (backend or settings.credential_backend or "keyring").strip().lower()
    if selected == "memory":
        logger.warning("Using in-memory credentials; tokens will be lost when the app exits")
        return _memory_store
    if selected == "keyring":
        return KeyringCredentialStore()
    raise ValueError(f"Unsupported credential backend: {selected}")
