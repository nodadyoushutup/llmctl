#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import selectors
import subprocess
import sys
from datetime import datetime, timezone
from typing import IO


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stdio tap that logs MCP traffic while proxying to a child process.",
    )
    parser.add_argument(
        "--log",
        default=os.getenv("MCP_STDIO_TAP_LOG", "/app/data/mcp-stdio-tap.log"),
        help="Log file path (default: /app/data/mcp-stdio-tap.log).",
    )
    parser.add_argument(
        "--max-line-bytes",
        type=int,
        default=20000,
        help="Max bytes to log per line (default: 20000).",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command to execute (pass after --).",
    )
    return parser.parse_args()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write_line(log: IO[str], direction: str, data: bytes, max_bytes: int) -> None:
    if max_bytes > 0 and len(data) > max_bytes:
        data = data[:max_bytes] + b"...<truncated>"
    text = data.decode("utf-8", "replace")
    log.write(f"{_timestamp()} {direction} {text}\n")
    log.flush()


def _drain_buffer(
    log: IO[str], direction: str, buffer: bytearray, max_bytes: int
) -> None:
    while True:
        newline_index = buffer.find(b"\n")
        if newline_index == -1:
            break
        line = bytes(buffer[:newline_index])
        del buffer[: newline_index + 1]
        if line:
            _write_line(log, direction, line, max_bytes)


def _log_chunk(
    log: IO[str], direction: str, buffer: bytearray, chunk: bytes, max_bytes: int
) -> None:
    buffer.extend(chunk)
    _drain_buffer(log, direction, buffer, max_bytes)


def main() -> int:
    args = _parse_args()
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("ERROR: Missing command. Use -- <command> ...", file=sys.stderr)
        return 2

    log_path = args.log
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(f"{_timestamp()} START {' '.join(cmd)}\n")
        log.flush()

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )

        if proc.stdin is None or proc.stdout is None:
            print("ERROR: Failed to attach stdio to child process.", file=sys.stderr)
            return 3

        sel = selectors.DefaultSelector()
        sel.register(sys.stdin.buffer, selectors.EVENT_READ, data="in")
        sel.register(proc.stdout, selectors.EVENT_READ, data="out")

        in_buffer = bytearray()
        out_buffer = bytearray()

        try:
            while True:
                if proc.poll() is not None and not sel.get_map():
                    break
                events = sel.select(timeout=0.2)
                if not events:
                    if proc.poll() is not None:
                        break
                    continue
                for key, _ in events:
                    if key.data == "in":
                        chunk = os.read(sys.stdin.fileno(), 65536)
                        if not chunk:
                            sel.unregister(sys.stdin.buffer)
                            proc.stdin.close()
                            continue
                        proc.stdin.write(chunk)
                        proc.stdin.flush()
                        _log_chunk(log, "IN", in_buffer, chunk, args.max_line_bytes)
                    else:
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            sel.unregister(proc.stdout)
                            break
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                        _log_chunk(log, "OUT", out_buffer, chunk, args.max_line_bytes)
        finally:
            if in_buffer:
                _write_line(log, "IN", bytes(in_buffer), args.max_line_bytes)
            if out_buffer:
                _write_line(log, "OUT", bytes(out_buffer), args.max_line_bytes)
            log.write(f"{_timestamp()} EXIT {proc.poll()}\n")
            log.flush()

        return int(proc.poll() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
