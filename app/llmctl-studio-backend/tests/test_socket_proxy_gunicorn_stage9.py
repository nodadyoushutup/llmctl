from __future__ import annotations

import importlib
import os
import sys
import unittest
from multiprocessing import cpu_count
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify, request, url_for
from flask_socketio import SocketIO

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.execution.contracts import (  # noqa: E402
    ExecutionRequest,
)
from services.realtime_events import normalize_runtime_metadata  # noqa: E402
from web.app import _configure_proxy_middleware  # noqa: E402
from web.realtime import (  # noqa: E402
    REALTIME_NAMESPACE,
    _default_message_queue_url,
    init_socketio,
    realtime_status_payload,
    socketio,
)
import web.realtime as realtime_module  # noqa: E402

BASE_TEMPLATE = STUDIO_SRC / "web" / "templates" / "base.html"
GUNICORN_ENV_KEYS = [
    "FLASK_HOST",
    "FLASK_PORT",
    "GUNICORN_BIND",
    "GUNICORN_WORKERS",
    "GUNICORN_THREADS",
    "GUNICORN_WORKER_CLASS",
    "GUNICORN_WORKER_CONNECTIONS",
    "GUNICORN_TIMEOUT",
    "GUNICORN_GRACEFUL_TIMEOUT",
    "GUNICORN_KEEPALIVE",
    "GUNICORN_LOG_LEVEL",
    "GUNICORN_ACCESS_LOG",
    "GUNICORN_ERROR_LOG",
    "GUNICORN_MAX_REQUESTS",
    "GUNICORN_MAX_REQUESTS_JITTER",
    "GUNICORN_CERTFILE",
    "GUNICORN_KEYFILE",
    "GUNICORN_CA_CERTS",
    "GUNICORN_CONTROL_SOCKET",
    "GUNICORN_CONTROL_SOCKET_MODE",
    "GUNICORN_CONTROL_SOCKET_DISABLE",
]


class GunicornConfigStage9Tests(unittest.TestCase):
    def _reload_module(self, overrides: dict[str, str]) -> object:
        import web.gunicorn_config as gunicorn_config

        next_env = os.environ.copy()
        for key in GUNICORN_ENV_KEYS:
            next_env.pop(key, None)
        next_env.update(overrides)
        with patch.dict(os.environ, next_env, clear=True):
            return importlib.reload(gunicorn_config)

    def test_defaults_apply_when_env_is_unset(self) -> None:
        module = self._reload_module({})
        expected_workers = max(2, min(8, (max(1, cpu_count()) * 2) + 1))
        self.assertEqual("0.0.0.0:5055", module.bind)
        self.assertEqual(expected_workers, module.workers)
        self.assertEqual(4, module.threads)
        self.assertEqual("gthread", module.worker_class)
        self.assertEqual(1000, module.worker_connections)
        self.assertEqual(120, module.timeout)
        self.assertEqual(30, module.graceful_timeout)
        self.assertEqual(5, module.keepalive)
        self.assertEqual("info", module.loglevel)
        self.assertEqual("-", module.accesslog)
        self.assertEqual("-", module.errorlog)
        self.assertEqual(1000, module.max_requests)
        self.assertEqual(100, module.max_requests_jitter)
        self.assertIsNone(module.certfile)
        self.assertIsNone(module.keyfile)
        self.assertIsNone(module.ca_certs)
        self.assertEqual("/tmp/gunicorn.ctl", module.control_socket)
        self.assertEqual(0o660, module.control_socket_mode)
        self.assertFalse(module.control_socket_disable)

    def test_env_overrides_and_invalid_values_fallback(self) -> None:
        module = self._reload_module(
            {
                "FLASK_HOST": "127.0.0.1",
                "FLASK_PORT": "6000",
                "GUNICORN_BIND": "0.0.0.0:9090",
                "GUNICORN_WORKERS": "3",
                "GUNICORN_THREADS": "0",
                "GUNICORN_WORKER_CLASS": "sync",
                "GUNICORN_WORKER_CONNECTIONS": "200",
                "GUNICORN_TIMEOUT": "abc",
                "GUNICORN_GRACEFUL_TIMEOUT": "45",
                "GUNICORN_KEEPALIVE": "-1",
                "GUNICORN_LOG_LEVEL": "debug",
                "GUNICORN_ACCESS_LOG": "/tmp/access.log",
                "GUNICORN_ERROR_LOG": "/tmp/error.log",
                "GUNICORN_MAX_REQUESTS": "0",
                "GUNICORN_MAX_REQUESTS_JITTER": "-9",
                "GUNICORN_CERTFILE": "/tls/cert.pem",
                "GUNICORN_KEYFILE": "/tls/key.pem",
                "GUNICORN_CA_CERTS": "/tls/ca.pem",
                "GUNICORN_CONTROL_SOCKET": "/var/run/llmctl-studio/gunicorn.ctl",
                "GUNICORN_CONTROL_SOCKET_MODE": "invalid",
                "GUNICORN_CONTROL_SOCKET_DISABLE": "true",
            }
        )
        self.assertEqual("0.0.0.0:9090", module.bind)
        self.assertEqual(3, module.workers)
        self.assertEqual(4, module.threads)
        self.assertEqual("sync", module.worker_class)
        self.assertEqual(200, module.worker_connections)
        self.assertEqual(120, module.timeout)
        self.assertEqual(45, module.graceful_timeout)
        self.assertEqual(5, module.keepalive)
        self.assertEqual("debug", module.loglevel)
        self.assertEqual("/tmp/access.log", module.accesslog)
        self.assertEqual("/tmp/error.log", module.errorlog)
        self.assertEqual(1000, module.max_requests)
        self.assertEqual(100, module.max_requests_jitter)
        self.assertEqual("/tls/cert.pem", module.certfile)
        self.assertEqual("/tls/key.pem", module.keyfile)
        self.assertEqual("/tls/ca.pem", module.ca_certs)
        self.assertEqual("/var/run/llmctl-studio/gunicorn.ctl", module.control_socket)
        self.assertEqual(0o660, module.control_socket_mode)
        self.assertTrue(module.control_socket_disable)

    def test_control_socket_falls_back_when_configured_path_is_unwritable(self) -> None:
        def fake_access(path: object, mode: int) -> bool:
            if str(path) == "/app":
                return False
            return True

        with patch("pathlib.Path.mkdir"), patch("os.access", side_effect=fake_access):
            module = self._reload_module(
                {
                    "GUNICORN_CONTROL_SOCKET": "/app/gunicorn.ctl",
                    "GUNICORN_CONTROL_SOCKET_DISABLE": "false",
                }
            )
        self.assertEqual("/tmp/gunicorn.ctl", module.control_socket)
        self.assertFalse(module.control_socket_disable)

    def test_control_socket_auto_disables_when_no_usable_path_exists(self) -> None:
        def fake_access(path: object, mode: int) -> bool:
            if str(path) in {"/app", "/tmp"}:
                return False
            return True

        with patch("pathlib.Path.mkdir"), patch("os.access", side_effect=fake_access):
            module = self._reload_module(
                {
                    "GUNICORN_CONTROL_SOCKET": "/app/gunicorn.ctl",
                    "GUNICORN_CONTROL_SOCKET_DISABLE": "false",
                }
            )
        self.assertEqual("/app/gunicorn.ctl", module.control_socket)
        self.assertTrue(module.control_socket_disable)


class ProxyFixStage9Tests(unittest.TestCase):
    def _build_app(self, *, proxy_fix_enabled: bool) -> Flask:
        app = Flask(__name__)
        app.config.update(
            PROXY_FIX_ENABLED=proxy_fix_enabled,
            PROXY_FIX_X_FOR=1,
            PROXY_FIX_X_PROTO=1,
            PROXY_FIX_X_HOST=1,
            PROXY_FIX_X_PORT=1,
            PROXY_FIX_X_PREFIX=1,
        )
        _configure_proxy_middleware(app)

        @app.get("/whoami")
        def whoami():
            return jsonify(
                {
                    "scheme": request.scheme,
                    "host": request.host,
                    "script_root": request.script_root,
                    "url": url_for("whoami", _external=True),
                }
            )

        return app

    def test_forwarded_headers_are_applied_when_proxy_fix_enabled(self) -> None:
        app = self._build_app(proxy_fix_enabled=True)
        client = app.test_client()
        response = client.get(
            "/whoami",
            base_url="http://internal.local:5055",
            headers={
                "X-Forwarded-For": "203.0.113.10",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "studio.example.com",
                "X-Forwarded-Port": "443",
                "X-Forwarded-Prefix": "/studio",
            },
        )
        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("https", payload["scheme"])
        self.assertEqual("studio.example.com", payload["host"])
        self.assertEqual("/studio", payload["script_root"])
        self.assertEqual("https://studio.example.com/studio/whoami", payload["url"])

    def test_forwarded_headers_are_ignored_when_proxy_fix_disabled(self) -> None:
        app = self._build_app(proxy_fix_enabled=False)
        client = app.test_client()
        response = client.get(
            "/whoami",
            base_url="http://internal.local:5055",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "studio.example.com",
                "X-Forwarded-Port": "443",
                "X-Forwarded-Prefix": "/studio",
            },
        )
        payload = response.get_json()
        self.assertEqual(200, response.status_code)
        self.assertEqual("http", payload["scheme"])
        self.assertEqual("internal.local:5055", payload["host"])
        self.assertEqual("", payload["script_root"])
        self.assertEqual("http://internal.local:5055/whoami", payload["url"])


class SocketIOStage9Tests(unittest.TestCase):
    def _build_app(self, *, queue_url: str | None = None) -> Flask:
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY="stage9",
            SOCKETIO_ASYNC_MODE="threading",
            SOCKETIO_MESSAGE_QUEUE=queue_url or "",
            SOCKETIO_CORS_ALLOWED_ORIGINS="*",
            SOCKETIO_PATH="socket.io",
            SOCKETIO_LOGGER=False,
            SOCKETIO_ENGINEIO_LOGGER=False,
            SOCKETIO_PING_INTERVAL=25.0,
            SOCKETIO_PING_TIMEOUT=60.0,
            SOCKETIO_MONITOR_CLIENTS=True,
            SOCKETIO_TRANSPORTS="websocket,polling",
        )
        init_socketio(app)
        return app

    @staticmethod
    def _ack_payload(raw_ack: object) -> dict[str, object]:
        if isinstance(raw_ack, dict):
            return raw_ack
        if isinstance(raw_ack, list) and raw_ack and isinstance(raw_ack[0], dict):
            return raw_ack[0]
        return {}

    def _build_local_socketio_app(self) -> tuple[Flask, SocketIO]:
        app = Flask(__name__)
        app.config.update(SECRET_KEY="stage9")
        local_socketio = SocketIO(
            async_mode="threading",
            cors_allowed_origins="*",
            path="socket.io",
            transports=["websocket", "polling"],
        )
        local_socketio.init_app(app)
        local_socketio.on_event(
            "connect",
            realtime_module._on_connect,
            namespace=REALTIME_NAMESPACE,
        )
        local_socketio.on_event(
            "disconnect",
            realtime_module._on_disconnect,
            namespace=REALTIME_NAMESPACE,
        )
        local_socketio.on_event(
            "rt.health",
            realtime_module._on_health,
            namespace=REALTIME_NAMESPACE,
        )
        local_socketio.on_event(
            "rt.subscribe",
            realtime_module._on_subscribe,
            namespace=REALTIME_NAMESPACE,
        )
        local_socketio.on_event(
            "rt.unsubscribe",
            realtime_module._on_unsubscribe,
            namespace=REALTIME_NAMESPACE,
        )
        return app, local_socketio

    def test_lifecycle_health_and_room_subscription_flow(self) -> None:
        app, local_socketio = self._build_local_socketio_app()
        client = local_socketio.test_client(app, namespace=REALTIME_NAMESPACE)
        self.assertTrue(client.is_connected(namespace=REALTIME_NAMESPACE))

        connected_events = [
            item
            for item in client.get_received(namespace=REALTIME_NAMESPACE)
            if item.get("name") == "rt.connected"
        ]
        self.assertGreaterEqual(len(connected_events), 1)
        connected_payload = (connected_events[0].get("args") or [{}])[0]
        self.assertEqual(True, connected_payload.get("ok"))
        self.assertEqual(REALTIME_NAMESPACE, connected_payload.get("namespace"))

        health_ack = self._ack_payload(
            client.emit(
                "rt.health",
                {"probe": "stage9"},
                namespace=REALTIME_NAMESPACE,
                callback=True,
            )
        )
        self.assertEqual(True, health_ack.get("ok"))
        self.assertEqual({"probe": "stage9"}, health_ack.get("echo"))

        subscribe_ack = self._ack_payload(
            client.emit(
                "rt.subscribe",
                {"rooms": ["task:9", "task:9", "bad", "thread:abc"]},
                namespace=REALTIME_NAMESPACE,
                callback=True,
            )
        )
        self.assertEqual(True, subscribe_ack.get("ok"))
        self.assertEqual(["task:9", "thread:abc"], subscribe_ack.get("rooms"))

        local_socketio.emit(
            "node.task.updated",
            {"status": "running"},
            room="task:9",
            namespace=REALTIME_NAMESPACE,
        )
        room_events = [
            item
            for item in client.get_received(namespace=REALTIME_NAMESPACE)
            if item.get("name") == "node.task.updated"
        ]
        self.assertEqual(1, len(room_events))
        self.assertEqual(
            {"status": "running"},
            (room_events[0].get("args") or [{}])[0],
        )

        unsubscribe_ack = self._ack_payload(
            client.emit(
                "rt.unsubscribe",
                {"rooms": ["task:9"]},
                namespace=REALTIME_NAMESPACE,
                callback=True,
            )
        )
        self.assertEqual(True, unsubscribe_ack.get("ok"))
        self.assertEqual(["task:9"], unsubscribe_ack.get("rooms"))

        local_socketio.emit(
            "node.task.updated",
            {"status": "completed"},
            room="task:9",
            namespace=REALTIME_NAMESPACE,
        )
        post_unsubscribe = [
            item
            for item in client.get_received(namespace=REALTIME_NAMESPACE)
            if item.get("name") == "node.task.updated"
        ]
        self.assertEqual(0, len(post_unsubscribe))

        before_disconnect = realtime_status_payload()["metrics"]["disconnect_total"]
        client.disconnect(namespace=REALTIME_NAMESPACE)
        after_disconnect = realtime_status_payload()["metrics"]["disconnect_total"]
        self.assertGreaterEqual(after_disconnect, before_disconnect + 1)

    def test_init_socketio_passes_redis_message_queue(self) -> None:
        app = Flask(__name__)
        app.config.update(
            SOCKETIO_ASYNC_MODE="threading",
            SOCKETIO_MESSAGE_QUEUE="redis://redis.internal:6379/0",
            SOCKETIO_CORS_ALLOWED_ORIGINS="*",
            SOCKETIO_PATH="socket.io",
            SOCKETIO_LOGGER=False,
            SOCKETIO_ENGINEIO_LOGGER=False,
            SOCKETIO_PING_INTERVAL=25.0,
            SOCKETIO_PING_TIMEOUT=60.0,
            SOCKETIO_MONITOR_CLIENTS=True,
            SOCKETIO_TRANSPORTS="websocket,polling",
        )
        with patch.object(socketio, "init_app") as mocked_init_app:
            init_socketio(app)
        self.assertTrue(mocked_init_app.called)
        _, kwargs = mocked_init_app.call_args
        self.assertEqual("redis://redis.internal:6379/0", kwargs["message_queue"])
        self.assertEqual("socket.io", kwargs["path"])
        self.assertEqual(["websocket", "polling"], kwargs["transports"])

    def test_default_message_queue_url_reuses_celery_redis_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLMCTL_STUDIO_SOCKETIO_MESSAGE_QUEUE": "",
                "CELERY_REDIS_HOST": "redis.service",
                "CELERY_REDIS_PORT": "6390",
                "CELERY_REDIS_BROKER_DB": "8",
            },
            clear=True,
        ):
            queue_url = _default_message_queue_url()
        self.assertEqual("redis://redis.service:6390/8", queue_url)


class SocketFallbackStage9Tests(unittest.TestCase):
    def test_fallback_only_triggers_on_verified_socket_failures(self) -> None:
        source = BASE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('triggerFailure("socket_connect_timeout")', source)
        self.assertIn('triggerFailure("socket_disconnected_before_ready")', source)
        self.assertIn('triggerFailure("socket_disconnected")', source)
        self.assertIn("window.setTimeout(() => {", source)
        self.assertIn("}, 5000);", source)
        self.assertIn("}, 3000);", source)

        connect_error_start = source.index('socket.on("connect_error", () => {')
        connect_error_end = source.index('socket.onAny((eventName, payload) => {')
        connect_error_block = source[connect_error_start:connect_error_end]
        self.assertNotIn("triggerFailure(", connect_error_block)
        self.assertIn("Wait for connection timeout window before failing over to polling", source)


class RuntimeParityStage9Tests(unittest.TestCase):
    def test_runtime_metadata_schema_is_consistent_for_kubernetes_execution(self) -> None:
        direct_payload = normalize_runtime_metadata(
            ExecutionRequest(
                node_id=1,
                node_type="agent",
                node_ref_id=None,
                node_config={},
                input_context={},
                execution_id=11,
                execution_task_id=None,
                execution_index=0,
                enabled_providers={"kubernetes"},
                default_model_id=None,
                mcp_server_keys=[],
                selected_provider="kubernetes",
                final_provider="kubernetes",
            ).run_metadata_payload()
        )
        failed_dispatch_payload = normalize_runtime_metadata(
            ExecutionRequest(
                node_id=1,
                node_type="agent",
                node_ref_id=None,
                node_config={},
                input_context={},
                execution_id=12,
                execution_task_id=None,
                execution_index=0,
                enabled_providers={"kubernetes"},
                default_model_id=None,
                mcp_server_keys=[],
                selected_provider="kubernetes",
                final_provider="kubernetes",
                fallback_attempted=False,
                fallback_reason=None,
                dispatch_uncertain=False,
                api_failure_category="api_unreachable",
                cli_fallback_used=False,
                cli_preflight_passed=None,
            ).run_metadata_payload()
        )

        expected_keys = {
            "selected_provider",
            "final_provider",
            "provider_dispatch_id",
            "workspace_identity",
            "dispatch_status",
            "fallback_attempted",
            "fallback_reason",
            "dispatch_uncertain",
            "api_failure_category",
            "cli_fallback_used",
            "cli_preflight_passed",
        }
        self.assertIsNotNone(direct_payload)
        self.assertIsNotNone(failed_dispatch_payload)
        assert direct_payload is not None
        assert failed_dispatch_payload is not None
        self.assertEqual(expected_keys, set(direct_payload.keys()))
        self.assertEqual(expected_keys, set(failed_dispatch_payload.keys()))
        self.assertEqual("kubernetes", direct_payload["selected_provider"])
        self.assertEqual("kubernetes", direct_payload["final_provider"])
        self.assertEqual("kubernetes", failed_dispatch_payload["selected_provider"])
        self.assertEqual("kubernetes", failed_dispatch_payload["final_provider"])


if __name__ == "__main__":
    unittest.main()
