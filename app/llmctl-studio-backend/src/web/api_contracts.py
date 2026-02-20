from __future__ import annotations

import uuid
from typing import Any

from flask import Request

from services.runtime_contracts import API_ERROR_CONTRACT_VERSION


def request_id_from_request(req: Request) -> str:
    request_id = str(
        req.headers.get("X-Request-ID")
        or req.headers.get("X-Request-Id")
        or req.args.get("request_id")
        or ""
    ).strip()
    return request_id or uuid.uuid4().hex


def correlation_id_from_request(req: Request) -> str | None:
    correlation_id = str(
        req.headers.get("X-Correlation-ID")
        or req.headers.get("X-Correlation-Id")
        or req.args.get("correlation_id")
        or ""
    ).strip()
    return correlation_id or None


def build_api_error_envelope(
    *,
    code: str,
    message: str,
    details: dict[str, object] | None,
    request_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error": {
            "contract_version": API_ERROR_CONTRACT_VERSION,
            "code": str(code),
            "message": str(message),
            "details": details or {},
            "request_id": str(request_id),
        },
    }
    if correlation_id:
        payload["correlation_id"] = str(correlation_id)
    return payload
