from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import re
from pathlib import Path
import os
import shutil

_DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "data",
    "dist",
    "node_modules",
    "out",
    "target",
    "venv",
}

_DEFAULT_EXCLUDE_GLOBS = [
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.tgz",
    "*.lock",
    "*.mp4",
    "*.mov",
    "*.sqlite",
    "*.db",
    "*.bin",
]

_DEFAULT_MAX_FILE_BYTES_BY_TYPE = {
    "pdf": 1_000_000_000,
}
_DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
_SUPPORTED_MODEL_PROVIDERS = {"openai", "gemini"}
_SUPPORTED_CHAT_RESPONSE_STYLES = {"low", "medium", "high"}
_CHAT_RESPONSE_STYLE_ALIASES = {
    "concise": "low",
    "brief": "low",
    "balanced": "medium",
    "detailed": "high",
    "verbose": "high",
}


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_map_list(value: str | None) -> dict[str, list[str]]:
    if not value:
        return {}
    result: dict[str, list[str]] = {}
    for pair in value.split(";"):
        if not pair.strip():
            continue
        if "=" not in pair:
            continue
        key, raw = pair.split("=", 1)
        key = key.strip().lower()
        if not key:
            continue
        parts = [item.strip() for item in re.split(r"[|,]", raw) if item.strip()]
        if parts:
            result[key] = parts
    return result


def _split_map_int(value: str | None) -> dict[str, int]:
    if not value:
        return {}
    result: dict[str, int] = {}
    for pair in value.split(";"):
        if not pair.strip():
            continue
        if "=" not in pair:
            continue
        key, raw = pair.split("=", 1)
        key = key.strip().lower()
        raw = raw.strip()
        if not key or not raw:
            continue
        try:
            result[key] = int(raw)
        except ValueError:
            continue
    return result


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / ".git").exists():
            return parent
    # Fallback to repo root estimate from app/llmctl-studio-backend/src/rag/engine.
    return here.parents[2]


@dataclass(frozen=True)
class RagConfig:
    repo_root: Path
    rag_mode: str
    chroma_host: str
    chroma_port: int
    collection: str
    embed_provider: str
    chat_provider: str
    openai_api_key: str | None
    gemini_api_key: str | None
    openai_embedding_model: str
    gemini_embedding_model: str
    embed_model: str
    embed_max_tokens_per_request: int
    embed_max_tokens_per_input: int
    embed_max_batch_items: int
    embed_min_request_interval_s: float
    embed_target_tokens_per_minute: int
    embed_rate_limit_max_retries: int
    git_url: str | None
    git_repo: str | None
    git_pat: str | None
    git_ssh_key_path: str | None
    git_branch: str
    git_poll_s: float
    git_dir: Path
    watch_enabled: bool
    watch_debounce_s: float
    chunk_lines: int
    chunk_overlap_lines: int
    max_file_bytes: int
    exclude_dirs: set[str]
    exclude_globs: list[str]
    include_globs: list[str]
    max_file_bytes_by_type: dict[str, int]
    exclude_globs_by_type: dict[str, list[str]]
    chunk_lines_by_type: dict[str, int]
    chunk_overlap_lines_by_type: dict[str, int]
    enabled_doc_types: set[str]
    ocr_enabled: bool
    ocr_lang: str
    ocr_dpi: int
    ocr_timeout_s: int
    ocr_include_char_boxes: bool
    drive_sync_workers: int
    index_parallel_workers: int
    pdf_page_workers: int
    embed_parallel_requests: int
    openai_chat_model: str
    gemini_chat_model: str
    chat_model: str
    chat_response_style: str
    chat_temperature: float
    chat_top_k: int
    chat_max_history: int
    chat_max_context_chars: int
    chat_snippet_chars: int
    chat_context_budget_tokens: int
    web_port: int


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_int_range(
    value: str | None,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    parsed = _as_int(value, default)
    if minimum is not None and parsed < minimum:
        return minimum
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def _normalize_chroma_target(host: str, port: int) -> tuple[str, int]:
    host_value = (host or "").strip()
    if host_value.lower() in _DOCKER_CHROMA_HOST_ALIASES and port != 8000:
        return "llmctl-chromadb", 8000
    if host_value.lower() in _DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port
    return host_value, port


def _parse_chroma_port(raw: str | None, default: int) -> int:
    value = _as_int(raw, default)
    if 1 <= value <= 65535:
        return value
    return default


def _setting(
    env_key: str,
    rag_settings: dict[str, str],
    rag_key: str,
    default: str | None = None,
) -> str | None:
    env_value = (os.getenv(env_key) or "").strip()
    if env_value:
        return env_value
    rag_value = (rag_settings.get(rag_key) or "").strip()
    if rag_value:
        return rag_value
    return default


def _setting_rag_first(
    env_key: str,
    rag_settings: dict[str, str],
    rag_key: str,
    default: str | None = None,
) -> str | None:
    rag_value = (rag_settings.get(rag_key) or "").strip()
    if rag_value:
        return rag_value
    env_value = (os.getenv(env_key) or "").strip()
    if env_value:
        return env_value
    return default


def _normalize_provider(value: str | None, default: str = "openai") -> str:
    candidate = (value or "").strip().lower()
    if candidate in _SUPPORTED_MODEL_PROVIDERS:
        return candidate
    return default


def _normalize_chat_response_style(value: str | None, default: str = "high") -> str:
    candidate = (value or "").strip().lower()
    candidate = _CHAT_RESPONSE_STYLE_ALIASES.get(candidate, candidate)
    if candidate in _SUPPORTED_CHAT_RESPONSE_STYLES:
        return candidate
    return default


def build_git_url(
    repo: str | None, pat: str | None, ssh_key_path: str | None
) -> str | None:
    repo_value = (repo or "").strip()
    if not repo_value:
        return None
    ssh_key_value = (ssh_key_path or "").strip()
    if ssh_key_value and shutil.which("ssh"):
        return f"git@github.com:{repo_value}.git"
    pat_value = (pat or "").strip()
    if pat_value:
        return f"https://x-access-token:{pat_value}@github.com/{repo_value}.git"
    return f"https://github.com/{repo_value}.git"


def max_file_bytes_for(config: RagConfig, doc_type: str | None) -> int:
    if not doc_type:
        return config.max_file_bytes
    return config.max_file_bytes_by_type.get(doc_type, config.max_file_bytes)


def chunk_lines_for(config: RagConfig, doc_type: str | None) -> int:
    if not doc_type:
        return config.chunk_lines
    return config.chunk_lines_by_type.get(doc_type, config.chunk_lines)


def chunk_overlap_lines_for(config: RagConfig, doc_type: str | None) -> int:
    if not doc_type:
        return config.chunk_overlap_lines
    return config.chunk_overlap_lines_by_type.get(doc_type, config.chunk_overlap_lines)


def _signature_payload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parser_signature(config: RagConfig, version: str) -> str:
    payload = {
        "version": version,
        "max_file_bytes_by_type": config.max_file_bytes_by_type,
        "exclude_globs_by_type": config.exclude_globs_by_type,
        "enabled_doc_types": sorted(config.enabled_doc_types),
        "ocr_enabled": config.ocr_enabled,
        "ocr_lang": config.ocr_lang,
        "ocr_dpi": config.ocr_dpi,
        "ocr_timeout_s": config.ocr_timeout_s,
        "ocr_include_char_boxes": config.ocr_include_char_boxes,
    }
    return _signature_payload(payload)


def chunker_signature(config: RagConfig, version: str) -> str:
    payload = {
        "version": version,
        "chunk_lines": config.chunk_lines,
        "chunk_overlap_lines": config.chunk_overlap_lines,
        "chunk_lines_by_type": config.chunk_lines_by_type,
        "chunk_overlap_lines_by_type": config.chunk_overlap_lines_by_type,
    }
    return _signature_payload(payload)


def load_config() -> RagConfig:
    rag_settings = {}
    github_settings = {}
    chroma_settings = {}
    llm_settings = {}
    try:
        from rag.repositories.settings import load_rag_settings

        rag_settings = load_rag_settings("rag")
    except Exception:
        rag_settings = {}
    try:
        from services.integrations import load_integration_settings

        github_settings = load_integration_settings("github")
        chroma_settings = load_integration_settings("chroma")
        llm_settings = load_integration_settings("llm")
    except Exception:
        github_settings = {}
        chroma_settings = {}
        llm_settings = {}

    local_root = _setting("RAG_ROOT", rag_settings, "local_path", None)
    repo_root = (
        Path(local_root).expanduser().resolve()
        if local_root
        else _find_repo_root()
    )

    rag_mode = (
        _setting("RAG_MODE", rag_settings, "mode", "local") or "local"
    ).strip().lower()
    git_dir_raw = _setting(
        "RAG_GIT_DIR", rag_settings, "git_dir", "/tmp/llmctl-studio-rag-repo"
    ) or "/tmp/llmctl-studio-rag-repo"
    git_dir = Path(git_dir_raw).expanduser().resolve()
    if rag_mode == "git":
        repo_root = git_dir

    git_repo = (github_settings.get("repo") or "").strip() or None
    git_pat = (github_settings.get("pat") or "").strip() or None
    git_ssh_key_path = (github_settings.get("ssh_key_path") or "").strip() or None
    git_url = _setting("RAG_GIT_URL", rag_settings, "git_url", None)
    if not git_url:
        git_url = build_git_url(git_repo, git_pat, git_ssh_key_path)

    exclude_dirs = set(_DEFAULT_EXCLUDE_DIRS)
    exclude_dirs.update(
        _split_csv(_setting("RAG_EXCLUDE_DIRS", rag_settings, "exclude_dirs", None))
    )

    exclude_globs = list(_DEFAULT_EXCLUDE_GLOBS)
    exclude_globs.extend(
        _split_csv(_setting("RAG_EXCLUDE_GLOBS", rag_settings, "exclude_globs", None))
    )

    include_globs = _split_csv(
        _setting("RAG_INCLUDE_GLOBS", rag_settings, "include_globs", None)
    )
    max_file_bytes_by_type = _split_map_int(
        _setting(
            "RAG_MAX_FILE_BYTES_BY_TYPE",
            rag_settings,
            "max_file_bytes_by_type",
            None,
        )
    )
    exclude_globs_by_type = _split_map_list(
        _setting(
            "RAG_EXCLUDE_GLOBS_BY_TYPE",
            rag_settings,
            "exclude_globs_by_type",
            None,
        )
    )
    chunk_lines_by_type = _split_map_int(
        _setting("RAG_CHUNK_LINES_BY_TYPE", rag_settings, "chunk_lines_by_type", None)
    )
    chunk_overlap_lines_by_type = _split_map_int(
        _setting(
            "RAG_CHUNK_OVERLAP_LINES_BY_TYPE",
            rag_settings,
            "chunk_overlap_lines_by_type",
            None,
        )
    )
    enabled_doc_types = {
        item.lower()
        for item in _split_csv(
            _setting("RAG_ENABLED_DOC_TYPES", rag_settings, "enabled_doc_types", None)
        )
    }
    ocr_enabled_raw = _setting("RAG_OCR_ENABLED", rag_settings, "ocr_enabled", "true")
    ocr_enabled = (ocr_enabled_raw or "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    ocr_lang = _setting("RAG_OCR_LANG", rag_settings, "ocr_lang", "eng") or "eng"
    ocr_dpi = max(
        72,
        _as_int(
            _setting("RAG_OCR_DPI", rag_settings, "ocr_dpi", "150"),
            150,
        ),
    )
    ocr_timeout_s = max(
        0,
        _as_int(
            _setting("RAG_OCR_TIMEOUT_S", rag_settings, "ocr_timeout_s", "45"),
            45,
        ),
    )
    ocr_include_char_boxes = _as_bool(
        _setting(
            "RAG_OCR_INCLUDE_CHAR_BOXES",
            rag_settings,
            "ocr_include_char_boxes",
            "false",
        ),
        False,
    )

    embed_provider = _normalize_provider(
        _setting_rag_first(
            "RAG_EMBED_PROVIDER", rag_settings, "embed_provider", "openai"
        ),
        "openai",
    )
    chat_provider = _normalize_provider(
        _setting_rag_first(
            "RAG_CHAT_PROVIDER", rag_settings, "chat_provider", "openai"
        ),
        "openai",
    )

    # RAG runtime auth is sourced from Provider settings first.
    openai_api_key = (
        (llm_settings.get("codex_api_key") or "").strip()
        or (os.getenv("OPENAI_API_KEY") or "").strip()
        or None
    )
    gemini_api_key = (
        (llm_settings.get("gemini_api_key") or "").strip()
        or (os.getenv("GEMINI_API_KEY") or "").strip()
        or None
    )
    if not gemini_api_key:
        gemini_api_key = (os.getenv("GOOGLE_API_KEY") or "").strip() or None

    openai_embedding_model = (
        _setting_rag_first(
            "OPENAI_EMBED_MODEL",
            rag_settings,
            "openai_embed_model",
            "text-embedding-3-small",
        )
        or "text-embedding-3-small"
    )
    gemini_embedding_model = (
        _setting_rag_first(
            "GEMINI_EMBED_MODEL",
            rag_settings,
            "gemini_embed_model",
            "models/gemini-embedding-001",
        )
        or "models/gemini-embedding-001"
    )
    embed_model = (
        gemini_embedding_model
        if embed_provider == "gemini"
        else openai_embedding_model
    )

    openai_chat_model = (
        _setting_rag_first(
            "OPENAI_CHAT_MODEL", rag_settings, "openai_chat_model", "gpt-4o-mini"
        )
        or "gpt-4o-mini"
    )
    gemini_chat_model = (
        _setting_rag_first(
            "GEMINI_CHAT_MODEL",
            rag_settings,
            "gemini_chat_model",
            "gemini-2.5-flash",
        )
        or "gemini-2.5-flash"
    )
    chat_model = gemini_chat_model if chat_provider == "gemini" else openai_chat_model
    chat_response_style = _normalize_chat_response_style(
        _setting_rag_first(
            "RAG_CHAT_RESPONSE_STYLE",
            rag_settings,
            "chat_response_style",
            "high",
        ),
        "high",
    )

    chat_temperature_raw = _setting_rag_first(
        "RAG_CHAT_TEMPERATURE",
        rag_settings,
        "chat_temperature",
        None,
    )
    if chat_temperature_raw is None:
        chat_temperature_raw = _setting_rag_first(
            "OPENAI_CHAT_TEMPERATURE",
            rag_settings,
            "openai_chat_temperature",
            None,
        )

    chroma_host = (
        (chroma_settings.get("host") or "").strip()
        or (os.getenv("CHROMA_HOST") or "").strip()
        or (rag_settings.get("chroma_host") or "").strip()
        or "llmctl-chromadb"
    )
    chroma_port = _parse_chroma_port(
        (chroma_settings.get("port") or "").strip()
        or (os.getenv("CHROMA_PORT") or "").strip()
        or (rag_settings.get("chroma_port") or "").strip(),
        8000,
    )
    chroma_host, chroma_port = _normalize_chroma_target(chroma_host, chroma_port)

    return RagConfig(
        repo_root=repo_root,
        rag_mode=rag_mode,
        chroma_host=chroma_host,
        chroma_port=chroma_port,
        collection=_setting(
            "CHROMA_COLLECTION", rag_settings, "chroma_collection", "llmctl_repo"
        )
        or "llmctl_repo",
        embed_provider=embed_provider,
        chat_provider=chat_provider,
        openai_api_key=openai_api_key,
        gemini_api_key=gemini_api_key,
        openai_embedding_model=openai_embedding_model,
        gemini_embedding_model=gemini_embedding_model,
        embed_model=embed_model,
        embed_max_tokens_per_request=_as_int_range(
            _setting(
                "RAG_EMBED_MAX_TOKENS_PER_REQUEST",
                rag_settings,
                "embed_max_tokens_per_request",
                "300000",
            ),
            300000,
            minimum=1,
        ),
        embed_max_tokens_per_input=_as_int_range(
            _setting(
                "RAG_EMBED_MAX_TOKENS_PER_INPUT",
                rag_settings,
                "embed_max_tokens_per_input",
                "8192",
            ),
            8192,
            minimum=1,
        ),
        embed_max_batch_items=_as_int(
            _setting(
                "RAG_EMBED_MAX_BATCH_ITEMS",
                rag_settings,
                "embed_max_batch_items",
                "100",
            ),
            100,
        ),
        embed_min_request_interval_s=_as_float(
            _setting(
                "RAG_EMBED_MIN_REQUEST_INTERVAL_S",
                rag_settings,
                "embed_min_request_interval_s",
                "0",
            ),
            0.0,
        ),
        embed_target_tokens_per_minute=_as_int(
            _setting(
                "RAG_EMBED_TARGET_TOKENS_PER_MINUTE",
                rag_settings,
                "embed_target_tokens_per_minute",
                "0",
            ),
            0,
        ),
        embed_rate_limit_max_retries=_as_int(
            _setting(
                "RAG_EMBED_RATE_LIMIT_MAX_RETRIES",
                rag_settings,
                "embed_rate_limit_max_retries",
                "6",
            ),
            6,
        ),
        git_url=git_url,
        git_repo=git_repo,
        git_pat=git_pat,
        git_ssh_key_path=git_ssh_key_path,
        git_branch=_setting("RAG_GIT_BRANCH", rag_settings, "git_branch", "main")
        or "main",
        git_poll_s=_as_float(
            _setting("RAG_GIT_POLL_S", rag_settings, "git_poll_s", None), 300.0
        ),
        git_dir=git_dir,
        watch_enabled=_as_bool(
            _setting("RAG_WATCH_ENABLED", rag_settings, "watch_enabled", None),
            _as_bool(rag_settings.get("watch_enabled"), True),
        ),
        watch_debounce_s=_as_float(
            _setting("RAG_WATCH_DEBOUNCE_S", rag_settings, "watch_debounce_s", None),
            1.0,
        ),
        chunk_lines=_as_int_range(
            _setting("RAG_CHUNK_LINES", rag_settings, "chunk_lines", "120"),
            120,
            minimum=1,
        ),
        chunk_overlap_lines=_as_int_range(
            _setting("RAG_CHUNK_OVERLAP_LINES", rag_settings, "chunk_overlap_lines", "20"),
            20,
            minimum=0,
        ),
        max_file_bytes=_as_int_range(
            _setting(
                "RAG_MAX_FILE_BYTES", rag_settings, "max_file_bytes", str(1_000_000)
            ),
            1_000_000,
            minimum=1,
        ),
        exclude_dirs=exclude_dirs,
        exclude_globs=exclude_globs,
        include_globs=include_globs,
        max_file_bytes_by_type={
            **_DEFAULT_MAX_FILE_BYTES_BY_TYPE,
            **max_file_bytes_by_type,
        },
        exclude_globs_by_type=exclude_globs_by_type,
        chunk_lines_by_type=chunk_lines_by_type,
        chunk_overlap_lines_by_type=chunk_overlap_lines_by_type,
        enabled_doc_types=enabled_doc_types,
        ocr_enabled=ocr_enabled,
        ocr_lang=ocr_lang,
        ocr_dpi=ocr_dpi,
        ocr_timeout_s=ocr_timeout_s,
        ocr_include_char_boxes=ocr_include_char_boxes,
        drive_sync_workers=max(
            1,
            _as_int(
                _setting(
                    "RAG_DRIVE_SYNC_WORKERS",
                    rag_settings,
                    "drive_sync_workers",
                    "4",
                ),
                4,
            ),
        ),
        index_parallel_workers=max(
            1,
            _as_int(
                _setting(
                    "RAG_INDEX_PARALLEL_WORKERS",
                    rag_settings,
                    "index_parallel_workers",
                    "1",
                ),
                1,
            ),
        ),
        pdf_page_workers=max(
            1,
            _as_int(
                _setting(
                    "RAG_PDF_PAGE_WORKERS",
                    rag_settings,
                    "pdf_page_workers",
                    "1",
                ),
                1,
            ),
        ),
        embed_parallel_requests=max(
            1,
            _as_int(
                _setting(
                    "RAG_EMBED_PARALLEL_REQUESTS",
                    rag_settings,
                    "embed_parallel_requests",
                    _setting(
                        "CELERY_WORKER_CONCURRENCY",
                        rag_settings,
                        "celery_worker_concurrency",
                        "6",
                    )
                    or "6",
                ),
                6,
            ),
        ),
        openai_chat_model=openai_chat_model,
        gemini_chat_model=gemini_chat_model,
        chat_model=chat_model,
        chat_response_style=chat_response_style,
        chat_temperature=_as_float(chat_temperature_raw, 0.2),
        chat_top_k=_as_int_range(
            _setting("RAG_CHAT_TOP_K", rag_settings, "chat_top_k", "5"),
            5,
            minimum=1,
            maximum=20,
        ),
        chat_max_history=_as_int_range(
            _setting("RAG_CHAT_MAX_HISTORY", rag_settings, "chat_max_history", "8"),
            8,
            minimum=1,
            maximum=50,
        ),
        chat_max_context_chars=_as_int_range(
            _setting(
                "RAG_CHAT_MAX_CONTEXT_CHARS",
                rag_settings,
                "chat_max_context_chars",
                "12000",
            ),
            12000,
            minimum=1000,
        ),
        chat_snippet_chars=_as_int_range(
            _setting(
                "RAG_CHAT_SNIPPET_CHARS",
                rag_settings,
                "chat_snippet_chars",
                "600",
            ),
            600,
            minimum=100,
        ),
        chat_context_budget_tokens=_as_int_range(
            _setting(
                "RAG_CHAT_CONTEXT_BUDGET_TOKENS",
                rag_settings,
                "chat_context_budget_tokens",
                "8000",
            ),
            8000,
            minimum=256,
        ),
        web_port=_as_int_range(
            _setting("RAG_WEB_PORT", rag_settings, "web_port", "5050"),
            5050,
            minimum=1,
            maximum=65535,
        ),
    )


def build_source_config(base: RagConfig, source, github_settings: dict[str, str]) -> RagConfig:
    kind = (getattr(source, "kind", "") or "").strip().lower()
    rag_mode = base.rag_mode
    repo_root = base.repo_root
    git_url = base.git_url
    git_dir = base.git_dir
    git_branch = base.git_branch
    git_repo = None
    git_pat = (github_settings.get("pat") or "").strip() or None
    git_ssh_key_path = (github_settings.get("ssh_key_path") or "").strip() or None

    if kind in {"local", "google_drive"}:
        rag_mode = "local"
        local_path = (getattr(source, "local_path", "") or "").strip()
        if local_path:
            repo_root = Path(local_path).expanduser().resolve()
    elif kind == "github":
        rag_mode = "git"
        git_repo = (getattr(source, "git_repo", "") or "").strip() or None
        source_branch = (getattr(source, "git_branch", "") or "").strip() or None
        source_git_dir = (getattr(source, "git_dir", "") or "").strip() or None
        if source_git_dir:
            git_dir = Path(source_git_dir).expanduser().resolve()
            repo_root = git_dir
        if source_branch:
            git_branch = source_branch
        git_url = build_git_url(git_repo, git_pat, git_ssh_key_path)
        repo_root = git_dir

    return replace(
        base,
        rag_mode=rag_mode,
        repo_root=repo_root,
        collection=getattr(source, "collection", base.collection),
        git_url=git_url,
        git_repo=git_repo,
        git_pat=git_pat,
        git_ssh_key_path=git_ssh_key_path,
        git_branch=git_branch,
        git_dir=git_dir,
    )
