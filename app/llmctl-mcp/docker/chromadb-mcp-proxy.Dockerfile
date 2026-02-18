FROM mcp/chroma:latest

ENV PYTHONUNBUFFERED=1

RUN for bin in chroma-mcp chromadb-mcp; do \
       if command -v "${bin}" >/dev/null 2>&1; then \
         mv "$(command -v "${bin}")" "/usr/local/bin/${bin}-real"; \
       fi; \
     done \
  && cat <<'PY' > /usr/local/bin/chroma-mcp \
  && cp /usr/local/bin/chroma-mcp /usr/local/bin/chromadb-mcp \
  && chmod +x /usr/local/bin/chroma-mcp /usr/local/bin/chromadb-mcp
#!/usr/local/bin/python
import builtins
import sys
from typing import Any

_orig_print = builtins.print

def _stderr_print(*args, **kwargs):
    kwargs["file"] = sys.stderr
    return _orig_print(*args, **kwargs)

builtins.print = _stderr_print

import numpy as np
from chromadb.api.models.CollectionCommon import CollectionCommon


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json_safe(item) for key, item in value.items()}
    return value


def _patch_chromadb_serialization() -> None:
    original_peek = CollectionCommon._transform_peek_response
    original_get = CollectionCommon._transform_get_response

    def patched_peek(self, response):  # type: ignore[no-untyped-def]
        return _to_json_safe(original_peek(self, response))

    def patched_get(self, response, include):  # type: ignore[no-untyped-def]
        return _to_json_safe(original_get(self, response, include))

    CollectionCommon._transform_peek_response = patched_peek
    CollectionCommon._transform_get_response = patched_get

    if hasattr(CollectionCommon, "_transform_query_response"):
        original_query = CollectionCommon._transform_query_response

        def patched_query(self, response, include):  # type: ignore[no-untyped-def]
            return _to_json_safe(original_query(self, response, include))

        CollectionCommon._transform_query_response = patched_query


_patch_chromadb_serialization()

import chroma_mcp.server as server

server.main()
PY
