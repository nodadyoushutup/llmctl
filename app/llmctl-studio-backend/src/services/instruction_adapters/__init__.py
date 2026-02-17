from __future__ import annotations

from services.instruction_adapters.base import (
    FRONTIER_INSTRUCTION_FILENAMES,
    NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME,
    InstructionAdapter,
    InstructionAdapterDescriptor,
    InstructionAdapterMaterializationResult,
    is_frontier_instruction_provider,
    resolve_agent_markdown_filename,
    validate_agent_markdown_filename,
)
from services.instruction_adapters.claude import ClaudeInstructionAdapter
from services.instruction_adapters.codex import CodexInstructionAdapter
from services.instruction_adapters.gemini import GeminiInstructionAdapter
from services.instruction_adapters.vllm import VLLMInstructionAdapter


def resolve_instruction_adapter(
    provider: str,
    *,
    agent_markdown_filename: str | None = None,
) -> InstructionAdapter:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "codex":
        return CodexInstructionAdapter()
    if normalized_provider == "gemini":
        return GeminiInstructionAdapter()
    if normalized_provider == "claude":
        return ClaudeInstructionAdapter()
    if normalized_provider in {"vllm_local", "vllm_remote"}:
        return VLLMInstructionAdapter(
            provider=normalized_provider,
            agent_markdown_filename=agent_markdown_filename,
        )
    raise ValueError(f"No instruction adapter configured for provider '{provider}'.")


__all__ = [
    "FRONTIER_INSTRUCTION_FILENAMES",
    "NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME",
    "InstructionAdapter",
    "InstructionAdapterDescriptor",
    "InstructionAdapterMaterializationResult",
    "ClaudeInstructionAdapter",
    "CodexInstructionAdapter",
    "GeminiInstructionAdapter",
    "VLLMInstructionAdapter",
    "is_frontier_instruction_provider",
    "resolve_agent_markdown_filename",
    "resolve_instruction_adapter",
    "validate_agent_markdown_filename",
]
