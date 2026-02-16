from __future__ import annotations

from pathlib import Path

from services.instruction_adapters.base import (
    FRONTIER_INSTRUCTION_FILENAMES,
    InstructionAdapterDescriptor,
    InstructionAdapterMaterializationResult,
    compiled_instructions_markdown,
    write_compiled_instruction_file,
)
from services.instructions.compiler import CompiledInstructionPackage


class CodexInstructionAdapter:
    adapter_name = "codex_native_file"
    provider = "codex"
    file_name = FRONTIER_INSTRUCTION_FILENAMES[provider]

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
            mode="native",
            adapter=self.adapter_name,
            materialized_paths=(str(path),),
        )

    def fallback_payload(self, compiled: CompiledInstructionPackage) -> dict[str, object]:
        return {
            "provider": self.provider,
            "instructions_markdown": compiled_instructions_markdown(compiled),
        }

    def describe(self) -> InstructionAdapterDescriptor:
        return InstructionAdapterDescriptor(
            provider=self.provider,
            adapter=self.adapter_name,
            native_filename=self.file_name,
            supports_native=True,
        )
