from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import time
from typing import Any, Callable


@dataclass(slots=True, frozen=True)
class AgentInfo:
    id: int | None
    name: str
    description: str

    @classmethod
    def from_model(cls, agent: Any) -> "AgentInfo":
        raw_id = getattr(agent, "id", None)
        try:
            identifier = int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            identifier = None
        name = str(getattr(agent, "name", "") or "")
        description = str(getattr(agent, "description", "") or "").strip() or name
        return cls(id=identifier, name=name, description=description)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "description": self.description,
        }
        if self.id is not None:
            payload["id"] = self.id
        return payload


def build_agent_payload(agent: Any) -> dict[str, object]:
    return AgentInfo.from_model(agent).to_payload()


@dataclass(slots=True, frozen=True)
class FrontierAgentRequest:
    provider: str
    prompt: str | None
    mcp_configs: dict[str, dict[str, Any]]
    model_config: dict[str, Any] | None = None
    env: dict[str, str] | None = None


@dataclass(slots=True, frozen=True)
class FrontierAgentDependencies:
    provider_label: Callable[[str], str]
    codex_settings_from_model_config: Callable[[dict[str, Any]], dict[str, Any]]
    gemini_settings_from_model_config: Callable[[dict[str, Any]], dict[str, Any]]
    load_codex_auth_key: Callable[[], str]
    load_gemini_auth_key: Callable[[], str]
    resolve_claude_auth_key: Callable[[dict[str, str] | None], tuple[str, str]]
    default_codex_model: str
    default_gemini_model: str
    default_claude_model: str
    require_claude_api_key: bool


class FrontierAgent:
    """SDK-first runtime adapter for frontier providers."""

    def __init__(self, dependencies: FrontierAgentDependencies) -> None:
        self._dependencies = dependencies

    def run(
        self,
        request: FrontierAgentRequest,
        *,
        on_update: Callable[[str, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        provider = str(request.provider or "").strip().lower()
        provider_label = self._dependencies.provider_label(provider)
        prompt_text = str(request.prompt or "")
        config_map = request.model_config if isinstance(request.model_config, dict) else {}
        env_map = dict(request.env or os.environ.copy())

        if request.mcp_configs and provider != "codex":
            return self._emit_result(
                subprocess.CompletedProcess(
                    [f"sdk:{provider}"],
                    1,
                    "",
                    (
                        f"{provider_label} SDK runtime does not support MCP transport config. "
                        "MCP server wiring via CLI has been removed; unbind MCP servers for this run."
                    ),
                ),
                on_update=on_update,
            )

        def _run_once() -> subprocess.CompletedProcess[str]:
            if provider == "codex":
                return self._run_codex(
                    prompt=prompt_text,
                    mcp_configs=request.mcp_configs,
                    config_map=config_map,
                    env_map=env_map,
                    on_log=on_log,
                    provider_label=provider_label,
                )
            if provider == "gemini":
                return self._run_gemini(
                    prompt=prompt_text,
                    config_map=config_map,
                    env_map=env_map,
                    on_log=on_log,
                    provider_label=provider_label,
                )
            if provider == "claude":
                return self._run_claude(
                    prompt=prompt_text,
                    config_map=config_map,
                    env_map=env_map,
                    on_log=on_log,
                    provider_label=provider_label,
                )
            return subprocess.CompletedProcess(
                [f"sdk:{provider}"],
                1,
                "",
                f"Unknown frontier provider '{provider}'.",
            )

        result = _run_once()
        if result.returncode != 0 and (
            result.returncode >= 500 or _is_upstream_500(result.stdout, result.stderr)
        ):
            if on_log:
                on_log(f"{provider_label} returned upstream 500; retrying once.")
            time.sleep(1.0)
            result = _run_once()
        return self._emit_result(result, on_update=on_update)

    @staticmethod
    def _emit_result(
        result: subprocess.CompletedProcess[str],
        *,
        on_update: Callable[[str, str], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if on_update is not None:
            on_update(str(result.stdout or ""), str(result.stderr or ""))
        return result

    def _run_codex(
        self,
        *,
        prompt: str,
        mcp_configs: dict[str, dict[str, Any]],
        config_map: dict[str, Any],
        env_map: dict[str, str],
        on_log: Callable[[str], None] | None,
        provider_label: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover
            return subprocess.CompletedProcess(
                ["sdk:codex"],
                1,
                "",
                f"OpenAI Python SDK is required for codex provider: {exc}",
            )

        codex_settings = self._dependencies.codex_settings_from_model_config(config_map)
        model_name = str(codex_settings.get("model") or "").strip()
        if not model_name:
            model_name = self._dependencies.default_codex_model

        api_key = (
            self._dependencies.load_codex_auth_key()
            or str(env_map.get("OPENAI_API_KEY") or "").strip()
            or str(env_map.get("CODEX_API_KEY") or "").strip()
        )
        if not api_key:
            return subprocess.CompletedProcess(
                ["sdk:codex"],
                1,
                "",
                "Codex runtime requires OPENAI_API_KEY or CODEX_API_KEY.",
            )
        try:
            mcp_tools = _build_codex_sdk_mcp_tools(mcp_configs)
        except ValueError as exc:
            return subprocess.CompletedProcess(
                ["sdk:codex"],
                1,
                "",
                str(exc),
            )

        if on_log:
            on_log(f"Running {provider_label}: OpenAI SDK responses model={model_name}.")

        payload: dict[str, Any] = {
            "model": model_name,
            "input": prompt,
        }
        if mcp_tools:
            payload["tools"] = mcp_tools
        max_output_tokens = _optional_positive_int(config_map.get("max_output_tokens"))
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        temperature = _optional_float(config_map.get("temperature"))
        if temperature is not None:
            payload["temperature"] = temperature
        top_p = _optional_float(config_map.get("top_p"))
        if top_p is not None:
            payload["top_p"] = top_p

        try:
            response_payload = OpenAI(api_key=api_key).responses.create(**payload)
        except Exception as exc:
            return subprocess.CompletedProcess(
                ["sdk:codex"],
                _error_status_code(exc),
                "",
                str(exc),
            )
        return subprocess.CompletedProcess(
            ["sdk:codex"],
            0,
            _extract_openai_response_text(response_payload),
            "",
        )

    def _run_gemini(
        self,
        *,
        prompt: str,
        config_map: dict[str, Any],
        env_map: dict[str, str],
        on_log: Callable[[str], None] | None,
        provider_label: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            from google import genai
        except Exception as exc:  # pragma: no cover
            return subprocess.CompletedProcess(
                ["sdk:gemini"],
                1,
                "",
                f"google-genai Python SDK is required for gemini provider: {exc}",
            )

        gemini_settings = self._dependencies.gemini_settings_from_model_config(config_map)
        model_name = str(gemini_settings.get("model") or "").strip()
        if not model_name:
            model_name = self._dependencies.default_gemini_model

        api_key = (
            self._dependencies.load_gemini_auth_key()
            or str(env_map.get("GEMINI_API_KEY") or "").strip()
            or str(env_map.get("GOOGLE_API_KEY") or "").strip()
        )
        if not api_key:
            return subprocess.CompletedProcess(
                ["sdk:gemini"],
                1,
                "",
                "Gemini runtime requires GEMINI_API_KEY or GOOGLE_API_KEY.",
            )

        if on_log:
            on_log(
                f"Running {provider_label}: Google SDK generate_content model={model_name}."
            )

        request_config: dict[str, Any] = {}
        max_output_tokens = _optional_positive_int(config_map.get("max_output_tokens"))
        if max_output_tokens is not None:
            request_config["max_output_tokens"] = max_output_tokens
        temperature = _optional_float(config_map.get("temperature"))
        if temperature is not None:
            request_config["temperature"] = temperature
        top_p = _optional_float(config_map.get("top_p"))
        if top_p is not None:
            request_config["top_p"] = top_p
        top_k = _optional_positive_int(config_map.get("top_k"))
        if top_k is not None:
            request_config["top_k"] = top_k

        try:
            response_payload = genai.Client(api_key=api_key).models.generate_content(
                model=model_name,
                contents=prompt,
                config=request_config if request_config else None,
            )
        except Exception as exc:
            return subprocess.CompletedProcess(
                ["sdk:gemini"],
                _error_status_code(exc),
                "",
                str(exc),
            )
        return subprocess.CompletedProcess(
            ["sdk:gemini"],
            0,
            _extract_google_response_text(response_payload),
            "",
        )

    def _run_claude(
        self,
        *,
        prompt: str,
        config_map: dict[str, Any],
        env_map: dict[str, str],
        on_log: Callable[[str], None] | None,
        provider_label: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            from anthropic import Anthropic
        except Exception as exc:  # pragma: no cover
            return subprocess.CompletedProcess(
                ["sdk:claude"],
                1,
                "",
                f"Anthropic Python SDK is required for claude provider: {exc}",
            )

        model_name = str(config_map.get("model") or "").strip()
        if not model_name:
            model_name = self._dependencies.default_claude_model
        claude_api_key, _ = self._dependencies.resolve_claude_auth_key(env_map)
        if not claude_api_key:
            if self._dependencies.require_claude_api_key:
                return subprocess.CompletedProcess(
                    ["sdk:claude"],
                    1,
                    "",
                    (
                        "Claude runtime requires ANTHROPIC_API_KEY. "
                        "Set it in Settings -> Provider -> Claude or via environment."
                    ),
                )
            if on_log:
                on_log(
                    "Claude auth key not set. Continuing because "
                    "CLAUDE_AUTH_REQUIRE_API_KEY=false."
                )
        if on_log:
            on_log(
                f"Running {provider_label}: Anthropic SDK messages model={model_name}."
            )

        payload: dict[str, Any] = {
            "model": model_name,
            "max_tokens": _safe_int(config_map.get("max_tokens"), 2048),
            "messages": [{"role": "user", "content": prompt}],
        }
        temperature = _optional_float(config_map.get("temperature"))
        if temperature is not None:
            payload["temperature"] = temperature
        top_p = _optional_float(config_map.get("top_p"))
        if top_p is not None:
            payload["top_p"] = top_p
        system_prompt = str(config_map.get("system") or "").strip()
        if system_prompt:
            payload["system"] = system_prompt

        try:
            response_payload = Anthropic(api_key=claude_api_key).messages.create(**payload)
        except Exception as exc:
            return subprocess.CompletedProcess(
                ["sdk:claude"],
                _error_status_code(exc),
                "",
                str(exc),
            )
        return subprocess.CompletedProcess(
            ["sdk:claude"],
            0,
            _extract_claude_response_text(response_payload),
            "",
        )


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _error_status_code(exc: Exception) -> int:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        try:
            code = int(value)
        except (TypeError, ValueError):
            continue
        if code > 0:
            return code
    return 1


def _extract_openai_response_text(payload: Any) -> str:
    output_text = str(getattr(payload, "output_text", "") or "").strip()
    if output_text:
        return output_text
    if hasattr(payload, "model_dump"):
        try:
            payload = payload.model_dump()
        except Exception:
            payload = None
    if not isinstance(payload, dict):
        return str(payload or "").strip()
    outputs = payload.get("output")
    if not isinstance(outputs, list):
        return str(payload).strip()
    chunks: list[str] = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text_value = str(block.get("text") or block.get("output_text") or "").strip()
            if text_value:
                chunks.append(text_value)
    if chunks:
        return "\n".join(chunks).strip()
    return str(payload).strip()


def _extract_google_response_text(payload: Any) -> str:
    direct = str(getattr(payload, "text", "") or "").strip()
    if direct:
        return direct
    candidates = list(getattr(payload, "candidates", None) or [])
    chunks: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        for part in parts:
            text_value = str(getattr(part, "text", "") or "").strip()
            if text_value:
                chunks.append(text_value)
    if chunks:
        return "\n".join(chunks).strip()
    return str(payload or "").strip()


def _extract_claude_response_text(payload: Any) -> str:
    blocks = list(getattr(payload, "content", None) or [])
    chunks: list[str] = []
    for block in blocks:
        text_value = str(getattr(block, "text", "") or "").strip()
        if text_value:
            chunks.append(text_value)
            continue
        if isinstance(block, dict):
            fallback = str(block.get("text") or "").strip()
            if fallback:
                chunks.append(fallback)
    if chunks:
        return "\n".join(chunks).strip()
    return str(payload or "").strip()


def _extract_list_config(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{label} must be a string or list.")


def _extract_mapping_config(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a table of key/value pairs.")
    return {str(key): str(val) for key, val in value.items()}


def _build_codex_sdk_mcp_tools(
    mcp_configs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    allowed_keys = {
        "authorization",
        "description",
        "headers",
        "include_tools",
        "require_approval",
        "transport",
        "url",
    }
    for server_key in sorted(mcp_configs):
        config = dict(mcp_configs.get(server_key) or {})
        unsupported_keys = sorted(
            key
            for key, value in config.items()
            if key not in allowed_keys and value not in (None, "", [], {})
        )
        if unsupported_keys:
            raise ValueError(
                "Codex SDK MCP does not support these config fields for "
                f"'{server_key}': {', '.join(unsupported_keys)}."
            )

        server_url = str(config.get("url") or "").strip()
        if not server_url:
            raise ValueError(
                f"Codex MCP config for '{server_key}' must include a non-empty url."
            )

        transport = str(config.get("transport") or "").strip().lower()
        if transport and transport not in {"streamable-http", "http", "sse"}:
            raise ValueError(
                "Codex SDK MCP only supports remote HTTP/SSE servers; "
                f"server '{server_key}' has unsupported transport '{transport}'."
            )

        require_approval = str(config.get("require_approval") or "").strip().lower()
        if require_approval and require_approval not in {"always", "never"}:
            raise ValueError(
                "Codex MCP config for "
                f"'{server_key}' has invalid require_approval='{require_approval}'."
            )
        tool: dict[str, Any] = {
            "type": "mcp",
            "server_label": str(server_key),
            "server_url": server_url,
            "require_approval": require_approval or "never",
        }
        description = str(config.get("description") or "").strip()
        if description:
            tool["server_description"] = description

        headers = _extract_mapping_config(config.get("headers"), "headers")
        explicit_authorization = str(config.get("authorization") or "").strip()
        header_authorization = ""
        for header_key, header_value in headers.items():
            if header_key.lower() == "authorization":
                header_authorization = str(header_value).strip()
                break
        if explicit_authorization and header_authorization and (
            explicit_authorization != header_authorization
        ):
            raise ValueError(
                "Codex MCP config for "
                f"'{server_key}' defines conflicting authorization values."
            )
        authorization = explicit_authorization or header_authorization
        if authorization:
            tool["authorization"] = authorization
        forwarded_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() != "authorization"
        }
        if forwarded_headers:
            tool["headers"] = forwarded_headers

        include_tools = _extract_list_config(config.get("include_tools"), "include_tools")
        if include_tools:
            tool["allowed_tools"] = include_tools
        tools.append(tool)
    return tools


def _is_upstream_500(stdout: str, stderr: str) -> bool:
    haystack = f"{stdout}\n{stderr}".lower()
    markers = (
        "status: internal",
        "\"status\":\"internal\"",
        "internal error encountered",
        "status: 500",
        "code\":500",
        "error code: 500",
        "http 500",
        "internal server error",
    )
    return any(marker in haystack for marker in markers)
