from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from rag.engine.config import RagConfig


@dataclass(frozen=True)
class ParsedDocument:
    """Normalized document representation from any parser."""

    content: str
    doc_type: str
    language: str | None
    source: dict[str, object]
    structural_hints: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """Atomic unit to embed + index with optional structural metadata."""

    text: str
    metadata: dict[str, object] = field(default_factory=dict)
    start_line: int | None = None
    end_line: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    source: str | None = None
    doc_group_id: str | None = None


class Parser(Protocol):
    def __call__(self, path: Path, config: RagConfig) -> ParsedDocument | None:
        ...


class Chunker(Protocol):
    def __call__(self, document: ParsedDocument, config: RagConfig) -> list[Chunk]:
        ...


class ParserRegistry:
    """Register parsers keyed by extension, with a fallback parser."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}
        self._fallback: Parser | None = None

    def register(self, ext: str, parser: Parser) -> None:
        key = ext.lower().strip()
        if key and not key.startswith("."):
            key = f".{key}"
        self._parsers[key] = parser

    def register_fallback(self, parser: Parser) -> None:
        self._fallback = parser

    def resolve(self, path: Path) -> Parser | None:
        ext = path.suffix.lower()
        parser = self._parsers.get(ext)
        if parser is not None:
            return parser
        return self._fallback


class ChunkerRegistry:
    """Register chunkers keyed by doc_type, with a fallback chunker."""

    def __init__(self) -> None:
        self._chunkers: dict[str, Chunker] = {}
        self._fallback: Chunker | None = None

    def register(self, doc_type: str, chunker: Chunker) -> None:
        self._chunkers[doc_type.lower().strip()] = chunker

    def register_fallback(self, chunker: Chunker) -> None:
        self._fallback = chunker

    def resolve(self, doc_type: str) -> Chunker | None:
        key = doc_type.lower().strip()
        chunker = self._chunkers.get(key)
        if chunker is not None:
            return chunker
        return self._fallback


def make_doc_group_id(path: Path, source_tag: str | None = None) -> str:
    """Stable grouping key for all chunks derived from the same file."""

    base = path.as_posix()
    if source_tag:
        return f"{base}::group::{source_tag}"
    return f"{base}::group"


def make_chunk_id(path: Path, source: str, page: int | None, index: int) -> str:
    """Generate a consistent chunk id with source + page metadata."""

    page_tag = f"page-{page}" if page is not None else "page-unknown"
    return f"{path.as_posix()}::{source}::{page_tag}::chunk-{index}"
