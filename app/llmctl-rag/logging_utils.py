from __future__ import annotations

import contextvars
import json
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator


_log_sink: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar(
    "log_sink", default=None
)


@contextmanager
def log_sink(sink: Callable[[str], None]) -> Iterator[None]:
    token = _log_sink.set(sink)
    try:
        yield
    finally:
        _log_sink.reset(token)


def _format_event(event: str, fields: dict[str, Any]) -> str:
    message = fields.get("message")
    if isinstance(message, str) and message.strip():
        return message
    parts: list[str] = []
    for key, value in fields.items():
        if key == "message":
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            parts.append(f"{key}={value}")
    if parts:
        return f"{event}: " + " ".join(parts)
    return event


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "event": event,
        "ts": time.time(),
        **fields,
    }
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()

    sink = _log_sink.get()
    if sink is not None:
        try:
            sink(_format_event(event, fields))
        except Exception:
            pass
