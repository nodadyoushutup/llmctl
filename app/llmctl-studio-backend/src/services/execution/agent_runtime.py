from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import subprocess
import time
from typing import Any, Callable

_UPSTREAM_500_MAX_ATTEMPTS = 2
_MCP_TOOL_LIST_FAILED_DEPENDENCY_MAX_ATTEMPTS = 3
_TOOL_LOOP_MAX_CYCLES_DEFAULT = 24
_TOOL_LOOP_MAX_CYCLES_LIMIT = 64


@dataclass(slots=True, frozen=True)
class FrontierAgentRequest:
    provider: str
    prompt: str | None
    mcp_configs: dict[str, dict[str, Any]]
    system_prompt: str | None = None
    model_config: dict[str, Any] | None = None
    env: dict[str, str] | None = None
    request_id: str | None = None
    correlation_id: str | None = None


@dataclass(slots=True, frozen=True)
class FrontierToolCall:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(slots=True, frozen=True)
class FrontierToolResult:
    call_id: str
    tool_name: str
    output: Any
    is_error: bool = False


class FrontierToolDispatchError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(str(message or "Tool dispatch failed."))
        self.code = str(code or "").strip() or "tool_dispatch_error"
        self.details = dict(details or {})
        self.retryable = bool(retryable)


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
    dispatch_tool_call: Callable[[FrontierToolCall], FrontierToolResult | dict[str, Any]] | None = (
        None
    )


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
        system_prompt_text = str(request.system_prompt or "").strip()
        config_map = request.model_config if isinstance(request.model_config, dict) else {}
        env_map = dict(request.env or os.environ.copy())
        request_id = str(request.request_id or "").strip() or None
        correlation_id = str(request.correlation_id or "").strip() or None

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

        max_cycles = _safe_int(
            config_map.get("tool_loop_max_cycles"),
            _TOOL_LOOP_MAX_CYCLES_DEFAULT,
        )
        if max_cycles < 1:
            max_cycles = _TOOL_LOOP_MAX_CYCLES_DEFAULT
        max_cycles = min(max_cycles, _TOOL_LOOP_MAX_CYCLES_LIMIT)

        cycle_prompt = prompt_text
        tool_trace: list[dict[str, Any]] = []
        for cycle_index in range(1, max_cycles + 1):
            result = self._run_provider_cycle(
                provider=provider,
                provider_label=provider_label,
                prompt=cycle_prompt,
                system_prompt=system_prompt_text,
                mcp_configs=request.mcp_configs,
                config_map=config_map,
                env_map=env_map,
                on_log=on_log,
            )
            if result.returncode != 0:
                return self._emit_result(
                    result,
                    on_update=on_update,
                    tool_trace=tool_trace,
                )

            tool_calls = _extract_provider_tool_calls(
                provider=provider,
                payload=getattr(result, "_llmctl_raw_response", None),
            )
            if on_log:
                on_log(
                    "sdk_tool_cycle "
                    f"provider={provider} cycle={cycle_index} tool_calls={len(tool_calls)}"
                )
            if not tool_calls:
                return self._emit_result(
                    result,
                    on_update=on_update,
                    tool_trace=tool_trace,
                )

            tool_results, dispatch_error = self._dispatch_tool_calls(
                provider=provider,
                tool_calls=tool_calls,
                request_id=request_id,
                correlation_id=correlation_id,
                on_log=on_log,
            )
            tool_trace.extend(
                _build_tool_trace_entries(
                    provider=provider,
                    cycle_index=cycle_index,
                    tool_results=tool_results,
                )
            )
            if dispatch_error is not None:
                return self._emit_result(
                    dispatch_error,
                    on_update=on_update,
                    tool_trace=tool_trace,
                )
            cycle_prompt = _append_tool_results_to_prompt(
                prompt=cycle_prompt,
                tool_results=tool_results,
                cycle_index=cycle_index,
            )

        return self._emit_result(
            _tool_loop_error_completed_process(
                provider=provider,
                code="tool_loop_max_cycles_exceeded",
                message=(
                    f"{provider_label} SDK tool loop exceeded max cycles "
                    f"({max_cycles}) without producing a terminal response."
                ),
                details={"max_cycles": max_cycles},
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            on_update=on_update,
            tool_trace=tool_trace,
        )

    def _run_provider_cycle(
        self,
        *,
        provider: str,
        provider_label: str,
        prompt: str,
        system_prompt: str,
        mcp_configs: dict[str, dict[str, Any]],
        config_map: dict[str, Any],
        env_map: dict[str, str],
        on_log: Callable[[str], None] | None,
    ) -> subprocess.CompletedProcess[str]:
        def _run_once() -> subprocess.CompletedProcess[str]:
            if provider == "codex":
                return self._run_codex(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    mcp_configs=mcp_configs,
                    config_map=config_map,
                    env_map=env_map,
                    on_log=on_log,
                    provider_label=provider_label,
                )
            if provider == "gemini":
                return self._run_gemini(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    config_map=config_map,
                    env_map=env_map,
                    on_log=on_log,
                    provider_label=provider_label,
                )
            if provider == "claude":
                return self._run_claude(
                    prompt=prompt,
                    system_prompt=system_prompt,
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
        attempt = 1
        while result.returncode != 0:
            if _is_retryable_mcp_tool_list_failed_dependency(
                provider=provider,
                mcp_configs=mcp_configs,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            ):
                if attempt >= _MCP_TOOL_LIST_FAILED_DEPENDENCY_MAX_ATTEMPTS:
                    break
                retry_delay_seconds = float(attempt)
                if on_log:
                    on_log(
                        f"{provider_label} MCP tools/list returned failed dependency "
                        f"(attempt {attempt}/{_MCP_TOOL_LIST_FAILED_DEPENDENCY_MAX_ATTEMPTS}); "
                        f"retrying in {retry_delay_seconds:.1f}s."
                    )
                time.sleep(retry_delay_seconds)
                attempt += 1
                result = _run_once()
                continue
            if result.returncode >= 500 or _is_upstream_500(result.stdout, result.stderr):
                if attempt >= _UPSTREAM_500_MAX_ATTEMPTS:
                    break
                if on_log:
                    on_log(f"{provider_label} returned upstream 500; retrying once.")
                time.sleep(1.0)
                attempt += 1
                result = _run_once()
                continue
            break
        return result

    def _dispatch_tool_calls(
        self,
        *,
        provider: str,
        tool_calls: list[FrontierToolCall],
        request_id: str | None,
        correlation_id: str | None,
        on_log: Callable[[str], None] | None,
    ) -> tuple[list[FrontierToolResult], subprocess.CompletedProcess[str] | None]:
        dispatcher = self._dependencies.dispatch_tool_call
        if dispatcher is None:
            return [], _tool_loop_error_completed_process(
                provider=provider,
                code="tool_dispatcher_unconfigured",
                message=(
                    "SDK tool loop dispatcher is not configured. "
                    "Tool domain wiring is required before tool calls can execute."
                ),
                details={"tool_call_count": len(tool_calls)},
                request_id=request_id,
                correlation_id=correlation_id,
            )
        results: list[FrontierToolResult] = []
        for tool_call in tool_calls:
            if on_log:
                on_log(
                    "sdk_tool_dispatch "
                    f"provider={provider} call_id={tool_call.call_id} "
                    f"tool_name={tool_call.tool_name}"
                )
            try:
                raw_result = dispatcher(tool_call)
            except Exception as exc:
                if isinstance(exc, FrontierToolDispatchError):
                    return results, _tool_loop_error_completed_process(
                        provider=provider,
                        code=exc.code,
                        message=str(exc),
                        details=exc.details,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        retryable=exc.retryable,
                    )
                return results, _tool_loop_error_completed_process(
                    provider=provider,
                    code="tool_dispatch_failed",
                    message=f"Tool dispatch failed for {tool_call.tool_name}: {exc}",
                    details={
                        "call_id": tool_call.call_id,
                        "tool_name": tool_call.tool_name,
                    },
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
            normalized_result = _normalize_frontier_tool_result(raw_result, fallback=tool_call)
            results.append(normalized_result)
        return results, None

    @staticmethod
    def _emit_result(
        result: subprocess.CompletedProcess[str],
        *,
        on_update: Callable[[str, str], None] | None = None,
        tool_trace: list[dict[str, Any]] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if isinstance(tool_trace, list):
            setattr(result, "_llmctl_tool_trace", list(tool_trace))
        if on_update is not None:
            on_update(str(result.stdout or ""), str(result.stderr or ""))
        return result

    def _run_codex(
        self,
        *,
        prompt: str,
        system_prompt: str,
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
        configured_instructions = str(config_map.get("instructions") or "").strip()
        effective_instructions = _merge_system_prompt(
            primary=system_prompt,
            secondary=configured_instructions,
        )
        if effective_instructions:
            payload["instructions"] = effective_instructions
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
        completed = subprocess.CompletedProcess(
            ["sdk:codex"],
            0,
            _extract_openai_response_text(response_payload),
            "",
        )
        setattr(completed, "_llmctl_raw_response", response_payload)
        return completed

    def _run_gemini(
        self,
        *,
        prompt: str,
        system_prompt: str,
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

        use_vertex_raw = gemini_settings.get("use_vertex_ai")
        use_vertex_ai = False
        if isinstance(use_vertex_raw, bool):
            use_vertex_ai = use_vertex_raw
        elif isinstance(use_vertex_raw, str):
            use_vertex_ai = use_vertex_raw.strip().lower() == "true"

        client_kwargs: dict[str, Any]
        if use_vertex_ai:
            project = str(gemini_settings.get("project") or "").strip()
            location = str(gemini_settings.get("location") or "").strip()
            if not project or not location:
                return subprocess.CompletedProcess(
                    ["sdk:gemini"],
                    1,
                    "",
                    (
                        "Gemini Vertex runtime requires both project and location when "
                        "use_vertex_ai=true."
                    ),
                )
            client_kwargs = {
                "vertexai": True,
                "project": project,
                "location": location,
            }
        else:
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
            client_kwargs = {"api_key": api_key}

        if on_log:
            mode = "Vertex AI" if use_vertex_ai else "Developer API"
            on_log(f"Running {provider_label}: Google SDK ({mode}) model={model_name}.")

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
        configured_system_instruction = str(
            config_map.get("system_instruction") or config_map.get("system") or ""
        ).strip()
        effective_system_instruction = _merge_system_prompt(
            primary=system_prompt,
            secondary=configured_system_instruction,
        )
        if effective_system_instruction:
            request_config["system_instruction"] = effective_system_instruction

        try:
            response_payload = genai.Client(**client_kwargs).models.generate_content(
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
        completed = subprocess.CompletedProcess(
            ["sdk:gemini"],
            0,
            _extract_google_response_text(response_payload),
            "",
        )
        setattr(completed, "_llmctl_raw_response", response_payload)
        return completed

    def _run_claude(
        self,
        *,
        prompt: str,
        system_prompt: str,
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
        configured_system_prompt = str(config_map.get("system") or "").strip()
        effective_system_prompt = _merge_system_prompt(
            primary=system_prompt,
            secondary=configured_system_prompt,
        )
        if effective_system_prompt:
            payload["system"] = effective_system_prompt

        try:
            response_payload = Anthropic(api_key=claude_api_key).messages.create(**payload)
        except Exception as exc:
            return subprocess.CompletedProcess(
                ["sdk:claude"],
                _error_status_code(exc),
                "",
                str(exc),
            )
        completed = subprocess.CompletedProcess(
            ["sdk:claude"],
            0,
            _extract_claude_response_text(response_payload),
            "",
        )
        setattr(completed, "_llmctl_raw_response", response_payload)
        return completed


def _merge_system_prompt(*, primary: str | None, secondary: str | None) -> str:
    first = str(primary or "").strip()
    second = str(secondary or "").strip()
    if first and second:
        return f"{first}\n\n{second}"
    return first or second


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
    message = str(exc or "")
    for pattern in (
        r"\berror code:\s*(\d{3})\b",
        r"\bhttp status code:\s*(\d{3})\b",
        r"\bstatus code:\s*(\d{3})\b",
    ):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            parsed = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
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


def _coerce_model_dump(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        try:
            return payload.model_dump()
        except Exception:
            return payload
    return payload


def _normalize_frontier_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"value": text}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    if raw is None:
        return {}
    return {"value": raw}


def _extract_openai_tool_calls(payload: Any) -> list[FrontierToolCall]:
    parsed = _coerce_model_dump(payload)
    if not isinstance(parsed, dict):
        return []
    outputs = parsed.get("output")
    if not isinstance(outputs, list):
        return []
    tool_calls: list[FrontierToolCall] = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type not in {"function_call", "tool_call"}:
            continue
        name = str(item.get("name") or item.get("tool_name") or "").strip()
        if not name and isinstance(item.get("function"), dict):
            name = str(item.get("function", {}).get("name") or "").strip()
        if not name:
            continue
        arguments = item.get("arguments")
        if arguments is None and isinstance(item.get("function"), dict):
            arguments = item.get("function", {}).get("arguments")
        call_id = str(item.get("call_id") or item.get("id") or "").strip() or (
            f"openai-call-{len(tool_calls) + 1}"
        )
        tool_calls.append(
            FrontierToolCall(
                call_id=call_id,
                tool_name=name,
                arguments=_normalize_frontier_tool_arguments(arguments),
            )
        )
    return tool_calls


def _extract_gemini_tool_calls(payload: Any) -> list[FrontierToolCall]:
    candidates = list(getattr(payload, "candidates", None) or [])
    tool_calls: list[FrontierToolCall] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        for part in parts:
            function_call = getattr(part, "function_call", None)
            if function_call is None and isinstance(part, dict):
                function_call = part.get("function_call")
            if function_call is None:
                continue
            name = str(
                getattr(function_call, "name", None)
                or (
                    function_call.get("name")
                    if isinstance(function_call, dict)
                    else ""
                )
                or ""
            ).strip()
            if not name:
                continue
            arguments = (
                getattr(function_call, "args", None)
                if not isinstance(function_call, dict)
                else function_call.get("args")
            )
            call_id = str(
                getattr(function_call, "id", None)
                or (
                    function_call.get("id")
                    if isinstance(function_call, dict)
                    else ""
                )
                or ""
            ).strip() or (f"gemini-call-{len(tool_calls) + 1}")
            tool_calls.append(
                FrontierToolCall(
                    call_id=call_id,
                    tool_name=name,
                    arguments=_normalize_frontier_tool_arguments(arguments),
                )
            )
    return tool_calls


def _extract_claude_tool_calls(payload: Any) -> list[FrontierToolCall]:
    blocks = list(getattr(payload, "content", None) or [])
    tool_calls: list[FrontierToolCall] = []
    for block in blocks:
        block_type = str(
            getattr(block, "type", None)
            or (block.get("type") if isinstance(block, dict) else "")
            or ""
        ).strip().lower()
        if block_type != "tool_use":
            continue
        name = str(
            getattr(block, "name", None)
            or (block.get("name") if isinstance(block, dict) else "")
            or ""
        ).strip()
        if not name:
            continue
        arguments = (
            getattr(block, "input", None)
            if not isinstance(block, dict)
            else block.get("input")
        )
        call_id = str(
            getattr(block, "id", None)
            or (block.get("id") if isinstance(block, dict) else "")
            or ""
        ).strip() or (f"claude-call-{len(tool_calls) + 1}")
        tool_calls.append(
            FrontierToolCall(
                call_id=call_id,
                tool_name=name,
                arguments=_normalize_frontier_tool_arguments(arguments),
            )
        )
    return tool_calls


def _extract_provider_tool_calls(*, provider: str, payload: Any) -> list[FrontierToolCall]:
    if payload is None:
        return []
    if provider == "codex":
        return _extract_openai_tool_calls(payload)
    if provider == "gemini":
        return _extract_gemini_tool_calls(payload)
    if provider == "claude":
        return _extract_claude_tool_calls(payload)
    return []


def _normalize_frontier_tool_result(
    value: FrontierToolResult | dict[str, Any],
    *,
    fallback: FrontierToolCall,
) -> FrontierToolResult:
    if isinstance(value, FrontierToolResult):
        return value
    payload = dict(value or {})
    call_id = str(payload.get("call_id") or fallback.call_id).strip() or fallback.call_id
    tool_name = str(payload.get("tool_name") or fallback.tool_name).strip() or fallback.tool_name
    is_error = bool(payload.get("is_error"))
    if "output" in payload:
        output = payload.get("output")
    elif "result" in payload:
        output = payload.get("result")
    else:
        output = {
            key: val
            for key, val in payload.items()
            if key not in {"call_id", "tool_name", "is_error"}
        }
    return FrontierToolResult(
        call_id=call_id,
        tool_name=tool_name,
        output=output,
        is_error=is_error,
    )


def _append_tool_results_to_prompt(
    *,
    prompt: str,
    tool_results: list[FrontierToolResult],
    cycle_index: int,
) -> str:
    serialized = json.dumps(
        [
            {
                "call_id": item.call_id,
                "tool_name": item.tool_name,
                "is_error": bool(item.is_error),
                "output": item.output,
            }
            for item in tool_results
        ],
        sort_keys=True,
    )
    prefix = prompt.strip()
    if prefix:
        prefix = f"{prefix}\n\n"
    return (
        f"{prefix}Tool results from cycle {int(cycle_index)} (JSON):\n"
        f"{serialized}\n"
        "Use these results to continue. If more tool actions are required, emit new tool calls."
    )


def _build_tool_trace_entries(
    *,
    provider: str,
    cycle_index: int,
    tool_results: list[FrontierToolResult],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in tool_results:
        output = item.output if isinstance(item.output, dict) else {}
        trace_envelope = (
            output.get("trace_envelope")
            if isinstance(output.get("trace_envelope"), dict)
            else {}
        )
        warnings = output.get("warnings")
        warnings_list = list(warnings) if isinstance(warnings, list) else []
        entries.append(
            {
                "provider": str(provider or "").strip().lower(),
                "cycle": int(cycle_index),
                "call_id": item.call_id,
                "tool_name": item.tool_name,
                "is_error": bool(item.is_error),
                "tool_domain": str(output.get("tool_domain") or "").strip(),
                "operation": str(output.get("operation") or "").strip(),
                "execution_status": str(output.get("execution_status") or "").strip(),
                "fallback_used": bool(output.get("fallback_used")),
                "warnings": warnings_list,
                "warning_count": len(warnings_list),
                "trace_envelope": trace_envelope,
            }
        )
    return entries


def _tool_loop_error_completed_process(
    *,
    provider: str,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    retryable: bool = False,
) -> subprocess.CompletedProcess[str]:
    envelope = _tool_loop_error_envelope(
        code=code,
        message=message,
        details=details,
        request_id=request_id,
        correlation_id=correlation_id,
        retryable=retryable,
    )
    return subprocess.CompletedProcess(
        [f"sdk:{provider}"],
        1,
        "",
        f"{message}\n{json.dumps(envelope, sort_keys=True)}".strip(),
    )


def _tool_loop_error_envelope(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": str(code or "").strip() or "tool_loop_error",
        "message": str(message or "").strip() or "SDK tool loop failed.",
        "details": dict(details or {}),
        "retryable": bool(retryable),
        "request_id": request_id,
        "correlation_id": correlation_id,
    }
    return payload


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


def _is_retryable_mcp_tool_list_failed_dependency(
    *,
    provider: str,
    mcp_configs: dict[str, dict[str, Any]],
    returncode: int,
    stdout: str,
    stderr: str,
) -> bool:
    if provider != "codex" or not mcp_configs:
        return False
    haystack = f"{stdout}\n{stderr}".lower()
    if "error retrieving tool list from mcp server" not in haystack:
        return False
    return (
        returncode == 424
        or "error code: 424" in haystack
        or "http status code: 424" in haystack
        or "failed dependency" in haystack
    )
