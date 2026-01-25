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


def resolve_llm_provider(default: str | None = None) -> str:
    settings = load_integration_settings("llm")
    provider = normalize_provider(settings.get("provider"))
    if provider in LLM_PROVIDERS:
        return provider
    env_provider = normalize_provider(Config.LLM_PROVIDER)
    if env_provider in LLM_PROVIDERS:
        return env_provider
    fallback = normalize_provider(default)
    if fallback in LLM_PROVIDERS:
        return fallback
    return "codex"


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
