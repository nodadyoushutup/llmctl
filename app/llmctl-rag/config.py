from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


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
    "*.pdf",
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


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent] + list(here.parents):
        if (parent / ".git").exists():
            return parent
    # Fallback to two levels up: app/llmctl-rag -> repo root
    return here.parents[2]


@dataclass(frozen=True)
class RagConfig:
    repo_root: Path
    rag_mode: str
    chroma_host: str
    chroma_port: int
    collection: str
    openai_api_key: str | None
    openai_embedding_model: str
    git_url: str | None
    git_branch: str
    git_poll_s: float
    git_dir: Path
    chunk_lines: int
    chunk_overlap_lines: int
    max_file_bytes: int
    exclude_dirs: set[str]
    exclude_globs: list[str]
    include_globs: list[str]


def load_config() -> RagConfig:
    root_env = os.getenv("RAG_ROOT")
    repo_root = Path(root_env).expanduser().resolve() if root_env else _find_repo_root()

    rag_mode = os.getenv("RAG_MODE", "local").strip().lower()
    git_dir = Path(os.getenv("RAG_GIT_DIR", "/tmp/llmctl-rag-repo")).expanduser().resolve()
    if rag_mode == "git":
        repo_root = git_dir

    exclude_dirs = set(_DEFAULT_EXCLUDE_DIRS)
    exclude_dirs.update(_split_csv(os.getenv("RAG_EXCLUDE_DIRS")))

    exclude_globs = list(_DEFAULT_EXCLUDE_GLOBS)
    exclude_globs.extend(_split_csv(os.getenv("RAG_EXCLUDE_GLOBS")))

    include_globs = _split_csv(os.getenv("RAG_INCLUDE_GLOBS"))

    return RagConfig(
        repo_root=repo_root,
        rag_mode=rag_mode,
        chroma_host=os.getenv("CHROMA_HOST", "localhost"),
        chroma_port=int(os.getenv("CHROMA_PORT", "8000")),
        collection=os.getenv("CHROMA_COLLECTION", "llmctl_repo"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_embedding_model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        git_url=os.getenv("RAG_GIT_URL"),
        git_branch=os.getenv("RAG_GIT_BRANCH", "main"),
        git_poll_s=float(os.getenv("RAG_GIT_POLL_S", "300")),
        git_dir=git_dir,
        chunk_lines=int(os.getenv("RAG_CHUNK_LINES", "120")),
        chunk_overlap_lines=int(os.getenv("RAG_CHUNK_OVERLAP_LINES", "20")),
        max_file_bytes=int(os.getenv("RAG_MAX_FILE_BYTES", str(1_000_000))),
        exclude_dirs=exclude_dirs,
        exclude_globs=exclude_globs,
        include_globs=include_globs,
    )
