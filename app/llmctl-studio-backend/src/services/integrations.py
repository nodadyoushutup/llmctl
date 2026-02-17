from __future__ import annotations

import base64
import hashlib
import json
import re

from sqlalchemy import select

from core.config import Config
from core.db import session_scope
from core.models import IntegrationSetting
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]

LLM_PROVIDERS = (
    "codex",
    "gemini",
    "claude",
    "vllm_local",
    "vllm_remote",
)
LLM_PROVIDER_LABELS = {
    "codex": "Codex",
    "gemini": "Gemini",
    "claude": "Claude",
    "vllm_local": "vLLM Local",
    "vllm_remote": "vLLM Remote",
}
DEFAULT_ENABLED_LLM_PROVIDERS = {"codex", "gemini", "claude"}
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
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
    "google_cloud_mcp_enabled",
)
GOOGLE_WORKSPACE_KEYS = (
    "service_account_json",
    "workspace_delegated_user_email",
    "google_workspace_mcp_enabled",
)
NODE_EXECUTOR_PROVIDER = "node_executor"
NODE_EXECUTOR_PROVIDER_KUBERNETES = "kubernetes"
NODE_EXECUTOR_PROVIDER_CHOICES = (
    NODE_EXECUTOR_PROVIDER_KUBERNETES,
)
NODE_EXECUTOR_DISPATCH_STATUS_CHOICES = (
    "dispatch_pending",
    "dispatch_submitted",
    "dispatch_confirmed",
    "dispatch_failed",
)
NODE_EXECUTOR_FALLBACK_REASON_CHOICES = (
    "provider_unavailable",
    "preflight_failed",
    "dispatch_timeout",
    "create_failed",
    "image_pull_failed",
    "config_error",
    "unknown",
)
NODE_EXECUTOR_API_FAILURE_CATEGORY_CHOICES = (
    "socket_missing",
    "socket_unreachable",
    "api_unreachable",
    "auth_error",
    "tls_error",
    "timeout",
    "preflight_failed",
    "unknown",
)
NODE_EXECUTOR_IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
NODE_EXECUTOR_IMAGE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
NODE_EXECUTOR_WORKSPACE_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
NODE_EXECUTOR_PROVIDER_DISPATCH_ID_PATTERN = re.compile(
    r"^(kubernetes):[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}$"
)
NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MIN = 60
NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MAX = 86400
NODE_EXECUTOR_SETTING_KEYS = (
    "provider",
    "dispatch_timeout_seconds",
    "execution_timeout_seconds",
    "log_collection_timeout_seconds",
    "cancel_grace_timeout_seconds",
    "cancel_force_kill_enabled",
    "workspace_identity_key",
    "k8s_namespace",
    "k8s_image",
    "k8s_in_cluster",
    "k8s_service_account",
    "k8s_kubeconfig",
    "k8s_gpu_limit",
    "k8s_job_ttl_seconds",
    "k8s_image_pull_secrets_json",
)
NODE_EXECUTOR_K8S_KUBECONFIG_ENCRYPTED_PREFIX = "enc:v1:"


def normalize_provider(value: str | None) -> str:
    return (value or "").strip().lower()


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _as_bool_flag(value: str | None, *, default: bool = False) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _bool_string(value: bool) -> str:
    return "true" if value else "false"


def _coerce_int_setting(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> str:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        parsed = default
    parsed = max(minimum, min(maximum, parsed))
    return str(parsed)


def _node_executor_secret_cipher() -> Fernet | None:
    if Fernet is None:
        return None
    seed = (Config.SECRET_KEY or "dev").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


def _encrypt_node_executor_secret(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith(NODE_EXECUTOR_K8S_KUBECONFIG_ENCRYPTED_PREFIX):
        return cleaned
    cipher = _node_executor_secret_cipher()
    if cipher is None:
        return cleaned
    token = cipher.encrypt(cleaned.encode("utf-8")).decode("utf-8")
    return NODE_EXECUTOR_K8S_KUBECONFIG_ENCRYPTED_PREFIX + token


def _decrypt_node_executor_secret(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if not cleaned.startswith(NODE_EXECUTOR_K8S_KUBECONFIG_ENCRYPTED_PREFIX):
        return cleaned
    cipher = _node_executor_secret_cipher()
    if cipher is None:
        return ""
    token = cleaned[len(NODE_EXECUTOR_K8S_KUBECONFIG_ENCRYPTED_PREFIX) :]
    try:
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8").strip()
    except (InvalidToken, ValueError):
        return ""


def _parse_port(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = int(raw)
    except ValueError:
        return ""
    if parsed < 1 or parsed > 65535:
        return ""
    return str(parsed)


def _normalize_chroma_target(host: str, port: str) -> tuple[str, str]:
    if host.lower() in DOCKER_CHROMA_HOST_ALIASES and port and port != "8000":
        return "llmctl-chromadb", "8000"
    if host.lower() in DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port
    return host, port


def _parse_option_entries(raw: str | None) -> list[dict[str, str]]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return []
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload:
        value = ""
        label = ""
        if isinstance(item, dict):
            value = (item.get("value") or "").strip()
            label = (item.get("label") or "").strip()
        elif isinstance(item, str):
            value = item.strip()
        if not value or value in seen:
            continue
        options.append({"value": value, "label": label or value})
        seen.add(value)
    options.sort(key=lambda option: option["label"].lower())
    return options


def resolve_enabled_llm_providers(
    settings: dict[str, str] | None = None,
) -> set[str]:
    settings = settings or load_integration_settings("llm")
    enabled_keys = [
        key for key in settings if key.startswith("provider_enabled_")
    ]
    if not enabled_keys:
        return set(DEFAULT_ENABLED_LLM_PROVIDERS)
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


def normalize_node_executor_provider(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in NODE_EXECUTOR_PROVIDER_CHOICES:
        return cleaned
    return NODE_EXECUTOR_PROVIDER_KUBERNETES


def normalize_node_executor_fallback_provider(value: str | None) -> str:
    del value
    return NODE_EXECUTOR_PROVIDER_KUBERNETES


def normalize_workspace_identity_key(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        cleaned = "default"
    if "/" in cleaned or "\\" in cleaned or "://" in cleaned:
        raise ValueError(
            "Workspace identity key must be a stable key, not a filesystem path."
        )
    if not NODE_EXECUTOR_WORKSPACE_IDENTITY_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Workspace identity key must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}."
        )
    return cleaned


def validate_node_executor_image_reference(
    value: str | None,
    *,
    field_name: str,
) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if any(char.isspace() for char in cleaned):
        raise ValueError(
            f"{field_name} is invalid. Spaces are not allowed in image references."
        )

    base = cleaned
    digest = ""
    if "@" in cleaned:
        base, digest = cleaned.rsplit("@", 1)
        if not NODE_EXECUTOR_IMAGE_DIGEST_PATTERN.fullmatch(digest):
            raise ValueError(
                f"{field_name} is invalid. Digest must be sha256:<64hex> when provided."
            )

    if not base:
        raise ValueError(f"{field_name} is invalid. Repository name is required.")

    last_slash = base.rfind("/")
    last_colon = base.rfind(":")
    repo = base
    tag = ""
    if last_colon > last_slash:
        repo = base[:last_colon]
        tag = base[last_colon + 1 :]

    if not repo:
        raise ValueError(f"{field_name} is invalid. Repository name is required.")
    if repo.startswith("/") or repo.endswith("/") or "//" in repo:
        raise ValueError(
            f"{field_name} is invalid. Repository path segments must be non-empty."
        )
    if tag and not NODE_EXECUTOR_IMAGE_TAG_PATTERN.fullmatch(tag):
        raise ValueError(
            f"{field_name} is invalid. Tag format is not supported."
        )

    return cleaned


def normalize_provider_dispatch_id(
    value: str | None,
    *,
    selected_provider: str | None = None,
) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if not NODE_EXECUTOR_PROVIDER_DISPATCH_ID_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "provider_dispatch_id must use kubernetes:<native_id>."
        )
    if selected_provider:
        expected = normalize_node_executor_provider(selected_provider)
        if not cleaned.startswith(f"{expected}:"):
            raise ValueError(
                "provider_dispatch_id provider prefix must match selected_provider."
            )
    return cleaned


def normalize_node_executor_dispatch_status(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in NODE_EXECUTOR_DISPATCH_STATUS_CHOICES:
        return cleaned
    return "dispatch_pending"


def normalize_node_executor_fallback_reason(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in NODE_EXECUTOR_FALLBACK_REASON_CHOICES:
        return cleaned
    return ""


def normalize_node_executor_api_failure_category(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in NODE_EXECUTOR_API_FAILURE_CATEGORY_CHOICES:
        return cleaned
    return ""


def normalize_node_executor_run_metadata(
    payload: dict[str, object] | None,
) -> dict[str, str]:
    payload = payload or {}
    selected_provider = normalize_node_executor_provider(
        str(payload.get("selected_provider") or "")
    )
    final_provider = NODE_EXECUTOR_PROVIDER_KUBERNETES
    dispatch_status = normalize_node_executor_dispatch_status(
        str(payload.get("dispatch_status") or "")
    )
    dispatch_uncertain = _as_bool_flag(
        str(payload.get("dispatch_uncertain") or ""),
        default=False,
    )
    api_failure_category = normalize_node_executor_api_failure_category(
        str(payload.get("api_failure_category") or "")
    )
    workspace_identity = normalize_workspace_identity_key(
        str(payload.get("workspace_identity") or "default")
    )
    provider_dispatch_id = normalize_provider_dispatch_id(
        str(payload.get("provider_dispatch_id") or ""),
        selected_provider=selected_provider,
    )

    if dispatch_status in {"dispatch_submitted", "dispatch_confirmed"} and not provider_dispatch_id:
        raise ValueError(
            "provider_dispatch_id is required when dispatch_status is dispatch_submitted or dispatch_confirmed."
        )

    return {
        "selected_provider": selected_provider,
        "final_provider": final_provider,
        "provider_dispatch_id": provider_dispatch_id,
        "workspace_identity": workspace_identity,
        "dispatch_status": dispatch_status,
        "fallback_attempted": _bool_string(False),
        "fallback_reason": "",
        "dispatch_uncertain": _bool_string(dispatch_uncertain),
        "api_failure_category": api_failure_category,
        "cli_fallback_used": _bool_string(False),
        "cli_preflight_passed": "",
    }


def node_executor_default_settings() -> dict[str, str]:
    return {
        "provider": NODE_EXECUTOR_PROVIDER_KUBERNETES,
        "dispatch_timeout_seconds": _coerce_int_setting(
            str(Config.NODE_EXECUTOR_DISPATCH_TIMEOUT_SECONDS),
            default=300,
            minimum=5,
            maximum=3600,
        ),
        "execution_timeout_seconds": _coerce_int_setting(
            str(Config.NODE_EXECUTOR_EXECUTION_TIMEOUT_SECONDS),
            default=1800,
            minimum=30,
            maximum=86400,
        ),
        "log_collection_timeout_seconds": _coerce_int_setting(
            str(Config.NODE_EXECUTOR_LOG_COLLECTION_TIMEOUT_SECONDS),
            default=30,
            minimum=1,
            maximum=600,
        ),
        "cancel_grace_timeout_seconds": _coerce_int_setting(
            str(Config.NODE_EXECUTOR_CANCEL_GRACE_TIMEOUT_SECONDS),
            default=15,
            minimum=1,
            maximum=300,
        ),
        "cancel_force_kill_enabled": _bool_string(
            Config.NODE_EXECUTOR_CANCEL_FORCE_KILL_ENABLED
        ),
        "workspace_identity_key": normalize_workspace_identity_key(
            Config.NODE_EXECUTOR_WORKSPACE_IDENTITY_KEY
        ),
        "k8s_namespace": (Config.NODE_EXECUTOR_K8S_NAMESPACE or "").strip() or "default",
        "k8s_image": (
            (Config.NODE_EXECUTOR_K8S_IMAGE or "").strip()
            or "llmctl-executor:latest"
        ),
        "k8s_in_cluster": _bool_string(Config.NODE_EXECUTOR_K8S_IN_CLUSTER),
        "k8s_service_account": (
            (Config.NODE_EXECUTOR_K8S_SERVICE_ACCOUNT or "").strip()
        ),
        "k8s_kubeconfig": "",
        "k8s_gpu_limit": _coerce_int_setting(
            str(Config.NODE_EXECUTOR_K8S_GPU_LIMIT),
            default=0,
            minimum=0,
            maximum=8,
        ),
        "k8s_job_ttl_seconds": _coerce_int_setting(
            str(Config.NODE_EXECUTOR_K8S_JOB_TTL_SECONDS),
            default=1800,
            minimum=NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MIN,
            maximum=NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MAX,
        ),
        "k8s_image_pull_secrets_json": (
            (Config.NODE_EXECUTOR_K8S_IMAGE_PULL_SECRETS_JSON or "").strip()
        ),
    }


def ensure_node_executor_setting_defaults(
    defaults: dict[str, str] | None = None,
) -> None:
    provider_key = NODE_EXECUTOR_PROVIDER
    baseline = defaults or node_executor_default_settings()
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
        for key, value in baseline.items():
            cleaned = (value or "").strip()
            if key in existing_keys or not cleaned:
                continue
            IntegrationSetting.create(
                session,
                provider=provider_key,
                key=key,
                value=cleaned,
            )


def migrate_node_executor_to_kubernetes_only_settings() -> dict[str, int]:
    deprecated_keys = (
        "fallback_provider",
        "fallback_enabled",
        "fallback_on_dispatch_error",
        "workspace_root",
        "docker_host",
        "docker_image",
        "docker_network",
        "docker_pull_policy",
        "docker_env_json",
        "docker_api_stall_seconds",
    )
    settings = load_node_executor_settings(include_secrets=True)
    save_node_executor_settings(settings)
    stored = load_integration_settings(NODE_EXECUTOR_PROVIDER)
    cleanup_payload: dict[str, str] = {}
    removed = 0
    for key in deprecated_keys:
        if key in stored:
            cleanup_payload[key] = ""
            removed += 1
    if cleanup_payload:
        save_integration_settings(NODE_EXECUTOR_PROVIDER, cleanup_payload)
    return {
        "provider_forced": 1,
        "deprecated_keys_removed": removed,
    }


def load_node_executor_settings(*, include_secrets: bool = False) -> dict[str, str]:
    defaults = node_executor_default_settings()
    try:
        ensure_node_executor_setting_defaults(defaults)
    except Exception:
        pass
    stored = load_integration_settings(NODE_EXECUTOR_PROVIDER)
    kubeconfig_updated_at = ""
    with session_scope() as session:
        kubeconfig_row = (
            session.execute(
                select(IntegrationSetting).where(
                    IntegrationSetting.provider == NODE_EXECUTOR_PROVIDER,
                    IntegrationSetting.key == "k8s_kubeconfig",
                )
            )
            .scalars()
            .first()
        )
    if kubeconfig_row is not None and kubeconfig_row.updated_at is not None:
        kubeconfig_updated_at = kubeconfig_row.updated_at.isoformat()
    stored["k8s_kubeconfig"] = _decrypt_node_executor_secret(
        stored.get("k8s_kubeconfig")
    )
    settings = {**defaults, **stored}
    settings["provider"] = NODE_EXECUTOR_PROVIDER_KUBERNETES
    settings["dispatch_timeout_seconds"] = _coerce_int_setting(
        settings.get("dispatch_timeout_seconds"),
        default=int(defaults["dispatch_timeout_seconds"]),
        minimum=5,
        maximum=3600,
    )
    settings["execution_timeout_seconds"] = _coerce_int_setting(
        settings.get("execution_timeout_seconds"),
        default=int(defaults["execution_timeout_seconds"]),
        minimum=30,
        maximum=86400,
    )
    settings["log_collection_timeout_seconds"] = _coerce_int_setting(
        settings.get("log_collection_timeout_seconds"),
        default=int(defaults["log_collection_timeout_seconds"]),
        minimum=1,
        maximum=600,
    )
    settings["cancel_grace_timeout_seconds"] = _coerce_int_setting(
        settings.get("cancel_grace_timeout_seconds"),
        default=int(defaults["cancel_grace_timeout_seconds"]),
        minimum=1,
        maximum=300,
    )
    settings["cancel_force_kill_enabled"] = _bool_string(
        _as_bool_flag(settings.get("cancel_force_kill_enabled"), default=True)
    )
    try:
        settings["workspace_identity_key"] = normalize_workspace_identity_key(
            settings.get("workspace_identity_key")
        )
    except ValueError:
        settings["workspace_identity_key"] = defaults["workspace_identity_key"]
    settings["k8s_namespace"] = (
        (settings.get("k8s_namespace") or "").strip() or defaults["k8s_namespace"]
    )
    try:
        settings["k8s_image"] = validate_node_executor_image_reference(
            settings.get("k8s_image"),
            field_name="Kubernetes image",
        ) or defaults["k8s_image"]
    except ValueError:
        settings["k8s_image"] = defaults["k8s_image"]
    settings["k8s_in_cluster"] = _bool_string(
        _as_bool_flag(settings.get("k8s_in_cluster"), default=False)
    )
    settings["k8s_service_account"] = (
        settings.get("k8s_service_account") or ""
    ).strip()
    settings["k8s_gpu_limit"] = _coerce_int_setting(
        settings.get("k8s_gpu_limit"),
        default=int(defaults["k8s_gpu_limit"]),
        minimum=0,
        maximum=8,
    )
    settings["k8s_job_ttl_seconds"] = _coerce_int_setting(
        settings.get("k8s_job_ttl_seconds"),
        default=int(defaults["k8s_job_ttl_seconds"]),
        minimum=NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MIN,
        maximum=NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MAX,
    )
    kubeconfig_value = (settings.get("k8s_kubeconfig") or "").strip()
    kubeconfig_fingerprint = ""
    if kubeconfig_value:
        kubeconfig_fingerprint = (
            "sha256:"
            + hashlib.sha256(kubeconfig_value.encode("utf-8")).hexdigest()[:12]
        )
    settings["k8s_kubeconfig_is_set"] = "true" if bool(kubeconfig_value) else "false"
    settings["k8s_kubeconfig_fingerprint"] = kubeconfig_fingerprint
    settings["k8s_kubeconfig_updated_at"] = kubeconfig_updated_at
    settings["k8s_kubeconfig"] = kubeconfig_value if include_secrets else ""
    settings["k8s_image_pull_secrets_json"] = (
        settings.get("k8s_image_pull_secrets_json") or ""
    ).strip()
    return settings


def save_node_executor_settings(payload: dict[str, str]) -> dict[str, str]:
    provider_raw = (payload.get("provider") or "").strip().lower()
    if provider_raw and provider_raw != NODE_EXECUTOR_PROVIDER_KUBERNETES:
        raise ValueError("Node executor provider must be kubernetes.")
    current = load_node_executor_settings(include_secrets=True)
    candidate = dict(current)
    for key in NODE_EXECUTOR_SETTING_KEYS:
        if key not in payload:
            continue
        candidate[key] = (payload.get(key) or "").strip()

    validated: dict[str, str] = {
        "provider": NODE_EXECUTOR_PROVIDER_KUBERNETES,
        "dispatch_timeout_seconds": _coerce_int_setting(
            candidate.get("dispatch_timeout_seconds"),
            default=300,
            minimum=5,
            maximum=3600,
        ),
        "execution_timeout_seconds": _coerce_int_setting(
            candidate.get("execution_timeout_seconds"),
            default=1800,
            minimum=30,
            maximum=86400,
        ),
        "log_collection_timeout_seconds": _coerce_int_setting(
            candidate.get("log_collection_timeout_seconds"),
            default=30,
            minimum=1,
            maximum=600,
        ),
        "cancel_grace_timeout_seconds": _coerce_int_setting(
            candidate.get("cancel_grace_timeout_seconds"),
            default=15,
            minimum=1,
            maximum=300,
        ),
        "cancel_force_kill_enabled": _bool_string(
            _as_bool_flag(candidate.get("cancel_force_kill_enabled"), default=True)
        ),
        "workspace_identity_key": normalize_workspace_identity_key(
            candidate.get("workspace_identity_key")
        ),
        "k8s_namespace": (
            (candidate.get("k8s_namespace") or "").strip() or "default"
        ),
        "k8s_image": validate_node_executor_image_reference(
            candidate.get("k8s_image"),
            field_name="Kubernetes image",
        ) or "llmctl-executor:latest",
        "k8s_in_cluster": _bool_string(
            _as_bool_flag(candidate.get("k8s_in_cluster"), default=False)
        ),
        "k8s_service_account": (candidate.get("k8s_service_account") or "").strip(),
        "k8s_kubeconfig": _encrypt_node_executor_secret(
            candidate.get("k8s_kubeconfig")
        ),
        "k8s_gpu_limit": _coerce_int_setting(
            candidate.get("k8s_gpu_limit"),
            default=0,
            minimum=0,
            maximum=8,
        ),
        "k8s_job_ttl_seconds": _coerce_int_setting(
            candidate.get("k8s_job_ttl_seconds"),
            default=1800,
            minimum=NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MIN,
            maximum=NODE_EXECUTOR_K8S_JOB_TTL_SECONDS_MAX,
        ),
        "k8s_image_pull_secrets_json": (
            candidate.get("k8s_image_pull_secrets_json") or ""
        ).strip(),
    }
    image_pull_secrets_json = (validated.get("k8s_image_pull_secrets_json") or "").strip()
    if image_pull_secrets_json:
        try:
            pull_secrets_payload = json.loads(image_pull_secrets_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Kubernetes image pull secrets JSON is invalid: {exc.msg}."
            ) from exc
        if not isinstance(pull_secrets_payload, list):
            raise ValueError("Kubernetes image pull secrets JSON must be an array.")

    save_integration_settings(NODE_EXECUTOR_PROVIDER, validated)
    return validated


def node_executor_effective_config_summary() -> dict[str, str]:
    settings = load_node_executor_settings(include_secrets=False)
    return {
        "provider": settings.get("provider") or NODE_EXECUTOR_PROVIDER_KUBERNETES,
        "dispatch_timeout_seconds": settings.get("dispatch_timeout_seconds") or "300",
        "execution_timeout_seconds": settings.get("execution_timeout_seconds") or "1800",
        "log_collection_timeout_seconds": settings.get("log_collection_timeout_seconds")
        or "30",
        "cancel_grace_timeout_seconds": settings.get("cancel_grace_timeout_seconds")
        or "15",
        "cancel_force_kill_enabled": settings.get("cancel_force_kill_enabled") or "true",
        "workspace_identity_key": settings.get("workspace_identity_key") or "default",
        "k8s_namespace": settings.get("k8s_namespace") or "default",
        "k8s_image": settings.get("k8s_image") or "llmctl-executor:latest",
        "k8s_in_cluster": settings.get("k8s_in_cluster") or "false",
        "k8s_service_account": settings.get("k8s_service_account") or "",
        "k8s_gpu_limit": settings.get("k8s_gpu_limit") or "0",
        "k8s_job_ttl_seconds": settings.get("k8s_job_ttl_seconds") or "1800",
        "k8s_kubeconfig_is_set": settings.get("k8s_kubeconfig_is_set") or "false",
        "k8s_kubeconfig_fingerprint": settings.get("k8s_kubeconfig_fingerprint")
        or "",
        "k8s_kubeconfig_updated_at": settings.get("k8s_kubeconfig_updated_at") or "",
        "k8s_image_pull_secrets_json": settings.get("k8s_image_pull_secrets_json") or "",
    }


def load_node_executor_runtime_settings() -> dict[str, str]:
    # Runtime-only accessor: includes sensitive kubeconfig for internal executor paths.
    settings = load_node_executor_settings(include_secrets=True)
    return {
        "provider": settings.get("provider") or NODE_EXECUTOR_PROVIDER_KUBERNETES,
        "dispatch_timeout_seconds": settings.get("dispatch_timeout_seconds") or "300",
        "execution_timeout_seconds": settings.get("execution_timeout_seconds") or "1800",
        "log_collection_timeout_seconds": settings.get("log_collection_timeout_seconds")
        or "30",
        "cancel_grace_timeout_seconds": settings.get("cancel_grace_timeout_seconds")
        or "15",
        "cancel_force_kill_enabled": settings.get("cancel_force_kill_enabled") or "true",
        "workspace_identity_key": settings.get("workspace_identity_key") or "default",
        "k8s_namespace": settings.get("k8s_namespace") or "default",
        "k8s_image": settings.get("k8s_image") or "llmctl-executor:latest",
        "k8s_in_cluster": settings.get("k8s_in_cluster") or "false",
        "k8s_service_account": settings.get("k8s_service_account") or "",
        "k8s_kubeconfig": settings.get("k8s_kubeconfig") or "",
        "k8s_gpu_limit": settings.get("k8s_gpu_limit") or "0",
        "k8s_job_ttl_seconds": settings.get("k8s_job_ttl_seconds") or "1800",
        "k8s_image_pull_secrets_json": settings.get("k8s_image_pull_secrets_json") or "",
    }


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
    provider_key = normalize_provider(provider)
    if not provider_key:
        return {}
    if provider_key in GOOGLE_PROVIDER_SET:
        migrate_legacy_google_integration_settings()
    if provider_key == GOOGLE_DRIVE_LEGACY_PROVIDER:
        provider_key = GOOGLE_WORKSPACE_PROVIDER
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


def migrate_legacy_google_integration_settings() -> bool:
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

        # Legacy Google Drive credentials previously backed both Cloud and Drive flows.
        # Ensure both split providers get a baseline service account when absent.
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


def integration_overview() -> dict[str, dict[str, object]]:
    migrate_legacy_google_integration_settings()
    github = load_integration_settings("github")
    jira = load_integration_settings("jira")
    confluence = load_integration_settings("confluence")
    google_cloud = load_integration_settings(GOOGLE_CLOUD_PROVIDER)
    google_workspace = load_integration_settings(GOOGLE_WORKSPACE_PROVIDER)
    chroma = load_integration_settings("chroma")
    google_cloud_mcp_enabled_raw = (
        google_cloud.get("google_cloud_mcp_enabled") or "true"
    ).strip().lower()
    google_cloud_mcp_enabled = google_cloud_mcp_enabled_raw in {
        "1",
        "true",
        "yes",
        "on",
    }
    google_workspace_mcp_enabled_raw = (
        google_workspace.get("google_workspace_mcp_enabled") or "false"
    ).strip().lower()
    google_workspace_mcp_enabled = google_workspace_mcp_enabled_raw in {
        "1",
        "true",
        "yes",
        "on",
    }
    google_cloud_project = (google_cloud.get("google_cloud_project_id") or "").strip()
    google_workspace_delegated_user = (
        google_workspace.get("workspace_delegated_user_email") or ""
    ).strip()
    chroma_host = (chroma.get("host") or "").strip() or (Config.CHROMA_HOST or "").strip()
    chroma_port = _parse_port(chroma.get("port")) or _parse_port(Config.CHROMA_PORT)
    chroma_host, chroma_port = _normalize_chroma_target(chroma_host, chroma_port)
    chroma_ssl_raw = (chroma.get("ssl") or "").strip() or Config.CHROMA_SSL
    confluence_spaces = _parse_option_entries(confluence.get("space_options"))
    selected_space = (confluence.get("space") or "").strip()
    if selected_space and all(
        option.get("value") != selected_space for option in confluence_spaces
    ):
        confluence_spaces.insert(
            0, {"value": selected_space, "label": selected_space}
        )
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
            "spaces": confluence_spaces,
        },
        "google_cloud": {
            "connected": bool((google_cloud.get("service_account_json") or "").strip()),
            "project_id": google_cloud_project or "not set",
            "mcp_enabled": google_cloud_mcp_enabled,
        },
        "google_workspace": {
            "connected": bool((google_workspace.get("service_account_json") or "").strip()),
            "delegated_user": google_workspace_delegated_user or "not set",
            "mcp_enabled": google_workspace_mcp_enabled,
            "mcp_guarded": True,
        },
        "chroma": {
            "connected": bool(chroma_host and chroma_port),
            "host": chroma_host or "not set",
            "port": chroma_port or "not set",
            "ssl": "enabled"
            if chroma_ssl_raw.strip().lower() == "true"
            else "disabled",
        },
    }
