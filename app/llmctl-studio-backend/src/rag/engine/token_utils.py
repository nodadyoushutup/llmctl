from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None

_CHARS_PER_TOKEN_ESTIMATE = 3


@lru_cache(maxsize=32)
def _get_encoding(model_name: str | None):
    if tiktoken is None:
        return None
    if model_name:
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            pass
    return tiktoken.get_encoding("cl100k_base")


@dataclass(frozen=True)
class TokenCounter:
    model_name: str | None = None

    def _encoding(self):
        return _get_encoding(self.model_name)

    def count(self, text: str) -> int:
        if not text:
            return 0
        encoding = self._encoding()
        if encoding is None:
            return max(1, (len(text) + _CHARS_PER_TOKEN_ESTIMATE - 1) // _CHARS_PER_TOKEN_ESTIMATE)
        return len(encoding.encode(text))

    def split(self, text: str, max_tokens: int) -> list[tuple[str, int]]:
        if not text:
            return []
        if max_tokens <= 0:
            return [(text, self.count(text))]
        encoding = self._encoding()
        if encoding is None:
            max_chars = max(1, max_tokens * _CHARS_PER_TOKEN_ESTIMATE)
            parts = []
            for i in range(0, len(text), max_chars):
                chunk = text[i : i + max_chars]
                parts.append((chunk, self.count(chunk)))
            return parts

        tokens = encoding.encode(text)
        if len(tokens) <= max_tokens:
            return [(text, len(tokens))]
        parts: list[tuple[str, int]] = []
        for i in range(0, len(tokens), max_tokens):
            token_slice = tokens[i : i + max_tokens]
            parts.append((encoding.decode(token_slice), len(token_slice)))
        return parts
