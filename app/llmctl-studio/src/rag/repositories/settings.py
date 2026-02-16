from __future__ import annotations

from sqlalchemy import select

from core.db import session_scope
from core.models import RAGSetting


def normalize_provider(value: str | None) -> str:
    return (value or "").strip().lower()


def load_rag_settings(provider: str) -> dict[str, str]:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return {}
    with session_scope() as session:
        rows = (
            session.execute(
                select(RAGSetting).where(RAGSetting.provider == provider_key)
            )
            .scalars()
            .all()
        )
    return {row.key: row.value for row in rows}


def save_rag_settings(provider: str, payload: dict[str, str]) -> None:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return
    cleaned = {key: (value or "").strip() for key, value in payload.items()}
    with session_scope() as session:
        existing = (
            session.execute(
                select(RAGSetting).where(RAGSetting.provider == provider_key)
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
                RAGSetting.create(
                    session, provider=provider_key, key=key, value=value
                )


def ensure_rag_setting_defaults(provider: str, defaults: dict[str, str]) -> None:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return
    with session_scope() as session:
        existing = (
            session.execute(
                select(RAGSetting).where(RAGSetting.provider == provider_key)
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
            RAGSetting.create(
                session,
                provider=provider_key,
                key=key,
                value=str(value),
            )
