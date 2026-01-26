from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from config import RagConfig, max_file_bytes_for
from logging_utils import log_event
from pipeline import ParsedDocument

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

try:
    import pytesseract
    from pytesseract import Output as TesseractOutput
except ImportError:  # pragma: no cover
    pytesseract = None
    TesseractOutput = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


_UNIT_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>inches|inch|in|mm|cm|ft|feet|\")",
    re.IGNORECASE,
)


def _require_pdf_deps():
    if fitz is None:
        raise RuntimeError("PyMuPDF is required to parse PDFs")
    if pytesseract is None:
        raise RuntimeError("pytesseract is required for OCR")
    if Image is None:
        raise RuntimeError("Pillow is required for OCR")


def _pixmap_to_image(pix):
    mode = "RGB"
    if pix.alpha:
        mode = "RGBA"
    return Image.frombytes(mode, [pix.width, pix.height], pix.samples)


def _extract_text_layer(page) -> dict[str, Any]:
    text = page.get_text("text")
    raw = page.get_text("rawdict")
    char_boxes: list[dict[str, Any]] = []

    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    bbox = char.get("bbox")
                    char_boxes.append(
                        {
                            "text": char.get("c"),
                            "bbox": bbox,
                            "confidence": None,
                        }
                    )

    return {
        "text": text or "",
        "char_boxes": char_boxes,
    }


def _ocr_page(image, lang: str) -> dict[str, Any]:
    data = pytesseract.image_to_data(image, output_type=TesseractOutput.DICT, lang=lang)
    words: list[dict[str, Any]] = []
    ocr_text_parts: list[str] = []

    for i, word in enumerate(data.get("text", [])):
        if not word.strip():
            continue
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        conf = data["conf"][i]
        words.append(
            {
                "text": word,
                "bbox": [x, y, x + w, y + h],
                "confidence": conf,
            }
        )
        ocr_text_parts.append(word)

    char_boxes: list[dict[str, Any]] = []
    for line in pytesseract.image_to_boxes(image, lang=lang).splitlines():
        parts = line.split(" ")
        if len(parts) < 6:
            continue
        char, x1, y1, x2, y2, page_num = parts[:6]
        char_boxes.append(
            {
                "text": char,
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "confidence": None,
                "page": int(page_num),
            }
        )

    return {
        "text": " ".join(ocr_text_parts),
        "word_boxes": words,
        "char_boxes": char_boxes,
    }


def _group_rows(word_boxes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not word_boxes:
        return []
    sorted_words = sorted(word_boxes, key=lambda w: (w["bbox"][1], w["bbox"][0]))
    rows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_y: float | None = None
    threshold = 8.0

    for word in sorted_words:
        y_top = word["bbox"][1]
        if current_y is None or abs(y_top - current_y) <= threshold:
            current.append(word)
            if current_y is None:
                current_y = y_top
            else:
                current_y = (current_y + y_top) / 2.0
        else:
            rows.append(sorted(current, key=lambda w: w["bbox"][0]))
            current = [word]
            current_y = y_top

    if current:
        rows.append(sorted(current, key=lambda w: w["bbox"][0]))
    return rows


def _extract_tables(word_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _group_rows(word_boxes)
    if not rows:
        return []
    table_rows = []
    for row in rows:
        cells = []
        for word in row:
            cells.append(
                {
                    "text": word["text"],
                    "bbox": word["bbox"],
                }
            )
        table_rows.append({"cells": cells})
    return [{"rows": table_rows}]


def _normalize_units(text: str, page_number: int, source: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for match in _UNIT_RE.finditer(text):
        value = float(match.group("value"))
        unit = match.group("unit").lower()
        normalized_unit = unit
        normalized_value = value
        if unit in {"inch", "inches", "in", '"'}:
            normalized_unit = "in"
        elif unit in {"ft", "feet"}:
            normalized_unit = "ft"
        elif unit in {"cm"}:
            normalized_unit = "cm"
        elif unit in {"mm"}:
            normalized_unit = "mm"
        units.append(
            {
                "value": value,
                "unit": unit,
                "normalized_value": normalized_value,
                "normalized_unit": normalized_unit,
                "page_number": page_number,
                "source": source,
            }
        )
    return units


def _serialize_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _json_friendly(value: Any) -> Any:
    if fitz is not None:
        if isinstance(value, fitz.Rect):
            return [value.x0, value.y0, value.x1, value.y1]
        if isinstance(value, fitz.Quad):
            return [[point.x, point.y] for point in value]
        if isinstance(value, fitz.Point):
            return [value.x, value.y]
        if isinstance(value, fitz.Matrix):
            return [value.a, value.b, value.c, value.d, value.e, value.f]
    if isinstance(value, dict):
        return {key: _json_friendly(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_friendly(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parse_pdf(path: Path, config: RagConfig) -> ParsedDocument | None:
    _require_pdf_deps()

    if path.stat().st_size > max_file_bytes_for(config, "pdf"):
        return None

    hasher = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    file_hash = hasher.hexdigest()

    doc = fitz.open(path)
    log_event(
        "rag_pdf_parse_start",
        path=str(path),
        pages=doc.page_count,
        message=f"Parsing PDF {path} ({doc.page_count} pages)",
    )
    pages: list[dict[str, Any]] = []

    for index in range(doc.page_count):
        page = doc.load_page(index)
        page_number = index + 1

        log_event(
            "rag_pdf_page_start",
            path=str(path),
            page_number=page_number,
            total_pages=doc.page_count,
            message=f"PDF page {page_number}/{doc.page_count}: extract text layer",
        )
        text_layer = _extract_text_layer(page)
        text_len = len(text_layer.get("text", "") or "")
        log_event(
            "rag_pdf_text_layer_complete",
            path=str(path),
            page_number=page_number,
            text_chars=text_len,
            message=f"PDF page {page_number}: text layer {text_len} chars",
        )
        ocr_layer = {"text": "", "word_boxes": [], "char_boxes": []}
        if config.ocr_enabled:
            log_event(
                "rag_pdf_ocr_start",
                path=str(path),
                page_number=page_number,
                ocr_lang=config.ocr_lang,
                message=f"PDF page {page_number}: OCR start (lang={config.ocr_lang})",
            )
            pix = page.get_pixmap(dpi=200)
            image = _pixmap_to_image(pix)
            ocr_layer = _ocr_page(image, config.ocr_lang)
            ocr_text_len = len(ocr_layer.get("text", "") or "")
            word_boxes = ocr_layer.get("word_boxes", [])
            log_event(
                "rag_pdf_ocr_complete",
                path=str(path),
                page_number=page_number,
                ocr_chars=ocr_text_len,
                ocr_words=len(word_boxes) if isinstance(word_boxes, list) else 0,
                message=f"PDF page {page_number}: OCR done ({ocr_text_len} chars)",
            )

        drawings = page.get_drawings()
        drawings_serialized = _json_friendly(drawings)
        primitives: list[dict[str, Any]] = []
        for drawing in drawings:
            for item in drawing.get("items", []):
                if not item:
                    continue
                kind = item[0]
                if kind == "l":
                    primitives.append(
                        {
                            "type": "line",
                            "points": _json_friendly([item[1], item[2]]),
                        }
                    )
                elif kind == "c":
                    primitives.append(
                        {
                            "type": "curve",
                            "points": _json_friendly([item[1], item[2], item[3], item[4]]),
                        }
                    )
                elif kind == "re":
                    primitives.append(
                        {
                            "type": "rect",
                            "rect": _json_friendly(item[1]),
                        }
                    )
                elif kind == "qu":
                    primitives.append(
                        {
                            "type": "quad",
                            "points": _json_friendly(item[1]),
                        }
                    )

        tables = _extract_tables(ocr_layer.get("word_boxes", []))
        log_event(
            "rag_pdf_vectors_complete",
            path=str(path),
            page_number=page_number,
            drawing_count=len(drawings) if drawings is not None else 0,
            primitive_count=len(primitives),
            table_count=len(tables),
            message=f"PDF page {page_number}: vectors {len(primitives)}, tables {len(tables)}",
        )
        normalized_units = _normalize_units(
            f"{text_layer.get('text','')} {ocr_layer.get('text','')}",
            page_number,
            "ocr",
        )
        log_event(
            "rag_pdf_units_complete",
            path=str(path),
            page_number=page_number,
            unit_count=len(normalized_units),
            message=f"PDF page {page_number}: normalized {len(normalized_units)} units",
        )

        pages.append(
            {
                "page_number": page_number,
                "text_layer": text_layer,
                "ocr": ocr_layer,
                "vector_primitives": primitives,
                "vector_raw": drawings_serialized,
                "tables": tables,
                "normalized_units": normalized_units,
            }
        )

    log_event(
        "rag_pdf_parse_complete",
        path=str(path),
        pages=len(pages),
        message=f"Completed PDF parse {path} ({len(pages)} pages)",
    )
    source = {
        "path": str(path),
        "size": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "file_hash": file_hash,
    }

    structural_hints = {
        "pdf": {
            "pages": pages,
        }
    }

    return ParsedDocument(
        content="",
        doc_type="pdf",
        language=None,
        source=source,
        structural_hints=structural_hints,
    )
