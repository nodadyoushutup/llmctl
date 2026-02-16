from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .contracts import (
    ERROR_INFRA,
    ExecutionResult,
    RESULT_PREFIX,
    ResultError,
    STATUS_FAILED,
    STATUS_INFRA_ERROR,
    STATUS_TIMEOUT,
    utcnow,
)
from .payload import ExecutionPayload, PayloadError, load_payload_input
from .runtime import execute_single_run


def _result_from_error(
    *,
    status: str,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> ExecutionResult:
    now = utcnow()
    return ExecutionResult(
        status=status,
        exit_code=1,
        started_at=now,
        finished_at=now,
        stdout="",
        stderr="",
        error=ResultError(code=code, message=message, details=details),
        provider_metadata={
            "executor": "llmctl-executor",
            "provider": "workspace",
            "request_id": "executor-error",
        },
    )


def _exit_code_for_result(result: ExecutionResult) -> int:
    if result.status == "success":
        return 0
    if result.status == STATUS_TIMEOUT:
        return 124
    if result.status == "cancelled":
        return 130
    if result.exit_code > 0:
        return int(result.exit_code)
    return 1


def _write_output_file(path_value: str, payload: dict[str, Any]) -> None:
    output_path = Path(path_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one llmctl executor payload.")
    parser.add_argument(
        "--payload-file",
        default="",
        help="Path to JSON payload file (overrides env input sources).",
    )
    parser.add_argument(
        "--payload-json",
        default="",
        help="Inline JSON payload string (overrides env input sources).",
    )
    parser.add_argument(
        "--output-file",
        default="",
        help=(
            "Optional path to write structured result JSON. "
            "Also honored via LLMCTL_EXECUTOR_OUTPUT_FILE."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    result: ExecutionResult
    try:
        payload_raw = load_payload_input(
            payload_file=args.payload_file,
            payload_json=args.payload_json,
        )
        payload = ExecutionPayload.from_dict(payload_raw)
        result = execute_single_run(payload)
    except PayloadError as exc:
        status = STATUS_INFRA_ERROR if exc.code == ERROR_INFRA else STATUS_FAILED
        result = _result_from_error(
            status=status,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        )
    except Exception as exc:  # pragma: no cover
        result = _result_from_error(
            status=STATUS_INFRA_ERROR,
            code=ERROR_INFRA,
            message=f"Unexpected executor failure: {exc}",
        )

    result_dict = result.as_dict()
    output_file = str(args.output_file or "").strip() or os.getenv(
        "LLMCTL_EXECUTOR_OUTPUT_FILE", ""
    ).strip()
    if output_file:
        _write_output_file(output_file, result_dict)

    print(f"{RESULT_PREFIX}{json.dumps(result_dict, sort_keys=True)}", flush=True)
    return _exit_code_for_result(result)
