"""RAG runtime bootstrap and lifecycle entrypoints."""

from rag.runtime.run import start_rag_runtime, stop_rag_runtime

__all__ = ["start_rag_runtime", "stop_rag_runtime"]
