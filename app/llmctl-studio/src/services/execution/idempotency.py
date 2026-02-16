from __future__ import annotations

import threading
import time

_IDEMPOTENCY_TTL_SECONDS = 24 * 3600
_dispatch_lock = threading.Lock()
_dispatch_registry: dict[tuple[int, str], float] = {}


def register_dispatch_key(execution_id: int, provider_dispatch_id: str) -> bool:
    key = (int(execution_id), str(provider_dispatch_id))
    now = time.time()
    cutoff = now - float(_IDEMPOTENCY_TTL_SECONDS)
    with _dispatch_lock:
        stale = [item for item, ts in _dispatch_registry.items() if ts <= cutoff]
        for item in stale:
            _dispatch_registry.pop(item, None)
        if key in _dispatch_registry:
            return False
        _dispatch_registry[key] = now
        return True


def clear_dispatch_registry() -> None:
    with _dispatch_lock:
        _dispatch_registry.clear()
