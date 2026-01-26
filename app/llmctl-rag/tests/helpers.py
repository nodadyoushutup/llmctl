from __future__ import annotations

from pathlib import Path

from config import RagConfig


def test_config(tmp_path: Path | None = None) -> RagConfig:
    root = tmp_path or Path("/tmp")
    return RagConfig(
        repo_root=root,
        rag_mode="local",
        chroma_host="localhost",
        chroma_port=8000,
        collection="test_collection",
        openai_api_key=None,
        openai_embedding_model="text-embedding-3-small",
        embed_max_tokens_per_request=300000,
        embed_max_tokens_per_input=8192,
        git_url=None,
        git_repo=None,
        git_pat=None,
        git_ssh_key_path=None,
        git_branch="main",
        git_poll_s=300.0,
        git_dir=Path("/tmp/llmctl-rag-repo"),
        watch_enabled=True,
        watch_debounce_s=1.0,
        chunk_lines=10,
        chunk_overlap_lines=2,
        max_file_bytes=1_000_000,
        exclude_dirs=set(),
        exclude_globs=[],
        include_globs=[],
        max_file_bytes_by_type={"pdf": 1_000_000_000},
        exclude_globs_by_type={},
        chunk_lines_by_type={},
        chunk_overlap_lines_by_type={},
        enabled_doc_types=set(),
        ocr_enabled=True,
        ocr_lang="eng",
        chat_model="gpt-4o-mini",
        chat_temperature=0.2,
        chat_top_k=5,
        chat_max_history=8,
        chat_max_context_chars=12000,
        chat_snippet_chars=600,
        chat_context_budget_tokens=8000,
        web_port=5050,
    )
