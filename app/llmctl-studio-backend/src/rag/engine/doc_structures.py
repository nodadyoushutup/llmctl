from __future__ import annotations

import html
import re
from html.parser import HTMLParser


def markdown_spans(text: str) -> list[dict[str, object]]:
    lines = text.splitlines(keepends=True)
    spans: list[dict[str, object]] = []
    current_heading = "<root>"
    buffer: list[str] = []
    start_line = 1
    in_fence = False
    fence_delim = ""
    fence_start = 0

    def flush(end_line: int) -> None:
        nonlocal buffer, start_line
        if not buffer:
            return
        spans.append(
            {
                "text": "".join(buffer),
                "start_line": start_line,
                "end_line": end_line,
                "metadata": {
                    "section": current_heading,
                },
            }
        )
        buffer = []

    for idx, line in enumerate(lines, start=1):
        fence_match = re.match(r"^(```|~~~)", line)
        if fence_match:
            if not in_fence:
                flush(idx - 1)
                in_fence = True
                fence_delim = fence_match.group(1)
                fence_start = idx
                buffer = [line]
                continue
            if fence_match.group(1) == fence_delim:
                buffer.append(line)
                spans.append(
                    {
                        "text": "".join(buffer),
                        "start_line": fence_start,
                        "end_line": idx,
                        "metadata": {
                            "section": current_heading,
                            "block_type": "code_fence",
                        },
                    }
                )
                buffer = []
                in_fence = False
                fence_delim = ""
                start_line = idx + 1
                continue
        if in_fence:
            buffer.append(line)
            continue
        match = re.match(r"^(#{1,6})\\s+(.*)", line)
        if match:
            flush(idx - 1)
            current_heading = match.group(2).strip() or "<untitled>"
            start_line = idx
            buffer.append(line)
            continue
        buffer.append(line)

    flush(len(lines))
    return spans


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignore_depth = 0
        self._current_heading: str | None = None
        self._sections: list[dict[str, object]] = []
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self._ignore_depth += 1
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self._current_heading = None

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if self._current_heading is None and self._buffer:
                heading_text = " ".join(self._buffer).strip() or "<untitled>"
                self._sections.append(
                    {
                        "text": heading_text,
                        "metadata": {
                            "section": heading_text,
                            "block_type": "heading",
                        },
                    }
                )
                self._current_heading = heading_text
                self._buffer = []

    def handle_data(self, data: str):
        if self._ignore_depth:
            return
        text = html.unescape(data)
        if not text.strip():
            return
        self._buffer.append(text)

    def _flush(self) -> None:
        if not self._buffer:
            return
        text = " ".join(self._buffer).strip()
        if not text:
            self._buffer = []
            return
        self._sections.append(
            {
                "text": text,
                "metadata": {
                    "section": self._current_heading or "<root>",
                },
            }
        )
        self._buffer = []

    def finalize(self) -> list[dict[str, object]]:
        self._flush()
        return self._sections


def html_spans(text: str) -> list[dict[str, object]]:
    parser = _HTMLTextExtractor()
    parser.feed(text)
    return parser.finalize()
