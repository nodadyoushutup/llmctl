from __future__ import annotations

import hashlib
from pathlib import Path

from code_spans import detect_language, spans_for_language
from config import RagConfig, max_file_bytes_for
from doc_structures import html_spans, markdown_spans
from office_parsers import parse_docx, parse_pptx, parse_xlsx
from pdf_pipeline import parse_pdf
from pipeline import ParsedDocument


_CODE_EXTS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "shell",
    ".fish": "shell",
    ".ps1": "powershell",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".lua": "lua",
    ".sql": "sql",
}

_MARKDOWN_EXTS: dict[str, str] = {
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".adoc": "asciidoc",
}

_HTML_EXTS: dict[str, str] = {
    ".html": "html",
    ".htm": "html",
}

_CONFIG_EXTS: dict[str, str] = {
    ".json": "json",
    ".jsonc": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "conf",
    ".env": "env",
    ".properties": "properties",
    ".xml": "xml",
}

_TEXT_EXTS: dict[str, str] = {
    ".txt": "text",
    ".log": "log",
}

_DOC_TYPE_BY_EXT: dict[str, str] = {}
_DOC_TYPE_BY_EXT.update({ext: "code" for ext in _CODE_EXTS})
_DOC_TYPE_BY_EXT.update({ext: "markdown" for ext in _MARKDOWN_EXTS})
_DOC_TYPE_BY_EXT.update({ext: "html" for ext in _HTML_EXTS})
_DOC_TYPE_BY_EXT.update({ext: "config" for ext in _CONFIG_EXTS})
_DOC_TYPE_BY_EXT.update({ext: "text" for ext in _TEXT_EXTS})
_DOC_TYPE_BY_EXT.update(
    {
        ".pdf": "pdf",
        ".docx": "docx",
        ".pptx": "pptx",
        ".xlsx": "xlsx",
    }
)


def _is_binary_bytes(sample: bytes) -> bool:
    return b"\x00" in sample


def _read_text_bytes(
    path: Path, config: RagConfig, doc_type: str | None
) -> tuple[str, dict[str, object]] | None:
    try:
        stat = path.stat()
    except OSError:
        return None

    if stat.st_size > max_file_bytes_for(config, doc_type):
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None

    if not data:
        return None

    if _is_binary_bytes(data[:2048]):
        return None

    text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        return None

    file_hash = hashlib.sha1(data).hexdigest()
    source = {
        "path": str(path),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "file_hash": file_hash,
    }
    return text, source


def _make_text_parser(doc_type: str, language: str | None):
    def _parser(path: Path, config: RagConfig) -> ParsedDocument | None:
        result = _read_text_bytes(path, config, doc_type)
        if result is None:
            return None
        text, source = result
        return ParsedDocument(
            content=text,
            doc_type=doc_type,
            language=language,
            source=source,
        )

    return _parser


def _make_code_parser(language: str):
    def _parser(path: Path, config: RagConfig) -> ParsedDocument | None:
        result = _read_text_bytes(path, config, "code")
        if result is None:
            return None
        text, source = result
        spans = spans_for_language(language, text)
        structural_hints = {"spans": spans} if spans else {}
        return ParsedDocument(
            content=text,
            doc_type="code",
            language=language,
            source=source,
            structural_hints=structural_hints,
        )

    return _parser


def _fallback_parser(path: Path, config: RagConfig) -> ParsedDocument | None:
    result = _read_text_bytes(path, config, None)
    if result is None:
        return None
    text, source = result
    language = detect_language(text)
    if language:
        spans = spans_for_language(language, text)
        structural_hints = {"spans": spans} if spans else {}
        return ParsedDocument(
            content=text,
            doc_type="code",
            language=language,
            source=source,
            structural_hints=structural_hints,
        )
    return ParsedDocument(
        content=text,
        doc_type="text",
        language=None,
        source=source,
    )


def build_parser_registry():
    from pipeline import ParserRegistry

    registry = ParserRegistry()

    for ext, lang in _CODE_EXTS.items():
        registry.register(ext, _make_code_parser(lang))

    for ext, lang in _MARKDOWN_EXTS.items():
        def _md_parser(path: Path, config: RagConfig, _lang=lang):
            result = _read_text_bytes(path, config, "markdown")
            if result is None:
                return None
            text, source = result
            spans = markdown_spans(text)
            return ParsedDocument(
                content=text,
                doc_type="markdown",
                language=_lang,
                source=source,
                structural_hints={"spans": spans} if spans else {},
            )

        registry.register(ext, _md_parser)

    for ext, lang in _HTML_EXTS.items():
        def _html_parser(path: Path, config: RagConfig, _lang=lang):
            result = _read_text_bytes(path, config, "html")
            if result is None:
                return None
            text, source = result
            spans = html_spans(text)
            return ParsedDocument(
                content=text,
                doc_type="html",
                language=_lang,
                source=source,
                structural_hints={"spans": spans} if spans else {},
            )

        registry.register(ext, _html_parser)

    for ext, lang in _CONFIG_EXTS.items():
        registry.register(ext, _make_text_parser("config", lang))

    for ext, lang in _TEXT_EXTS.items():
        registry.register(ext, _make_text_parser("text", lang))

    registry.register(".pdf", parse_pdf)
    registry.register(".docx", parse_docx)
    registry.register(".pptx", parse_pptx)
    registry.register(".xlsx", parse_xlsx)

    registry.register_fallback(_fallback_parser)
    return registry


def is_doc_type_enabled(config: RagConfig, doc_type: str | None) -> bool:
    if not doc_type:
        return True
    if not config.enabled_doc_types:
        return True
    return doc_type.lower() in config.enabled_doc_types


def guess_doc_type(path: Path) -> str | None:
    ext = path.suffix.lower()
    return _DOC_TYPE_BY_EXT.get(ext)
