#!/usr/bin/env python3
"""Lightweight HTTP proxy to log Gemini MCP requests and responses.

Usage:
  python3 debug_mcp_proxy.py \
    --listen-host 0.0.0.0 --listen-port 9900 \
    --upstream http://192.168.1.36:9000

Then point Gemini MCP URL to: http://192.168.1.36:9900/mcp
"""
from __future__ import annotations

import argparse
import json
import http.client
import io
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream: urlparse
    body_limit: int
    mode: str
    sessions: dict[str, str] = {}
    keepalive_seconds: float = 10.0
    keepalive_interval: float = 2.0
    prelude_comment: str = ": connected"
    use_chunked: bool = True

    def _log(self, msg: str) -> None:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if not length:
            return b""
        try:
            size = int(length)
        except ValueError:
            return b""
        return self.rfile.read(size)

    def _extract_json(self, payload: bytes) -> dict | None:
        text = payload.decode("utf-8", "replace")
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        for line in text.splitlines():
            candidate = line.strip()
            if candidate.startswith("data:"):
                candidate = candidate[5:].strip()
            if not candidate:
                continue
            if not candidate.startswith("{"):
                continue
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    def _join_upstream_path(self, path: str) -> str:
        base_path = self.upstream.path or ""
        if base_path in {"", "/"}:
            return path
        if base_path.endswith("/") and path.startswith("/"):
            return base_path[:-1] + path
        if not base_path.endswith("/") and not path.startswith("/"):
            return base_path + "/" + path
        return base_path + path

    def _forward(self) -> None:
        body = self._read_body()
        body_preview = body[: self.body_limit]
        truncated = b"" if len(body) <= self.body_limit else b"..."

        self._log(
            f"\n=== Incoming {self.command} {self.path} ===\n"
            f"Headers: {dict(self.headers)}\n"
            f"Body({len(body)}): {body_preview!r}{truncated.decode('utf-8', 'ignore')}"
        )

        conn = http.client.HTTPConnection(self.upstream.hostname, self.upstream.port)
        # Copy headers, but fix Host and remove hop-by-hop headers
        headers = {k: v for k, v in self.headers.items()}
        headers["Host"] = f"{self.upstream.hostname}:{self.upstream.port}"
        for hop in (
            "Connection",
            "Keep-Alive",
            "Proxy-Authenticate",
            "Proxy-Authorization",
            "TE",
            "Trailers",
            "Transfer-Encoding",
            "Upgrade",
        ):
            headers.pop(hop, None)

        if (
            self.mode == "gemini-sse-bridge"
            and self.command == "POST"
            and not any(k.lower() == "mcp-session-id" for k in headers)
        ):
            session_id = self.sessions.get(self.client_address[0])
            if session_id:
                headers["Mcp-Session-Id"] = session_id
                self._log(f"Injected Mcp-Session-Id for {self.client_address[0]}: {session_id}")

        upstream_path = self._join_upstream_path(self.path)

        conn.request(self.command, upstream_path, body=body if body else None, headers=headers)
        resp = conn.getresponse()

        self.send_response(resp.status, resp.reason)
        for key, value in resp.getheaders():
            if key.lower() == "transfer-encoding" and value.lower() == "chunked":
                continue
            self.send_header(key, value)
        self.end_headers()

        self._log(f"Upstream response: {resp.status} {resp.reason}")

        # Stream response to client, while capturing a preview
        preview = io.BytesIO()
        max_preview = self.body_limit
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
            if preview.tell() < max_preview:
                preview.write(chunk[: max_preview - preview.tell()])
        if preview.tell():
            self._log(f"Response preview({preview.tell()}): {preview.getvalue()!r}")
        conn.close()

    def _handle_gemini_sse_bridge(self) -> None:
        upstream_path = self._join_upstream_path(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        if self.use_chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        self.close_connection = False
        if self.prelude_comment:
            self._write_sse(f"{self.prelude_comment}\r\n\r\n")
            self._log("Sent SSE prelude.")

        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "gemini-sse-bridge", "version": "0"},
                "capabilities": {},
            },
        }
        conn = http.client.HTTPConnection(self.upstream.hostname, self.upstream.port)
        conn.request("POST", upstream_path, body=json.dumps(init_payload), headers=headers)
        init_resp = conn.getresponse()
        init_body = init_resp.read()
        init_json = self._extract_json(init_body)
        session_id = None
        for key, value in init_resp.getheaders():
            if key.lower() == "mcp-session-id":
                session_id = value
                break
        if session_id:
            self.sessions[self.client_address[0]] = session_id
        self._log(f"Upstream initialize: {init_resp.status} {init_resp.reason}")
        if init_json is None:
            self._log(f"Initialize body preview: {init_body[: self.body_limit]!r}")
        conn.close()

        if init_resp.status != 200:
            error = {
                "jsonrpc": "2.0",
                "id": "server-error",
                "error": {
                    "code": -32600,
                    "message": f"Upstream initialize failed: {init_resp.status} {init_resp.reason}",
                },
            }
            self._write_sse(f"data: {json.dumps(error)}\r\n\r\n")
            self._log("Sent SSE error for initialize.")
            return

        if init_json is not None:
            self._write_sse(f"data: {json.dumps(init_json)}\r\n\r\n")
            self._log("Sent SSE initialize event.")

        conn = http.client.HTTPConnection(self.upstream.hostname, self.upstream.port)
        tools_headers = dict(headers)
        if session_id:
            tools_headers["Mcp-Session-Id"] = session_id
        tools_payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        conn.request("POST", upstream_path, body=json.dumps(tools_payload), headers=tools_headers)
        tools_resp = conn.getresponse()
        tools_body = tools_resp.read()
        tools_json = self._extract_json(tools_body)
        self._log(f"Upstream tools/list: {tools_resp.status} {tools_resp.reason}")
        if tools_json is None:
            self._log(f"tools/list body preview: {tools_body[: self.body_limit]!r}")
        conn.close()

        if tools_resp.status != 200:
            error = {
                "jsonrpc": "2.0",
                "id": "server-error",
                "error": {
                    "code": -32600,
                    "message": f"Upstream tools/list failed: {tools_resp.status} {tools_resp.reason}",
                },
            }
            self._write_sse(f"data: {json.dumps(error)}\r\n\r\n")
            self._log("Sent SSE error for tools/list.")
            return

        if tools_json is not None:
            self._write_sse(f"data: {json.dumps(tools_json)}\r\n\r\n")
            self._log("Sent SSE tools/list event.")

        end_at = time.time() + self.keepalive_seconds
        while time.time() < end_at:
            try:
                self._write_sse(": keep-alive\r\n\r\n")
                self._log("Sent SSE keep-alive.")
                time.sleep(self.keepalive_interval)
            except BrokenPipeError:
                break

    def _write_sse(self, text: str) -> None:
        data = text.encode("utf-8")
        if self.use_chunked:
            size = f"{len(data):X}\r\n".encode("utf-8")
            self.wfile.write(size)
            self.wfile.write(data)
            self.wfile.write(b"\r\n")
        else:
            self.wfile.write(data)
        self.wfile.flush()

    def do_GET(self) -> None:  # noqa: N802
        if self.mode == "gemini-sse-bridge" and self.path.startswith("/mcp"):
            self._handle_gemini_sse_bridge()
            return
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def do_PUT(self) -> None:  # noqa: N802
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug MCP proxy logger.")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=9900)
    parser.add_argument("--upstream", required=True, help="Upstream base URL, e.g. http://192.168.1.36:9000")
    parser.add_argument("--body-limit", type=int, default=2048, help="Max bytes to log from request/response bodies")
    parser.add_argument(
        "--mode",
        choices=("proxy", "gemini-sse-bridge"),
        default="proxy",
        help="proxy: pass-through; gemini-sse-bridge: translate SSE GET to streamable-HTTP",
    )
    parser.add_argument(
        "--keepalive-seconds",
        type=float,
        default=10.0,
        help="Seconds to keep SSE connection alive after sending data (bridge mode)",
    )
    parser.add_argument(
        "--keepalive-interval",
        type=float,
        default=2.0,
        help="Seconds between keep-alive SSE comments (bridge mode)",
    )
    parser.add_argument(
        "--no-chunked",
        action="store_true",
        help="Disable Transfer-Encoding: chunked for SSE responses",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    upstream = urlparse(args.upstream)
    if not upstream.scheme or not upstream.hostname:
        print("Invalid upstream URL.", file=sys.stderr)
        return 2
    if upstream.scheme != "http":
        print("Only http upstream is supported.", file=sys.stderr)
        return 2
    if not upstream.port:
        upstream = upstream._replace(port=80)

    ProxyHandler.upstream = upstream
    ProxyHandler.body_limit = args.body_limit
    ProxyHandler.mode = args.mode
    ProxyHandler.keepalive_seconds = args.keepalive_seconds
    ProxyHandler.keepalive_interval = args.keepalive_interval
    ProxyHandler.use_chunked = not args.no_chunked

    server = ThreadingHTTPServer((args.listen_host, args.listen_port), ProxyHandler)
    print(f"Proxy listening on http://{args.listen_host}:{args.listen_port}")
    print(f"Forwarding to {upstream.geturl()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
