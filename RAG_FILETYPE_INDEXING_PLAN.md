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

- [ ] Confirm scope: modify `app/llmctl-rag` only (no other indexing paths).
- [ ] Define target file types and prioritization (must-have vs. later).
- [ ] Define acceptance criteria for quality and speed (e.g., retrieval accuracy, indexing time).
- [ ] Decide on dependency policy (pure-Python vs. native deps allowed).
- [ ] Define metadata schema (e.g., language, symbol name, page number, doc type, section header).
- [ ] Decide on max file size and per-type overrides.
- [ ] Record initial priorities:
  - [ ] Code: Python first (v1 must-have)
  - [ ] PDFs: text parse + OCR + vector point parse pipeline (v1 must-have)
  - [ ] Granularity: highest practical (prefer per-character boxes)
  - [ ] Dependencies: no constraints; prefer Tesseract for OCR
  - [ ] PDF vector points: store in Chroma (no size constraint)
  - [ ] Python chunking: AST symbols with fallback token chunks
  - [ ] Fallback token chunk sizing: parity with existing `RAG_CHUNK_LINES` config
  - [ ] PDF reading order: prioritize highest-quality layout order over speed
  - [ ] PDF outputs: always store text-layer parse and OCR parse separately (no merge)
  - [ ] PDF chunking: separate chunks per source (text vs OCR vs vector points)
  - [ ] PDF images: skip storing page images for now
  - [ ] Querying: ChromaDB MCP will query both sources; ensure metadata links all PDF chunks
  - [ ] Vector point data: serialize into chunk text for direct searchability
  - [ ] Chunk IDs: include source + page for clarity (e.g., `file.pdf::ocr::page-3::chunk-0`)
  - [ ] Vector point serialization format: JSON
  - [ ] OCR confidence: include per-character scores, plus per-word/line aggregates
  - [ ] Normalize units for numeric tokens (e.g., in, inches, mm) and store in metadata
  - [ ] Diagram line detection for technical drawings (line segments/shapes + coordinates)
  - [ ] Diagram detection approach: extract vector paths from PDF + raster line detection for scanned drawings
  - [ ] Diagram geometry storage: separate `source=vector-geom` chunks

## Stage 1: Architecture and interfaces

- [ ] Add a parser registry abstraction (path -> ParsedDocument).
- [ ] Add a chunker abstraction (ParsedDocument -> chunks with metadata).
- [ ] Define a standard ParsedDocument structure:
  - [ ] content (normalized text)
  - [ ] doc_type (e.g., code, markdown, pdf, text)
  - [ ] language or subtype (e.g., python, js, bash)
  - [ ] source metadata (path, size, hash, modified time)
  - [ ] structural hints (sections, symbols, page map)
- [ ] Define a Chunk structure:
  - [ ] text
  - [ ] start/end line or offsets (if applicable)
  - [ ] symbol/section/page metadata (if applicable)
  - [ ] source field (e.g., text, ocr, vector)
  - [ ] doc_group_id to link chunks from the same file

## Stage 2: Core implementation

- [ ] Implement parser routing by extension and/or MIME.
- [ ] Implement default text parser fallback:
  - [ ] UTF-8 decode (errors=ignore)
  - [ ] size and binary checks
  - [ ] minimal metadata
- [ ] Implement chunking strategies:
  - [ ] line-based chunker (existing behavior)
  - [ ] token-based chunker for prose (derive token size from `RAG_CHUNK_LINES` parity)
  - [ ] structure-based chunker for code
- [ ] Integrate new pipeline into `ingest.py`:
  - [ ] replace `_read_text()` + `_chunk_lines()` with parser + chunker
  - [ ] preserve batching and Chroma metadata fields
  - [ ] add new metadata fields (language, doc_type, symbol, page)

## Stage 3: Code-aware parsing (priority languages)

- [ ] Python:
  - [ ] parse functions/classes/modules
  - [ ] chunk by symbol with fallback token chunks (for large symbols or non-symbol text)
- [ ] JavaScript / TypeScript:
  - [ ] parse functions/classes/modules
  - [ ] chunk by symbol with fallback
- [ ] Bash / shell:
  - [ ] parse functions and scripts
  - [ ] chunk by function or logical block
- [ ] Add language detection fallback (if extension missing).

## Stage 4: Document parsing

- [ ] Markdown:
  - [ ] chunk by headings
  - [ ] preserve code fences as separate blocks
- [ ] HTML:
  - [ ] strip boilerplate
  - [ ] chunk by headings/sections
- [ ] PDF pipeline (always run: text parse -> Tesseract OCR -> vector point parse):
  - [ ] text-layer extraction with page mapping (always)
  - [ ] render pages to images for OCR (always)
  - [ ] OCR with Tesseract (always; language config + confidence capture)
  - [ ] vector point parse with highest granularity:
    - [ ] per-character boxes (default)
    - [ ] reading order + page coordinates
  - [ ] store text-layer output and OCR output separately (no merge)
  - [ ] serialize vector point data as JSON in chunk text
  - [ ] include per-character OCR confidence and per-word/line aggregates
  - [ ] include page coordinate system metadata (dpi, origin, units)
  - [ ] extract diagram line segments/shapes (vector geometry) and store in JSON
  - [ ] extract vector paths from PDFs when available
  - [ ] run raster line detection for scanned drawings
  - [ ] detect and normalize numeric units from text/OCR tokens
  - [ ] chunk by page/section with spatial metadata
  - [ ] emit separate chunks for each source (text, ocr, vector)
  - [ ] ensure shared metadata links chunks to the same PDF (path + doc_group_id)
  - [ ] store vector point metadata in Chroma (no size constraint)
- [ ] Office documents:
  - [ ] DOCX / PPTX / XLSX basic text extraction
  - [ ] chunk by slides/sheets/sections

## Stage 5: Index lifecycle and change tracking

- [ ] Extend file hash metadata to include parser version and chunker version.
- [ ] Detect parser-relevant changes and reindex when parser config changes.
- [ ] Add per-type exclusion rules and per-type max file size.
- [ ] Add per-type chunk-size overrides.

## Stage 6: Configuration and controls

- [ ] Add config for:
  - [ ] enabling/disabling file types
  - [ ] OCR enablement and language
  - [ ] chunk sizes per doc type
  - [ ] token chunk size (if used)
- [ ] Document environment variables in `app/llmctl-rag/README.md`.

## Stage 7: Testing and evaluation

- [ ] Unit tests for parsers and chunkers per file type.
- [ ] Regression tests against known repos (golden retrieval set).
- [ ] Performance tests (indexing speed, OCR throughput).
- [ ] Quality tests (retrieval relevance by file type).

## Stage 8: Ops and observability

- [ ] Add structured logging for parsing errors per file type.
- [ ] Track chunk counts and per-type coverage.
- [ ] Emit warnings for skipped files (size/binary/unsupported).

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
