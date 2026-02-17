from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from rag.engine.config import RagConfig, max_file_bytes_for
from rag.engine.logging_utils import log_event, submit_with_log_context
from rag.engine.pipeline import ParsedDocument

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

_AXIS_ALIGN_EPSILON = 1.5
_NON_AXIS_LINE_THRESHOLD = 8
_DENSE_PRIMITIVE_THRESHOLD = 1200
_MIXED_PRIMITIVE_THRESHOLD = 250
_MIXED_NON_AXIS_THRESHOLD = 3


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
    has_images = False

    for block in raw.get("blocks", []):
        if block.get("type") == 1:
            has_images = True
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
        "has_images": has_images,
    }


def _point_xy(point: Any) -> tuple[float, float] | None:
    if fitz is not None and isinstance(point, fitz.Point):
        return float(point.x), float(point.y)
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        try:
            return float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
    return None


def _is_axis_aligned_line(start: Any, end: Any, *, epsilon: float = _AXIS_ALIGN_EPSILON) -> bool:
    a = _point_xy(start)
    b = _point_xy(end)
    if a is None or b is None:
        return False
    return abs(a[0] - b[0]) <= epsilon or abs(a[1] - b[1]) <= epsilon


def _page_has_embedded_image(page, text_layer: dict[str, Any]) -> bool:
    if bool(text_layer.get("has_images")):
        return True
    try:
        return len(page.get_images(full=True)) > 0
    except Exception:
        return False


def _summarize_vector_geometry(drawings: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "drawing_count": len(drawings),
        "primitive_count": 0,
        "line_count": 0,
        "rect_count": 0,
        "curve_count": 0,
        "quad_count": 0,
        "non_axis_line_count": 0,
    }

    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item:
                continue
            kind = item[0]
            if kind == "l":
                stats["line_count"] += 1
                stats["primitive_count"] += 1
                if not _is_axis_aligned_line(item[1], item[2]):
                    stats["non_axis_line_count"] += 1
            elif kind == "c":
                stats["curve_count"] += 1
                stats["primitive_count"] += 1
            elif kind == "re":
                stats["rect_count"] += 1
                stats["primitive_count"] += 1
            elif kind == "qu":
                stats["quad_count"] += 1
                stats["primitive_count"] += 1

    return stats


def _should_capture_vector_payload(stats: dict[str, int]) -> tuple[bool, str]:
    primitive_count = int(stats.get("primitive_count", 0) or 0)
    line_count = int(stats.get("line_count", 0) or 0)
    rect_count = int(stats.get("rect_count", 0) or 0)
    curve_count = int(stats.get("curve_count", 0) or 0)
    quad_count = int(stats.get("quad_count", 0) or 0)
    non_axis_line_count = int(stats.get("non_axis_line_count", 0) or 0)

    if primitive_count <= 0:
        return False, "no_geometry"
    if (curve_count + quad_count) > 0:
        return True, "curve_or_quad"
    if non_axis_line_count >= _NON_AXIS_LINE_THRESHOLD:
        return True, "non_axis_lines"
    if primitive_count >= _DENSE_PRIMITIVE_THRESHOLD:
        return True, "dense_geometry"
    if (
        primitive_count >= _MIXED_PRIMITIVE_THRESHOLD
        and non_axis_line_count >= _MIXED_NON_AXIS_THRESHOLD
    ):
        return True, "mixed_geometry"
    if primitive_count == (line_count + rect_count) and non_axis_line_count == 0:
        return False, "axis_aligned_layout"
    return False, "low_signal_geometry"


def _build_vector_primitives(drawings: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return primitives


def _ocr_page(
    image,
    *,
    lang: str,
    timeout_s: int,
    include_char_boxes: bool,
) -> dict[str, Any]:
    ocr_kwargs: dict[str, Any] = {"lang": lang}
    if timeout_s > 0:
        ocr_kwargs["timeout"] = timeout_s
    data = pytesseract.image_to_data(
        image,
        output_type=TesseractOutput.DICT,
        **ocr_kwargs,
    )
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
    if include_char_boxes:
        for line in pytesseract.image_to_boxes(image, **ocr_kwargs).splitlines():
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


def _parse_single_pdf_page(
    path: Path,
    page_index: int,
    total_pages: int,
    config: RagConfig,
) -> tuple[int, dict[str, Any]]:
    page_number = page_index + 1
    doc = fitz.open(path)
    try:
        page = doc.load_page(page_index)
        log_event(
            "rag_pdf_page_start",
            path=str(path),
            page_number=page_number,
            total_pages=total_pages,
            message=f"PDF page {page_number}/{total_pages}: extract text layer",
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
        page_has_images = _page_has_embedded_image(page, text_layer)
        ocr_layer = {"text": "", "word_boxes": [], "char_boxes": []}
        if config.ocr_enabled and page_has_images:
            log_event(
                "rag_pdf_ocr_start",
                path=str(path),
                page_number=page_number,
                ocr_lang=config.ocr_lang,
                message=f"PDF page {page_number}: OCR start (lang={config.ocr_lang})",
            )
            pix = page.get_pixmap(dpi=max(72, int(config.ocr_dpi)))
            image = _pixmap_to_image(pix)
            try:
                ocr_layer = _ocr_page(
                    image,
                    lang=config.ocr_lang,
                    timeout_s=max(0, int(config.ocr_timeout_s)),
                    include_char_boxes=bool(config.ocr_include_char_boxes),
                )
            except RuntimeError as exc:
                if "timeout" in str(exc).lower():
                    log_event(
                        "rag_pdf_ocr_timeout",
                        path=str(path),
                        page_number=page_number,
                        timeout_s=max(0, int(config.ocr_timeout_s)),
                        message=(
                            f"PDF page {page_number}: OCR timed out after "
                            f"{max(0, int(config.ocr_timeout_s))}s"
                        ),
                    )
                else:
                    log_event(
                        "rag_pdf_ocr_error",
                        path=str(path),
                        page_number=page_number,
                        error=str(exc),
                        message=f"PDF page {page_number}: OCR failed ({exc})",
                    )
            finally:
                del pix
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
        elif config.ocr_enabled:
            log_event(
                "rag_pdf_ocr_skipped_no_image",
                path=str(path),
                page_number=page_number,
                message=f"PDF page {page_number}: OCR skipped (no images detected)",
            )

        drawings = page.get_drawings()
        vector_stats = _summarize_vector_geometry(drawings)
        capture_vectors, vector_reason = _should_capture_vector_payload(vector_stats)
        log_event(
            "rag_pdf_vector_gate",
            path=str(path),
            page_number=page_number,
            capture_vectors=capture_vectors,
            vector_reason=vector_reason,
            primitive_count=vector_stats.get("primitive_count", 0),
            line_count=vector_stats.get("line_count", 0),
            rect_count=vector_stats.get("rect_count", 0),
            curve_count=vector_stats.get("curve_count", 0),
            quad_count=vector_stats.get("quad_count", 0),
            non_axis_line_count=vector_stats.get("non_axis_line_count", 0),
            message=(
                f"PDF page {page_number}: vector payload "
                f"{'enabled' if capture_vectors else 'skipped'} ({vector_reason})"
            ),
        )
        if capture_vectors:
            primitives = _build_vector_primitives(drawings)
            drawings_serialized = _json_friendly(drawings)
        else:
            primitives = []
            drawings_serialized = []

        tables = _extract_tables(ocr_layer.get("word_boxes", []))
        log_event(
            "rag_pdf_vectors_complete",
            path=str(path),
            page_number=page_number,
            drawing_count=vector_stats.get("drawing_count", 0),
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

        return (
            page_index,
            {
                "page_number": page_number,
                "text_layer": text_layer,
                "ocr": ocr_layer,
                "vector_primitives": primitives,
                "vector_raw": drawings_serialized,
                "tables": tables,
                "normalized_units": normalized_units,
            },
        )
    finally:
        doc.close()


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
    try:
        page_count = doc.page_count
    finally:
        doc.close()

    page_workers = min(max(1, int(config.pdf_page_workers)), max(1, page_count))
    log_event(
        "rag_pdf_parse_start",
        path=str(path),
        pages=page_count,
        page_workers=page_workers,
        message=f"Parsing PDF {path} ({page_count} pages, workers={page_workers})",
    )

    pages_by_index: dict[int, dict[str, Any]] = {}
    if page_count <= 1 or page_workers <= 1:
        for index in range(page_count):
            parsed_index, parsed_page = _parse_single_pdf_page(
                path,
                index,
                page_count,
                config,
            )
            pages_by_index[parsed_index] = parsed_page
    else:
        with ThreadPoolExecutor(max_workers=page_workers) as executor:
            futures = [
                submit_with_log_context(
                    executor,
                    _parse_single_pdf_page,
                    path,
                    index,
                    page_count,
                    config,
                )
                for index in range(page_count)
            ]
            for future in as_completed(futures):
                parsed_index, parsed_page = future.result()
                pages_by_index[parsed_index] = parsed_page

    pages = [pages_by_index[index] for index in range(page_count) if index in pages_by_index]

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
