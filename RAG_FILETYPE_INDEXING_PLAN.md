# RAG file type indexing plan

This plan extends `app/llmctl-rag` with file-type-aware parsing and chunking, plus robust
handling of document formats (including PDFs). The default fallback is plain text for
unknown or extensionless files.

## How to use this plan

- Each task uses GitHub-style checkboxes.
- Mark a task complete by changing `[ ]` to `[x]`.
- Do not check a parent task until all of its children are complete.
- If a task is partially complete, add a short note beneath it describing what is left.

## Stage 0: Scope + acceptance criteria

- [x] Confirm scope: modify `app/llmctl-rag` only (no other indexing paths).
- [x] Define target file types and prioritization (must-have vs. later).
  - Must-have: Python code + PDF pipeline (text/OCR/vector).
  - Later: remaining code/doc/cad types listed in Appendix A.
- [x] Define acceptance criteria for quality and speed.
  - PDF: answer content/measurement questions (e.g., dimensions in drawings) using text/OCR/vector data.
  - Python: retrieve correct symbol-level context for code questions.
  - Indexing: prioritize quality over speed; correctness of coverage is primary.
- [x] Decide on dependency policy (pure-Python vs. native deps allowed).
  - Native deps allowed; prefer Tesseract for OCR.
- [x] Define metadata schema (e.g., language, symbol name, page number, doc type, section header).
  - Core fields: path, doc_group_id, doc_type, source, language, page_number, chunk_index.
  - PDF fields: extracted_text, ocr_* boxes/confidence, vector_primitives, vector_raw_payload, table_structures, normalized_units.
- [x] Decide on max file size and per-type overrides.
  - Default: `RAG_MAX_FILE_BYTES` (current config).
  - Override: PDFs can exceed default (configurable per type).
- [x] Record initial priorities:
  - [x] Code: Python first (v1 must-have)
  - [x] PDFs: text parse + OCR + vector point parse pipeline (v1 must-have)
  - [x] Granularity: highest practical (prefer per-character boxes)
  - [x] Dependencies: no constraints; prefer Tesseract for OCR
  - [x] PDF vector points: store in Chroma (no size constraint)
  - [x] Python chunking: AST symbols with fallback token chunks
  - [x] Fallback token chunk sizing: parity with existing `RAG_CHUNK_LINES` config
  - [x] PDF reading order: prioritize highest-quality layout order over speed
  - [x] PDF outputs: always store text-layer parse and OCR parse separately (no merge)
  - [x] PDF chunking: separate chunks per source (text vs OCR vs vector points)
  - [x] PDF images: skip storing page images for now
  - [x] Querying: ChromaDB MCP will query both sources; ensure metadata links all PDF chunks
  - [x] Vector point data: serialize into chunk text for direct searchability
  - [x] Chunk IDs: include source + page for clarity (e.g., `file.pdf::ocr::page-3::chunk-0`)
  - [x] Vector point serialization format: JSON
  - [x] OCR confidence: include per-character scores, plus per-word/line aggregates
  - [x] Normalize units for numeric tokens (e.g., in, inches, mm) and store in metadata
  - [x] Diagram line detection for technical drawings (line segments/shapes + coordinates)
  - [x] Diagram detection approach: extract vector primitives from PDFs using a dedicated package
  - [x] Diagram geometry storage: separate `source=vector-geom` chunks
  - [x] Preserve full vector primitives (lines, arcs, circles, curves, polygons)
  - [x] PDF vector extraction package: prefer PyMuPDF (fitz) for richest primitive support
  - [x] PDF pipeline stack: PyMuPDF + Tesseract + OpenCV
  - [x] Store raw vector payload dump alongside parsed primitives
  - [x] Raw vector payload storage: separate `source=vector-raw` chunks
  - [x] Raw vector payload scope: both page-level and document-level dumps
  - [x] CAD support: defer to future (PDF focus for v1)
  - [x] PDF sources: separate chunk types for text and OCR (do not combine)
  - [x] OCR chunking: page-level chunks with per-word and per-character boxes in JSON
  - [x] Text-layer chunking: page-level, plus section/table detection when available
  - [x] Table handling: extract structure (rows/cols/cells + coordinates)
  - [x] Vector chunks: include plain-text `extracted_text` for searchability
  - [x] PDF chunk sizing: one chunk per page unless size limits are exceeded

## Stage 1: Architecture and interfaces

- [x] Add a parser registry abstraction (path -> ParsedDocument).
- [x] Add a chunker abstraction (ParsedDocument -> chunks with metadata).
- [x] Define a standard ParsedDocument structure:
  - [x] content (normalized text)
  - [x] doc_type (e.g., code, markdown, pdf, text)
  - [x] language or subtype (e.g., python, js, bash)
  - [x] source metadata (path, size, hash, modified time)
  - [x] structural hints (sections, symbols, page map)
- [x] Define a Chunk structure:
  - [x] text
  - [x] start/end line or offsets (if applicable)
  - [x] symbol/section/page metadata (if applicable)
  - [x] source field (e.g., text, ocr, vector)
  - [x] doc_group_id to link chunks from the same file
  - [x] PDF JSON schema (agnostic, searchable):
    - [x] extracted_text (plain text)
    - [x] page_number, doc_group_id, source
    - [x] ocr_char_boxes / ocr_word_boxes (with confidence)
    - [x] vector_primitives (lines/arcs/curves/polygons)
    - [x] vector_raw_payload (optional, large)
    - [x] table_structures (rows/cols/cells + coords)
    - [x] normalized_units (values + units + locations)

## Stage 2: Core implementation

- [x] Implement parser routing by extension and/or MIME.
- [x] Implement default text parser fallback:
  - [x] UTF-8 decode (errors=ignore)
  - [x] size and binary checks
  - [x] minimal metadata
- [x] Implement chunking strategies:
  - [x] line-based chunker (existing behavior)
  - [x] token-based chunker for prose (derive token size from `RAG_CHUNK_LINES` parity)
  - [x] structure-based chunker for code
- [x] Integrate new pipeline into `ingest.py`:
  - [x] replace `_read_text()` + `_chunk_lines()` with parser + chunker
  - [x] preserve batching and Chroma metadata fields
  - [x] add new metadata fields (language, doc_type, symbol, page)

## Stage 3: Code-aware parsing (priority languages)

- [x] Python:
  - [x] parse functions/classes/modules
  - [x] chunk by symbol with fallback token chunks (for large symbols or non-symbol text)
- [x] JavaScript / TypeScript:
  - [x] parse functions/classes/modules
  - [x] chunk by symbol with fallback
- [x] Bash / shell:
  - [x] parse functions and scripts
  - [x] chunk by function or logical block
- [x] Add language detection fallback (if extension missing).

## Stage 4: Document parsing

- [x] Markdown:
  - [x] chunk by headings
  - [x] preserve code fences as separate blocks
- [x] HTML:
  - [x] strip boilerplate
  - [x] chunk by headings/sections
- [x] PDF pipeline (always run: text parse -> Tesseract OCR -> vector point parse):
  - [x] text-layer extraction with page mapping (always)
  - [x] render pages to images for OCR (always)
  - [x] OCR with Tesseract (always; language config + confidence capture)
  - [x] vector point parse with highest granularity:
    - [x] per-character boxes (default)
    - [x] reading order + page coordinates
  - [x] store text-layer output and OCR output separately (no merge)
  - [x] serialize vector point data as JSON in chunk text
  - [x] include per-character OCR confidence and per-word/line aggregates
  - [x] coordinate system metadata deferred (not required for v1)
  - [x] extract diagram line segments/shapes (vector geometry) and store in JSON
  - [x] extract vector paths/primitives from PDFs when available
  - [x] store raw vector payload (as JSON) for traceability
  - [x] emit page-level raw vector payload chunks
  - [x] emit document-level raw vector payload chunk
  - [x] detect and normalize numeric units from text/OCR tokens
  - [x] chunk by page/section with spatial metadata
  - [x] emit separate chunks for each source (text, ocr, vector)
  - [x] ensure shared metadata links chunks to the same PDF (path + doc_group_id)
  - [x] store vector point metadata in Chroma (no size constraint)
- [x] Office documents:
  - [x] DOCX / PPTX / XLSX basic text extraction
  - [x] chunk by slides/sheets/sections

## Stage 5: Index lifecycle and change tracking

- [x] Extend file hash metadata to include parser version and chunker version.
- [x] Detect parser-relevant changes and reindex when parser config changes.
- [x] Add per-type exclusion rules and per-type max file size.
- [x] Add per-type chunk-size overrides.

## Stage 6: Configuration and controls

- [x] Add config for:
  - [x] enabling/disabling file types
  - [x] OCR enablement and language
  - [x] chunk sizes per doc type
  - [x] token chunk size (if used)
- [x] Document environment variables in `app/llmctl-rag/README.md`.

## Stage 7: Testing and evaluation

- [x] Unit tests for parsers and chunkers per file type.
- [x] Regression tests against known repos (golden retrieval set).
- [x] Performance tests (indexing speed, OCR throughput).
- [x] Quality tests (retrieval relevance by file type).

## Stage 8: Ops and observability

- [x] Add structured logging for parsing errors per file type.
- [x] Track chunk counts and per-type coverage.
- [x] Emit warnings for skipped files (size/binary/unsupported).

## Appendix A: Common file types to cover

### Code
- .py, .pyi
- .js, .jsx
- .ts, .tsx
- .mjs, .cjs
- .java
- .kt, .kts
- .go
- .rs
- .c, .h, .cpp, .hpp
- .cs
- .rb
- .php
- .swift
- .scala
- .lua
- .r
- .m (matlab), .mm (objc)
- .sql

### Shell / config / scripting
- .sh, .bash, .zsh, .fish
- .ps1
- .bat, .cmd
- .Makefile, Makefile
- .Dockerfile, Dockerfile
- .toml, .yaml, .yml
- .json, .jsonc
- .ini, .cfg, .conf
- .env
- .properties
- .xml

### Docs and prose
- .md, .mdx
- .rst
- .txt
- .adoc
- .rtf
- .html, .htm

### Data and notebooks
- .csv
- .tsv
- .parquet (metadata only by default)
- .ipynb

### PDFs and Office
- .pdf
- .docx
- .pptx
- .xlsx
- .odt, .odp, .ods

### Design / diagrams (text-based)
- .svg (text only)
- .drawio (xml)
- .mermaid

### CAD / modeling
- .dwg, .dxf
- .step, .stp
- .iges, .igs
- .stl
- .obj
- .fbx
- .3mf
- .blend
- .sldprt, .sldasm
- .ipt, .iam
- .prt, .asm
- .skp

### Other common text-like formats
- .log
- .proto
- .graphql, .gql
- .tf, .hcl
- .gradle
- .sbt

### Fallback
- extensionless files or unknown types: treat as plain text (current behavior)
