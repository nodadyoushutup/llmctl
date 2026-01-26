#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stdio MCP smoke test client (initialize + tools/list).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Seconds to wait for each response (default: 8).",
    )
    parser.add_argument(
        "--tool-name",
        default="",
        help="Optional tool name to call after tools/list.",
    )
    parser.add_argument(
        "--tool-args",
        default="{}",
        help="JSON string of tool arguments (default: {}).",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to execute (pass after --).",
    )
    return parser.parse_args()


def _stderr_pump(stream: Any) -> None:
    for line in iter(stream.readline, ""):
        if not line:
            break
        sys.stderr.write(line)
    stream.close()


def _send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_response(
    proc: subprocess.Popen[str], request_id: int, timeout: float
) -> dict[str, Any] | None:
    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("id") == request_id:
            return data
    return None


def main() -> int:
    args = _parse_args()
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("ERROR: Missing command. Use -- <command> ...", file=sys.stderr)
        return 2

    try:
        tool_args = json.loads(args.tool_args)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON for --tool-args: {exc}", file=sys.stderr)
        return 2

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if proc.stdin is None or proc.stdout is None or proc.stderr is None:
        print("ERROR: Failed to attach stdio to child process.", file=sys.stderr)
        return 3

    stderr_thread = threading.Thread(
        target=_stderr_pump,
        args=(proc.stderr,),
        daemon=True,
    )
    stderr_thread.start()

    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "stdio-smoke-test", "version": "0"},
            "capabilities": {},
        },
    }
    _send(proc, init_payload)
    init_response = _read_response(proc, 1, args.timeout)
    if init_response is None:
        print("initialize response: <none>")
        proc.terminate()
        return 4
    print("initialize response:")
    print(json.dumps(init_response, indent=2, sort_keys=True))

    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    tools_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    _send(proc, tools_payload)
    tools_response = _read_response(proc, 2, args.timeout)
    if tools_response is None:
        print("tools/list response: <none>")
        proc.terminate()
        return 5
    print("tools/list response:")
    print(json.dumps(tools_response, indent=2, sort_keys=True))

    if args.tool_name:
        call_payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": args.tool_name, "arguments": tool_args},
        }
        _send(proc, call_payload)
        call_response = _read_response(proc, 3, args.timeout)
        if call_response is None:
            print("tools/call response: <none>")
            proc.terminate()
            return 6
        print("tools/call response:")
        print(json.dumps(call_response, indent=2, sort_keys=True))

    proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
