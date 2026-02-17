from __future__ import annotations

import json
import re
from typing import Any, Iterable

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def parse_mcp_config(
    raw_config: str | dict[str, Any],
    server_key: str | None = None,
) -> dict[str, Any]:
    payload = _parse_json_payload(raw_config)
    config = _extract_server_config(payload, server_key)
    _validate_dict(config, path="config")
    return config


def format_mcp_config(
    raw_config: str | dict[str, Any],
    server_key: str,
) -> dict[str, Any]:
    return parse_mcp_config(raw_config, server_key=server_key)


def render_mcp_config(server_key: str, config: dict[str, Any]) -> dict[str, Any]:
    validate_server_key(server_key)
    _validate_dict(config, path=f"mcp_servers.{server_key}")
    return _copy_config(config)


def validate_server_key(server_key: str) -> None:
    if not _KEY_RE.fullmatch(server_key or ""):
        raise ValueError(
            "Server key must use letters, numbers, underscores, or dashes."
        )


def build_mcp_overrides(server_key: str, config: dict[str, Any]) -> list[str]:
    validate_server_key(server_key)
    prefix = f"mcp_servers.{server_key}"
    overrides: list[str] = []
    for key, value in _flatten(prefix, config):
        overrides.append(f"{key}={value}")
    return overrides


def _parse_json_payload(raw_config: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_config, dict):
        return raw_config
    if not isinstance(raw_config, str):
        raise ValueError("MCP config must be a JSON object.")
    stripped = raw_config.strip()
    if not stripped:
        raise ValueError("MCP config JSON is required.")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("MCP config must be a JSON object.")
    return payload


def _extract_server_config(
    payload: dict[str, Any], server_key: str | None
) -> dict[str, Any]:
    if "mcp_servers" in payload:
        if len(payload) != 1:
            raise ValueError("MCP config must only include the mcp_servers object.")
        mcp_servers = payload.get("mcp_servers")
        if not isinstance(mcp_servers, dict):
            raise ValueError("mcp_servers must be a JSON object.")
        if server_key is None:
            if len(mcp_servers) != 1:
                raise ValueError("MCP config must include exactly one server.")
            server_key = next(iter(mcp_servers))
        config = mcp_servers.get(server_key)
        if config is None:
            raise ValueError(f"Missing mcp_servers.{server_key} in config.")
        if not isinstance(config, dict):
            raise ValueError(f"mcp_servers.{server_key} must be a JSON object.")
        if len(mcp_servers) != 1:
            raise ValueError("MCP config must define exactly one server.")
        return config
    return payload


def _flatten(prefix: str, value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
                raise ValueError(
                    f"Invalid key '{key}'. Use letters, numbers, underscores, or dashes."
                )
            yield from _flatten(f"{prefix}.{key}", nested)
        return
    yield prefix, _override_value(value)


def _override_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return _override_string(value)
    if isinstance(value, list):
        return _override_array(value)
    raise ValueError(
        "MCP config values must be strings, numbers, booleans, or arrays."
    )


def _override_array(values: list[Any]) -> str:
    rendered = []
    for item in values:
        if isinstance(item, list) or isinstance(item, dict):
            raise ValueError("MCP config arrays must not contain objects or arrays.")
        rendered.append(_override_value(item))
    return "[" + ", ".join(rendered) + "]"


def _override_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f"\"{escaped}\""


def _validate_dict(payload: dict[str, Any], path: str) -> None:
    for key, value in payload.items():
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            raise ValueError(
                f"Invalid key '{key}' at {path}. Use letters, numbers, underscores, or dashes."
            )
        _validate_value(value, f"{path}.{key}")


def _validate_value(value: Any, path: str) -> None:
    if isinstance(value, dict):
        _validate_dict(value, path)
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            if isinstance(item, dict) or isinstance(item, list):
                raise ValueError(
                    f"Invalid array value at {path}[{idx}]. Arrays must be scalar values."
                )
            _validate_value(item, f"{path}[{idx}]")
        return
    if isinstance(value, (str, int, float, bool)):
        return
    raise ValueError(
        f"Invalid value at {path}. Use strings, numbers, booleans, or arrays."
    )


def _copy_config(value: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, nested in value.items():
        if isinstance(nested, dict):
            copied[key] = _copy_config(nested)
        elif isinstance(nested, list):
            copied[key] = list(nested)
        else:
            copied[key] = nested
    return copied
