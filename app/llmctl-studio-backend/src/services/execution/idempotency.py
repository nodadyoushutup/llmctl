from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading
import time

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from core.db import session_scope
from core.models import RuntimeIdempotencyKey

_IDEMPOTENCY_TTL_SECONDS = 24 * 3600
_dispatch_lock = threading.Lock()
_dispatch_registry: dict[tuple[int, str], float] = {}
_runtime_lock = threading.Lock()
_runtime_registry: dict[tuple[str, str], float] = {}

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _register_dispatch_key_in_memory(execution_id: int, provider_dispatch_id: str) -> bool:
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


def _register_dispatch_key_in_db(
    execution_id: int,
    provider_dispatch_id: str,
) -> bool | None:
    scope = f"execution_dispatch:{int(execution_id)}"
    normalized_key = str(provider_dispatch_id or "").strip()
    if not normalized_key:
        return False

    now = _utcnow()
    cutoff = now - timedelta(seconds=int(_IDEMPOTENCY_TTL_SECONDS))
    try:
        with session_scope() as session:
            session.execute(
                delete(RuntimeIdempotencyKey).where(
                    RuntimeIdempotencyKey.last_seen_at <= cutoff
                )
            )
            existing = (
                session.execute(
                    select(RuntimeIdempotencyKey)
                    .where(
                        RuntimeIdempotencyKey.scope == scope,
                        RuntimeIdempotencyKey.idempotency_key == normalized_key,
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if existing is not None:
                existing.last_seen_at = now
                existing.hit_count = int(existing.hit_count or 0) + 1
                return False
            RuntimeIdempotencyKey.create(
                session,
                scope=scope,
                idempotency_key=normalized_key,
                first_seen_at=now,
                last_seen_at=now,
                hit_count=1,
            )
            return True
    except IntegrityError:
        return False
    except Exception:
        logger.debug("Dispatch idempotency DB path unavailable; using in-memory fallback.")
        return None


def register_dispatch_key(execution_id: int, provider_dispatch_id: str) -> bool:
    db_result = _register_dispatch_key_in_db(execution_id, provider_dispatch_id)
    if isinstance(db_result, bool):
        return db_result
    return _register_dispatch_key_in_memory(execution_id, provider_dispatch_id)


def _register_runtime_key_in_memory(scope: str, idempotency_key: str) -> bool:
    normalized_scope = str(scope or "").strip().lower()
    normalized_key = str(idempotency_key or "").strip()
    if not normalized_scope or not normalized_key:
        return False
    key = (normalized_scope, normalized_key)
    now = time.time()
    cutoff = now - float(_IDEMPOTENCY_TTL_SECONDS)
    with _runtime_lock:
        stale = [item for item, ts in _runtime_registry.items() if ts <= cutoff]
        for item in stale:
            _runtime_registry.pop(item, None)
        if key in _runtime_registry:
            return False
        _runtime_registry[key] = now
        return True


def _register_runtime_key_in_db(scope: str, idempotency_key: str) -> bool | None:
    normalized_scope = str(scope or "").strip().lower()
    normalized_key = str(idempotency_key or "").strip()
    if not normalized_scope or not normalized_key:
        return False

    now = _utcnow()
    cutoff = now - timedelta(seconds=int(_IDEMPOTENCY_TTL_SECONDS))
    try:
        with session_scope() as session:
            session.execute(
                delete(RuntimeIdempotencyKey).where(
                    RuntimeIdempotencyKey.last_seen_at <= cutoff
                )
            )
            existing = (
                session.execute(
                    select(RuntimeIdempotencyKey)
                    .where(
                        RuntimeIdempotencyKey.scope == normalized_scope,
                        RuntimeIdempotencyKey.idempotency_key == normalized_key,
                    )
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if existing is not None:
                existing.last_seen_at = now
                existing.hit_count = int(existing.hit_count or 0) + 1
                return False
            RuntimeIdempotencyKey.create(
                session,
                scope=normalized_scope,
                idempotency_key=normalized_key,
                first_seen_at=now,
                last_seen_at=now,
                hit_count=1,
            )
            return True
    except IntegrityError:
        return False
    except Exception:
        logger.debug("Runtime idempotency DB path unavailable; using in-memory fallback.")
        return None


def register_runtime_idempotency_key(scope: str, idempotency_key: str) -> bool:
    db_result = _register_runtime_key_in_db(scope, idempotency_key)
    if isinstance(db_result, bool):
        return db_result
    return _register_runtime_key_in_memory(scope, idempotency_key)


def clear_dispatch_registry() -> None:
    with _dispatch_lock:
        _dispatch_registry.clear()
    with _runtime_lock:
        _runtime_registry.clear()
    try:
        with session_scope() as session:
            session.execute(
                delete(RuntimeIdempotencyKey).where(
                    RuntimeIdempotencyKey.scope.like("execution_dispatch:%")
                )
            )
    except Exception:
        logger.debug("Dispatch idempotency DB clear skipped; session unavailable.")
