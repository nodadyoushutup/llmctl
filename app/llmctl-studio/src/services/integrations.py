from __future__ import annotations

from sqlalchemy import select

from core.config import Config
from core.db import session_scope
from core.models import IntegrationSetting

LLM_PROVIDERS = ("codex", "gemini", "claude")
LLM_PROVIDER_LABELS = {
    "codex": "Codex",
    "gemini": "Gemini",
    "claude": "Claude",
}


def normalize_provider(value: str | None) -> str:
    return (value or "").strip().lower()


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def resolve_enabled_llm_providers(
    settings: dict[str, str] | None = None,
) -> set[str]:
    settings = settings or load_integration_settings("llm")
    enabled_keys = [
        key for key in settings if key.startswith("provider_enabled_")
    ]
    if not enabled_keys:
        return set(LLM_PROVIDERS)
    enabled: set[str] = set()
    for provider in LLM_PROVIDERS:
        key = f"provider_enabled_{provider}"
        if _as_bool(settings.get(key)):
            enabled.add(provider)
    return enabled


def resolve_default_model_id(settings: dict[str, str] | None = None) -> int | None:
    settings = settings or load_integration_settings("llm")
    raw = (settings.get("default_model_id") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def resolve_llm_provider(
    default: str | None = None,
    *,
    settings: dict[str, str] | None = None,
    enabled_providers: set[str] | None = None,
) -> str | None:
    settings = settings or load_integration_settings("llm")
    enabled = enabled_providers or resolve_enabled_llm_providers(settings)
    provider = normalize_provider(settings.get("provider"))
    if provider in enabled:
        return provider
    env_provider = normalize_provider(Config.LLM_PROVIDER)
    if env_provider in enabled:
        return env_provider
    fallback = normalize_provider(default)
    if fallback in enabled:
        return fallback
    return None


def load_integration_settings(provider: str) -> dict[str, str]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == provider
                )
            )
            .scalars()
            .all()
        )
    return {row.key: row.value for row in rows}


def save_integration_settings(provider: str, payload: dict[str, str]) -> None:
    cleaned = {key: (value or "").strip() for key, value in payload.items()}
    with session_scope() as session:
        existing = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == provider
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
                    session, provider=provider, key=key, value=value
                )


def integration_overview() -> dict[str, dict[str, object]]:
    github = load_integration_settings("github")
    jira = load_integration_settings("jira")
    confluence = load_integration_settings("confluence")
    return {
        "github": {
            "connected": bool(github.get("pat")),
            "repo": github.get("repo") or "not set",
        },
        "jira": {
            "connected": bool(jira.get("api_key")),
            "board": jira.get("board") or "not set",
            "project_key": jira.get("project_key") or "not set",
            "site": jira.get("site") or "not set",
        },
        "confluence": {
            "connected": bool(confluence.get("api_key")),
            "space": confluence.get("space") or "not set",
            "site": confluence.get("site") or "not set",
        },
    }
