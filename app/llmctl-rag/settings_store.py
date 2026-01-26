from __future__ import annotations

from sqlalchemy import select

from db import init_db, session_scope
from models import IntegrationSetting


def normalize_provider(value: str | None) -> str:
    return (value or "").strip().lower()


def load_integration_settings(provider: str) -> dict[str, str]:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return {}
    init_db()
    with session_scope() as session:
        rows = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == provider_key
                )
            )
            .scalars()
            .all()
        )
    return {row.key: row.value for row in rows}


def save_integration_settings(provider: str, payload: dict[str, str]) -> None:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return
    cleaned = {key: (value or "").strip() for key, value in payload.items()}
    init_db()
    with session_scope() as session:
        existing = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == provider_key
                )
            )
            .scalars()
            .all()
        )
        existing_map = {setting.key: setting for setting in existing}
        for key, value in cleaned.items():
            if not value:
                if key in existing_map:
                    session.delete(existing_map[key])
                continue
            if key in existing_map:
                existing_map[key].value = value
            else:
                IntegrationSetting.create(
                    session, provider=provider_key, key=key, value=value
                )


def ensure_integration_defaults(provider: str, defaults: dict[str, str]) -> None:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return
    init_db()
    with session_scope() as session:
        existing = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == provider_key
                )
            )
            .scalars()
            .all()
        )
        existing_keys = {setting.key for setting in existing}
        for key, value in defaults.items():
            if key in existing_keys:
                continue
            if value is None or str(value).strip() == "":
                continue
            IntegrationSetting.create(
                session, provider=provider_key, key=key, value=str(value)
            )
