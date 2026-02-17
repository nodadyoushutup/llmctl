from __future__ import annotations

from sqlalchemy import select

from db import init_db, session_scope
from models import IntegrationSetting

GOOGLE_DRIVE_LEGACY_PROVIDER = "google_drive"
GOOGLE_CLOUD_PROVIDER = "google_cloud"
GOOGLE_WORKSPACE_PROVIDER = "google_workspace"
GOOGLE_PROVIDER_SET = {
    GOOGLE_DRIVE_LEGACY_PROVIDER,
    GOOGLE_CLOUD_PROVIDER,
    GOOGLE_WORKSPACE_PROVIDER,
}
GOOGLE_CLOUD_KEYS = (
    "service_account_json",
    "google_cloud_project_id",
)
GOOGLE_WORKSPACE_KEYS = (
    "service_account_json",
    "workspace_delegated_user_email",
)


def normalize_provider(value: str | None) -> str:
    return (value or "").strip().lower()


def migrate_legacy_google_integration_settings() -> bool:
    init_db()
    with session_scope() as session:
        rows = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider.in_(tuple(sorted(GOOGLE_PROVIDER_SET)))
                )
            )
            .scalars()
            .all()
        )
        by_provider: dict[str, dict[str, IntegrationSetting]] = {}
        for row in rows:
            provider_rows = by_provider.setdefault(row.provider, {})
            provider_rows[row.key] = row

        legacy_rows = by_provider.get(GOOGLE_DRIVE_LEGACY_PROVIDER, {})
        if not legacy_rows:
            return False

        cloud_rows = by_provider.setdefault(GOOGLE_CLOUD_PROVIDER, {})
        workspace_rows = by_provider.setdefault(GOOGLE_WORKSPACE_PROVIDER, {})
        changed = False

        def _copy_if_missing(
            target_rows: dict[str, IntegrationSetting],
            target_provider: str,
            key: str,
            value: str,
        ) -> None:
            nonlocal changed
            cleaned = (value or "").strip()
            if not cleaned or key in target_rows:
                return
            target_rows[key] = IntegrationSetting.create(
                session,
                provider=target_provider,
                key=key,
                value=cleaned,
            )
            changed = True

        for key in GOOGLE_CLOUD_KEYS:
            row = legacy_rows.get(key)
            if row is not None:
                _copy_if_missing(cloud_rows, GOOGLE_CLOUD_PROVIDER, key, row.value)

        for key in GOOGLE_WORKSPACE_KEYS:
            row = legacy_rows.get(key)
            if row is not None:
                _copy_if_missing(
                    workspace_rows,
                    GOOGLE_WORKSPACE_PROVIDER,
                    key,
                    row.value,
                )

        shared_service_account = legacy_rows.get("service_account_json")
        if shared_service_account is not None:
            _copy_if_missing(
                cloud_rows,
                GOOGLE_CLOUD_PROVIDER,
                "service_account_json",
                shared_service_account.value,
            )
            _copy_if_missing(
                workspace_rows,
                GOOGLE_WORKSPACE_PROVIDER,
                "service_account_json",
                shared_service_account.value,
            )

        for row in legacy_rows.values():
            session.delete(row)
            changed = True

    return changed


def load_integration_settings(provider: str) -> dict[str, str]:
    provider_key = normalize_provider(provider)
    if not provider_key:
        return {}
    if provider_key in GOOGLE_PROVIDER_SET:
        migrate_legacy_google_integration_settings()
    if provider_key == GOOGLE_DRIVE_LEGACY_PROVIDER:
        provider_key = GOOGLE_WORKSPACE_PROVIDER
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
    if provider_key in GOOGLE_PROVIDER_SET:
        migrate_legacy_google_integration_settings()
    if provider_key == GOOGLE_DRIVE_LEGACY_PROVIDER:
        provider_key = GOOGLE_WORKSPACE_PROVIDER
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
