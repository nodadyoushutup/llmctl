from __future__ import annotations

from pathlib import Path

from services.instruction_adapters.base import (
    InstructionAdapterDescriptor,
    InstructionAdapterMaterializationResult,
    compiled_instructions_markdown,
    resolve_agent_markdown_filename,
    write_compiled_instruction_file,
)
from services.instructions.compiler import CompiledInstructionPackage


class VLLMInstructionAdapter:
    adapter_name = "vllm_prompt_fallback"

    def __init__(
        self,
        *,
        provider: str,
        agent_markdown_filename: str | None = None,
    ) -> None:
        self.provider = str(provider or "").strip().lower() or "vllm"
        self.file_name = resolve_agent_markdown_filename(
            provider=self.provider,
            configured_filename=agent_markdown_filename,
        )

    def materialize(
        self,
        compiled: CompiledInstructionPackage,
        *,
        workspace: Path,
        runtime_home: Path,
        codex_home: Path | None = None,
    ) -> InstructionAdapterMaterializationResult:
        del runtime_home
        del codex_home
        path = write_compiled_instruction_file(workspace, self.file_name, compiled)
        return InstructionAdapterMaterializationResult(
            mode="fallback",
            adapter=self.adapter_name,
            materialized_paths=(str(path),),
        )

    def fallback_payload(self, compiled: CompiledInstructionPackage) -> dict[str, object]:
        return {
            "provider": self.provider,
            "materialized_filename": self.file_name,
            "instructions_markdown": compiled_instructions_markdown(compiled),
        }

    def describe(self) -> InstructionAdapterDescriptor:
        return InstructionAdapterDescriptor(
            provider=self.provider,
            adapter=self.adapter_name,
            native_filename=self.file_name,
            supports_native=False,
        )
