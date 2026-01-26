from __future__ import annotations

import json
import re

from config import RagConfig, chunk_lines_for, chunk_overlap_lines_for
from pipeline import Chunk, ParsedDocument

_TOKEN_RE = re.compile(r"\S+")
_TOKENS_PER_LINE = 20


def _chunk_lines(lines: list[str], chunk_lines: int, overlap_lines: int):
    if chunk_lines <= 0:
        chunk_lines = 120
    overlap_lines = max(0, min(overlap_lines, chunk_lines - 1))

    start = 0
    total = len(lines)
    while start < total:
        end = min(start + chunk_lines, total)
        yield start, end, "".join(lines[start:end])
        if end >= total:
            break
        start = max(0, end - overlap_lines)


def line_chunker(document: ParsedDocument, config: RagConfig) -> list[Chunk]:
    chunk_lines = chunk_lines_for(config, document.doc_type)
    overlap_lines = chunk_overlap_lines_for(config, document.doc_type)
    lines = document.content.splitlines(keepends=True)
    chunks: list[Chunk] = []
    for start, end, text in _chunk_lines(
        lines, chunk_lines, overlap_lines
    ):
        text = text.strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                text=text,
                start_line=start + 1,
                end_line=end,
                metadata={
                    "start_line": start + 1,
                    "end_line": end,
                },
            )
        )
    return chunks


def _token_limits(config: RagConfig, doc_type: str) -> tuple[int, int]:
    chunk_lines = chunk_lines_for(config, doc_type)
    overlap_lines = chunk_overlap_lines_for(config, doc_type)
    max_tokens = max(200, chunk_lines * _TOKENS_PER_LINE)
    overlap_tokens = max(0, min(max_tokens - 1, overlap_lines * _TOKENS_PER_LINE))
    return max_tokens, overlap_tokens


def token_chunker(document: ParsedDocument, config: RagConfig) -> list[Chunk]:
    content = document.content
    tokens = list(_TOKEN_RE.finditer(content))
    if not tokens:
        return []

    max_tokens, overlap_tokens = _token_limits(config, document.doc_type)
    chunks: list[Chunk] = []

    idx = 0
    total = len(tokens)
    while idx < total:
        end_idx = min(idx + max_tokens, total)
        start_pos = tokens[idx].start()
        end_pos = tokens[end_idx - 1].end()
        text = content[start_pos:end_pos].strip()
        if text:
            chunks.append(
                Chunk(
                    text=text,
                    start_offset=start_pos,
                    end_offset=end_pos,
                    metadata={
                        "start_offset": start_pos,
                        "end_offset": end_pos,
                        "token_start": idx,
                        "token_end": end_idx,
                    },
                )
            )
        if end_idx >= total:
            break
        idx = max(0, end_idx - overlap_tokens)

    return chunks


def structure_chunker(document: ParsedDocument, config: RagConfig) -> list[Chunk]:
    spans = document.structural_hints.get("spans") if document.structural_hints else None
    if not spans:
        return token_chunker(document, config)

    chunks: list[Chunk] = []
    lines = document.content.splitlines(keepends=True)
    covered = [False] * len(lines)
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)

    for span in spans:
        text = span.get("text")
        if not text:
            continue
        start_line = span.get("start_line")
        end_line = span.get("end_line")
        if start_line and end_line:
            for idx in range(start_line - 1, min(end_line, len(covered))):
                covered[idx] = True
        metadata = dict(span.get("metadata", {}))
        if start_line is not None:
            metadata.setdefault("start_line", start_line)
        if end_line is not None:
            metadata.setdefault("end_line", end_line)
        chunks.append(
            Chunk(
                text=str(text).strip(),
                start_line=start_line,
                end_line=end_line,
                metadata=metadata,
            )
        )

    # Add fallback token chunks for uncovered spans (e.g., module-level text).
    if covered:
        idx = 0
        while idx < len(covered):
            if covered[idx]:
                idx += 1
                continue
            start_idx = idx
            while idx < len(covered) and not covered[idx]:
                idx += 1
            end_idx = idx
            block_text = "".join(lines[start_idx:end_idx])
            if not block_text.strip():
                continue
            block_start_line = start_idx + 1
            block_end_line = end_idx
            base_offset = line_offsets[start_idx]
            temp_doc = ParsedDocument(
                content=block_text,
                doc_type=document.doc_type,
                language=document.language,
                source=document.source,
                structural_hints={},
            )
            for sub_chunk in token_chunker(temp_doc, config):
                start_offset = (
                    sub_chunk.start_offset + base_offset
                    if sub_chunk.start_offset is not None
                    else None
                )
                end_offset = (
                    sub_chunk.end_offset + base_offset
                    if sub_chunk.end_offset is not None
                    else None
                )
                metadata = dict(sub_chunk.metadata)
                metadata.setdefault("block_start_line", block_start_line)
                metadata.setdefault("block_end_line", block_end_line)
                chunks.append(
                    Chunk(
                        text=sub_chunk.text,
                        metadata=metadata,
                        start_offset=start_offset,
                        end_offset=end_offset,
                    )
                )

    if not chunks:
        return token_chunker(document, config)
    return chunks


def _json_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def pdf_chunker(document: ParsedDocument, config: RagConfig) -> list[Chunk]:
    hints = document.structural_hints.get("pdf") if document.structural_hints else None
    if not hints:
        return token_chunker(document, config)

    pages = hints.get("pages", [])
    chunks: list[Chunk] = []

    for page in pages:
        page_number = page.get("page_number")
        text_layer = page.get("text_layer", {})
        text_value = text_layer.get("text") if isinstance(text_layer, dict) else None
        if text_value and text_value.strip():
            chunks.append(
                Chunk(
                    text=text_value.strip(),
                    metadata={"page_number": page_number},
                    source="text",
                )
            )

        ocr = page.get("ocr", {}) if isinstance(page.get("ocr"), dict) else {}
        ocr_text = ocr.get("text", "")
        ocr_payload = {
            "extracted_text": ocr_text,
            "ocr_word_boxes": ocr.get("word_boxes", []),
            "ocr_char_boxes": ocr.get("char_boxes", []),
            "table_structures": page.get("tables", []),
            "normalized_units": page.get("normalized_units", []),
            "page_number": page_number,
            "source": "ocr",
        }
        if ocr_payload["extracted_text"] or ocr_payload["ocr_word_boxes"]:
            chunks.append(
                Chunk(
                    text=_json_payload(ocr_payload),
                    metadata={"page_number": page_number},
                    source="ocr",
                )
            )

        extracted_text = text_value or ocr_text or ""
        vector_primitives = page.get("vector_primitives", [])
        if vector_primitives:
            vector_payload = {
                "extracted_text": extracted_text,
                "vector_primitives": vector_primitives,
                "page_number": page_number,
                "source": "vector-geom",
            }
            chunks.append(
                Chunk(
                    text=_json_payload(vector_payload),
                    metadata={"page_number": page_number},
                    source="vector-geom",
                )
            )

        vector_raw = page.get("vector_raw")
        if vector_raw:
            raw_payload = {
                "vector_raw_payload": vector_raw,
                "page_number": page_number,
                "source": "vector-raw",
            }
            chunks.append(
                Chunk(
                    text=_json_payload(raw_payload),
                    metadata={"page_number": page_number},
                    source="vector-raw",
                )
            )

    raw_document = hints.get("vector_raw_document")
    if raw_document:
        doc_payload = {
            "vector_raw_payload": raw_document,
            "page_number": None,
            "source": "vector-raw",
        }
        chunks.append(
            Chunk(
                text=_json_payload(doc_payload),
                metadata={},
                source="vector-raw",
            )
        )

    return chunks


def build_chunker_registry():
    from pipeline import ChunkerRegistry

    registry = ChunkerRegistry()
    registry.register("code", structure_chunker)
    registry.register("markdown", token_chunker)
    registry.register("html", token_chunker)
    registry.register("text", token_chunker)
    registry.register("config", line_chunker)
    registry.register("docx", structure_chunker)
    registry.register("pptx", structure_chunker)
    registry.register("xlsx", structure_chunker)
    registry.register("pdf", pdf_chunker)
    registry.register_fallback(line_chunker)
    return registry
