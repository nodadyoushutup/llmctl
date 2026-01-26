#!/usr/bin/env python3
"""Debug MCP tool discovery over streamable-HTTP (SSE).

Usage:
  python debug_mcp_tools.py --url http://192.168.1.36:9000/mcp
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Iterable, Tuple


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug MCP tools/list via SSE.")
    parser.add_argument(
        "--url",
        default="http://localhost:9000/mcp",
        help="MCP server URL (default: http://localhost:9000/mcp)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Read timeout seconds for SSE lines (default: 10)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print raw SSE lines.",
    )
    return parser.parse_args()


def _extract_session_id(headers: dict[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "mcp-session-id":
            return value.strip()
    return None


def _extract_sse_json(lines: Iterable[str], request_id: int, verbose: bool) -> dict | None:
    for line in lines:
        if verbose:
            print(f"SSE: {line}")
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("id") == request_id:
            return data
    return None


def _request_with_requests(
    url: str,
    payload: dict,
    headers: dict[str, str],
    timeout: float,
    verbose: bool,
) -> Tuple[dict[str, str], dict | None]:
    import requests  # type: ignore

    resp = requests.post(
        url,
        headers=headers,
        json=payload,
        stream=True,
        timeout=(5, timeout),
    )
    resp.raise_for_status()
    header_map = {k: v for k, v in resp.headers.items()}

    def _lines() -> Iterable[str]:
        start = time.time()
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                yield line
            if time.time() - start > timeout:
                break

    data = _extract_sse_json(_lines(), payload.get("id"), verbose)
    return header_map, data


def _request_with_urllib(
    url: str,
    payload: dict,
    headers: dict[str, str],
    timeout: float,
    verbose: bool,
) -> Tuple[dict[str, str], dict | None]:
    import socket
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    socket.setdefaulttimeout(timeout)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        header_map = {k: v for k, v in resp.headers.items()}
        lines: list[str] = []
        start = time.time()
        while time.time() - start < timeout:
            try:
                raw = resp.readline()
            except socket.timeout:
                break
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if line:
                lines.append(line)
                if verbose:
                    print(f"SSE: {line}")
        data = _extract_sse_json(lines, payload.get("id"), verbose)
        return header_map, data


def _sse_request(
    url: str,
    payload: dict,
    headers: dict[str, str],
    timeout: float,
    verbose: bool,
) -> Tuple[dict[str, str], dict | None]:
    try:
        import requests  # noqa: F401
    except Exception:
        return _request_with_urllib(url, payload, headers, timeout, verbose)
    return _request_with_requests(url, payload, headers, timeout, verbose)


def main() -> int:
    args = _parse_args()
    url = args.url

    base_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "debug-mcp", "version": "0"},
            "capabilities": {},
        },
    }
    print(f"==> initialize: {url}")
    init_headers, init_data = _sse_request(
        url, init_payload, base_headers, args.timeout, args.verbose
    )
    session_id = _extract_session_id(init_headers)
    print(f"Mcp-Session-Id: {session_id or 'MISSING'}")
    if init_data is not None:
        print("initialize response:")
        print(json.dumps(init_data, indent=2, sort_keys=True))
    else:
        print("initialize response: <no json data received>")

    if not session_id:
        print("\nERROR: No Mcp-Session-Id header returned. Cannot query tools.")
        return 2

    tools_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
    }
    headers = dict(base_headers)
    headers["Mcp-Session-Id"] = session_id
    print(f"\n==> tools/list: {url}")
    tools_headers, tools_data = _sse_request(
        url, tools_payload, headers, args.timeout, args.verbose
    )
    if tools_data is None:
        print("tools/list response: <no json data received>")
        return 3
    print("tools/list response:")
    print(json.dumps(tools_data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
