from __future__ import annotations

from sqlalchemy import select

from app.models import AppPreference, ConnectedAccount, SessionLocal


ACTIVE_ACCOUNT_KEY = "active_account_id"


def upsert_account(
    provider: str,
    external_id: str,
    display_name: str,
    username: str = "",
    avatar_url: str | None = None,
) -> int:
    normalized_provider = provider.strip().lower()
    if not normalized_provider or not external_id.strip():
        raise ValueError("Provider and external account ID are required")
    with SessionLocal() as session:
        account = session.scalar(
            select(ConnectedAccount).where(
                ConnectedAccount.provider == normalized_provider,
                ConnectedAccount.external_id == external_id.strip(),
            )
        )
        if account is None:
            account = ConnectedAccount(
                provider=normalized_provider,
                external_id=external_id.strip(),
            )
            session.add(account)
        account.display_name = display_name.strip()
        account.username = username.strip()
        account.avatar_url = avatar_url
        account.status = "connected"
        session.commit()
        session.refresh(account)
        return account.id


def set_active_account(account_id: int | None) -> None:
    with SessionLocal() as session:
        if account_id is not None and session.get(ConnectedAccount, account_id) is None:
            raise ValueError(f"Connected account {account_id} does not exist")
        preference = session.get(AppPreference, ACTIVE_ACCOUNT_KEY)
        if preference is None:
            preference = AppPreference(key=ACTIVE_ACCOUNT_KEY)
            session.add(preference)
        preference.value_json = account_id
        session.commit()


def get_active_account_id() -> int | None:
    with SessionLocal() as session:
        preference = session.get(AppPreference, ACTIVE_ACCOUNT_KEY)
        if preference is None or preference.value_json is None:
            return None
        return int(preference.value_json)


def list_accounts() -> list[ConnectedAccount]:
    with SessionLocal() as session:
        accounts = list(
            session.scalars(
                select(ConnectedAccount).order_by(
                    ConnectedAccount.provider.asc(), ConnectedAccount.display_name.asc()
                )
            ).all()
        )
        for account in accounts:
            session.expunge(account)
        return accounts
