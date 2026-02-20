#!/usr/bin/env python3
"""Provider-agnostic debug agent wrapper with unified MCP/tools/skills payloads."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


SUPPORTED_PROVIDERS = ("openai", "google", "anthropic")


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    url: str
    transport: str = "streamable-http"
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    sse_read_timeout_seconds: float | None = None


@dataclass(slots=True)
class SkillConfig:
    name: str
    path: str = ""
    description: str = ""
    enabled: bool = True


@dataclass(slots=True)
class ToolConfig:
    name: str
    description: str
    parameters_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": True}
    )
    handler: ToolHandler | None = None


@dataclass(slots=True)
class OutputContract:
    type: str = "json_object"
    schema: dict[str, Any] | None = None
    schema_name: str = "response"
    strict: bool = True
    require_json: bool = True
    max_validation_retries: int = 1


@dataclass(slots=True)
class AgentRequest:
    system_prompt: str
    user_prompt: str
    tools: list[ToolConfig] = field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    skills: list[SkillConfig] = field(default_factory=list)
    model: str | None = None
    max_tool_round_trips: int = 4
    output_contract: OutputContract | dict[str, Any] | None = None


@dataclass(slots=True)
class AgentResponse:
    text: str
    provider: str
    model: str
    backend: str
    warnings: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class AgentConfig:
    provider: str
    api_key: str
    model: str
    max_tokens: int = 1024
    provider_options: dict[str, Any] = field(default_factory=dict)
    output_contract: OutputContract | dict[str, Any] | None = None


class UnifiedAgent:
    """Provider adapter that accepts one structured payload for all providers."""

    def __init__(self, config: AgentConfig) -> None:
        provider = (config.provider or "").strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{config.provider}'. "
                f"Use one of: {', '.join(SUPPORTED_PROVIDERS)}"
            )
        if not config.api_key:
            raise ValueError(f"Missing API key for provider '{provider}'.")
        if not config.model:
            raise ValueError(f"Missing model for provider '{provider}'.")

        self.config = AgentConfig(
            provider=provider,
            api_key=config.api_key,
            model=config.model,
            max_tokens=config.max_tokens,
            provider_options=dict(config.provider_options or {}),
            output_contract=config.output_contract,
        )
        self._client: Any = self._build_client()

    def _build_client(self) -> Any:
        if self.config.provider == "openai":
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "Missing dependency for OpenAI. Install with: "
                    "`python3 -m pip install openai`"
                ) from exc
            return OpenAI(api_key=self.config.api_key)

        if self.config.provider == "google":
            try:
                from google import genai
            except ImportError:
                try:
                    import google.generativeai as genai
                except ImportError as exc:
                    raise RuntimeError(
                        "Missing dependency for Google. Install one of: "
                        "`python3 -m pip install google-genai` or "
                        "`python3 -m pip install google-generativeai`"
                    ) from exc
                genai.configure(api_key=self.config.api_key)
                return genai
            return genai.Client(api_key=self.config.api_key)

        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency for Anthropic. Install with: "
                "`python3 -m pip install anthropic`"
            ) from exc
        return Anthropic(api_key=self.config.api_key)

    def run(self, request: AgentRequest) -> AgentResponse:
        system_prompt = (request.system_prompt or "").strip()
        user_prompt = (request.user_prompt or "").strip()
        if not system_prompt:
            raise ValueError("system_prompt cannot be empty.")
        if not user_prompt:
            raise ValueError("user_prompt cannot be empty.")

        warnings: list[str] = []
        model = (request.model or self.config.model).strip()
        output_contract = self._resolve_output_contract(
            request.output_contract or self.config.output_contract
        )
        effective_system = self._build_effective_system_prompt(
            system_prompt=system_prompt,
            tools=request.tools,
            skills=request.skills,
            warnings=warnings,
            output_contract=output_contract,
        )

        conversation: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]
        tool_calls: list[dict[str, Any]] = []
        backend = "sdk"
        last_output = ""
        rounds = max(1, int(request.max_tool_round_trips or 1))

        for _ in range(rounds):
            generated, selected_backend, generated_warnings = self._generate_text(
                system_prompt=effective_system,
                conversation=conversation,
                request=request,
                model=model,
                output_contract=output_contract,
            )
            backend = selected_backend
            warnings.extend(generated_warnings)
            last_output = generated.strip()

            parsed_tool = self._extract_tool_call(last_output)
            if not request.tools or parsed_tool is None:
                finalized_text = self._finalize_response_text(
                    last_output,
                    output_contract=output_contract,
                    warnings=warnings,
                )
                return AgentResponse(
                    text=finalized_text,
                    provider=self.config.provider,
                    model=model,
                    backend=backend,
                    warnings=self._unique_in_order(warnings),
                    tool_calls=tool_calls,
                )

            call_name = parsed_tool.get("name")
            call_args = parsed_tool.get("arguments") or {}
            if not isinstance(call_name, str) or not call_name.strip():
                warnings.append("Model emitted malformed tool call; returning raw model output.")
                finalized_text = self._finalize_response_text(
                    last_output,
                    output_contract=output_contract,
                    warnings=warnings,
                )
                return AgentResponse(
                    text=finalized_text,
                    provider=self.config.provider,
                    model=model,
                    backend=backend,
                    warnings=self._unique_in_order(warnings),
                    tool_calls=tool_calls,
                )
            if not isinstance(call_args, dict):
                call_args = {"value": call_args}

            tool = next((item for item in request.tools if item.name == call_name), None)
            if tool is None:
                tool_result = {
                    "ok": False,
                    "error": f"Unknown tool '{call_name}'.",
                }
            elif tool.handler is None:
                tool_result = {
                    "ok": False,
                    "error": f"Tool '{call_name}' has no handler.",
                }
            else:
                try:
                    output = tool.handler(call_args)
                    tool_result = {"ok": True, "result": output}
                except Exception as exc:
                    tool_result = {"ok": False, "error": str(exc)}

            tool_calls.append(
                {
                    "name": call_name,
                    "arguments": call_args,
                    "result": tool_result,
                }
            )
            conversation.append({"role": "assistant", "content": last_output})
            conversation.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        {"tool_name": call_name, "tool_result": tool_result},
                        ensure_ascii=False,
                    ),
                }
            )
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "Tool result attached above. Either return final answer, or request "
                        "another tool call using the required JSON format."
                    ),
                }
            )

        warnings.append("Max tool round trips reached; returning latest model output.")
        finalized_text = self._finalize_response_text(
            last_output,
            output_contract=output_contract,
            warnings=warnings,
        )
        return AgentResponse(
            text=finalized_text,
            provider=self.config.provider,
            model=model,
            backend=backend,
            warnings=self._unique_in_order(warnings),
            tool_calls=tool_calls,
        )

    def _build_effective_system_prompt(
        self,
        *,
        system_prompt: str,
        tools: list[ToolConfig],
        skills: list[SkillConfig],
        warnings: list[str],
        output_contract: OutputContract | None,
    ) -> str:
        parts = [system_prompt]
        if tools:
            parts.append(self._tool_protocol_instructions(tools))
        skill_context = self._skill_context(skills, warnings=warnings)
        if skill_context:
            parts.append(skill_context)
        output_rules = self._output_contract_instructions(output_contract)
        if output_rules:
            parts.append(output_rules)
        return "\n\n".join(parts)

    def _tool_protocol_instructions(self, tools: list[ToolConfig]) -> str:
        tool_specs = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters_schema": tool.parameters_schema,
            }
            for tool in tools
        ]
        return (
            "You can call tools.\n"
            "When calling a tool, output ONLY valid JSON in this exact shape:\n"
            '{"tool_call":{"name":"<tool-name>","arguments":{...}}}\n'
            "When you do not need a tool, return normal plain text.\n"
            f"Available tools:\n{json.dumps(tool_specs, indent=2, ensure_ascii=False)}"
        )

    def _skill_context(self, skills: list[SkillConfig], *, warnings: list[str]) -> str:
        enabled = [skill for skill in skills if skill.enabled]
        if not enabled:
            return ""
        entries: list[str] = ["Skill context (best-effort cross-provider adaptation):"]
        for skill in enabled:
            desc = (skill.description or "").strip()
            snippet = ""
            path_value = str(skill.path or "").strip()
            if path_value:
                try:
                    skill_path = Path(path_value).expanduser().resolve()
                    if skill_path.exists() and skill_path.is_file():
                        raw = skill_path.read_text(encoding="utf-8", errors="replace")
                        snippet = raw[:1200].strip()
                    else:
                        warnings.append(f"Skill path not found for '{skill.name}': {path_value}")
                except Exception as exc:
                    warnings.append(f"Failed to load skill '{skill.name}': {exc}")
            lines = [f"- {skill.name}"]
            if desc:
                lines.append(f"  Description: {desc}")
            if snippet:
                lines.append(f"  Excerpt:\n{snippet}")
            entries.append("\n".join(lines))
        return "\n".join(entries)

    def _generate_text(
        self,
        *,
        system_prompt: str,
        conversation: list[dict[str, str]],
        request: AgentRequest,
        model: str,
        output_contract: OutputContract | None,
    ) -> tuple[str, str, list[str]]:
        warnings: list[str] = []
        transcript = self._render_transcript(conversation)
        prompt = (
            "SYSTEM INSTRUCTIONS:\n"
            f"{system_prompt}\n\n"
            "CONVERSATION SO FAR:\n"
            f"{transcript}\n\n"
            "Respond as the assistant for the latest user request."
        )
        backend = self._select_backend(request=request, warnings=warnings)
        if backend == "codex_cli":
            return self._run_codex_cli(prompt=prompt, request=request, model=model), backend, warnings
        if backend == "gemini_cli":
            return (
                self._run_gemini_cli(prompt=prompt, request=request, model=model),
                backend,
                warnings,
            )
        if backend == "claude_cli":
            return (
                self._run_claude_cli(prompt=prompt, request=request, model=model),
                backend,
                warnings,
            )
        return (
            self._run_sdk(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                output_contract=output_contract,
                warnings=warnings,
            ),
            backend,
            warnings,
        )

    def _select_backend(self, *, request: AgentRequest, warnings: list[str]) -> str:
        mcp_requested = bool(request.mcp_servers)
        skills_requested = any(skill.enabled for skill in request.skills)
        provider = self.config.provider

        if provider == "openai" and (mcp_requested or skills_requested):
            if shutil.which(self._option_str("codex_cmd", "codex")):
                return "codex_cli"
            warnings.append(
                "OpenAI advanced features requested (MCP/skills), but codex CLI is unavailable; "
                "falling back to OpenAI SDK."
            )
        if provider == "google" and mcp_requested:
            if shutil.which(self._option_str("gemini_cmd", "gemini")):
                return "gemini_cli"
            warnings.append(
                "Google MCP requested, but gemini CLI is unavailable; falling back to Google SDK "
                "without MCP transport."
            )
        if provider == "anthropic" and mcp_requested:
            if shutil.which(self._option_str("claude_cmd", "claude")):
                return "claude_cli"
            warnings.append(
                "Anthropic MCP requested, but claude CLI is unavailable; falling back to "
                "Anthropic SDK without MCP transport."
            )
        return "sdk"

    def _run_sdk(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        output_contract: OutputContract | None,
        warnings: list[str],
    ) -> str:
        if self.config.provider == "openai":
            return self._run_openai_sdk(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                output_contract=output_contract,
            )
        if self.config.provider == "google":
            return self._run_google_sdk(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                output_contract=output_contract,
                warnings=warnings,
            )
        return self._run_anthropic_sdk(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            output_contract=output_contract,
            warnings=warnings,
        )

    def _run_openai_sdk(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        output_contract: OutputContract | None,
    ) -> str:
        request: dict[str, Any] = {
            "model": model,
            "instructions": system_prompt,
            "input": prompt,
            "max_output_tokens": self.config.max_tokens,
        }
        options = self.config.provider_options
        temperature = options.get("temperature")
        if temperature is not None:
            request["temperature"] = temperature
        top_p = options.get("top_p")
        if top_p is not None:
            request["top_p"] = top_p
        reasoning_effort = options.get("reasoning_effort")
        if reasoning_effort:
            request["reasoning"] = {"effort": str(reasoning_effort)}
        verbosity = options.get("verbosity")
        if verbosity:
            request["text"] = {"verbosity": str(verbosity)}
        if output_contract and output_contract.require_json:
            text_payload = request.get("text")
            if not isinstance(text_payload, dict):
                text_payload = {}
            text_payload["format"] = self._openai_text_format(output_contract)
            request["text"] = text_payload
        extra_request_params = options.get("extra_request_params")
        if isinstance(extra_request_params, dict):
            request.update(extra_request_params)
        response = self._create_openai_response_with_model_compat(request)
        text = getattr(response, "output_text", None)
        if text:
            return text.strip()
        return str(response)

    def _run_google_sdk(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        output_contract: OutputContract | None,
        warnings: list[str],
    ) -> str:
        options = self.config.provider_options
        request_config: dict[str, Any] = {
            "system_instruction": system_prompt,
            "max_output_tokens": self.config.max_tokens,
        }
        for key in ("temperature", "top_p", "top_k", "candidate_count"):
            value = options.get(key)
            if value is not None:
                request_config[key] = value
        thinking_budget = options.get("thinking_budget")
        if thinking_budget is not None:
            request_config["thinking_config"] = {"thinking_budget": int(thinking_budget)}
        if output_contract and output_contract.require_json:
            request_config.update(self._google_structured_output_config(output_contract))

        if hasattr(self._client, "models"):
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=request_config,
                )
            except Exception as exc:
                fallback_config = dict(request_config)
                removed_keys = self._prune_google_unsupported_config(
                    fallback_config, exc
                )
                if not removed_keys:
                    fallback_config.pop("thinking_config", None)
                    removed_keys = ["thinking_config"]
                if removed_keys:
                    warnings.append(
                        "Google SDK removed unsupported config key(s): "
                        + ", ".join(sorted(set(removed_keys)))
                    )
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=fallback_config,
                )
            text = getattr(response, "text", None)
            if text:
                return text.strip()
            return str(response)

        legacy_model = self._client.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
        )
        generation_config: dict[str, Any] = {"max_output_tokens": self.config.max_tokens}
        for key in ("temperature", "top_p", "top_k", "candidate_count"):
            value = options.get(key)
            if value is not None:
                generation_config[key] = value
        if output_contract and output_contract.require_json:
            generation_config.update(self._google_structured_output_config(output_contract))
        try:
            response = legacy_model.generate_content(prompt, generation_config=generation_config)
        except Exception as exc:
            fallback_generation_config = dict(generation_config)
            removed_keys = self._prune_google_unsupported_config(
                fallback_generation_config,
                exc,
            )
            if removed_keys:
                warnings.append(
                    "Google legacy SDK removed unsupported config key(s): "
                    + ", ".join(sorted(set(removed_keys)))
                )
            response = legacy_model.generate_content(
                prompt,
                generation_config=fallback_generation_config,
            )
        text = getattr(response, "text", None)
        if text:
            return text.strip()
        return str(response)

    def _run_anthropic_sdk(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        output_contract: OutputContract | None,
        warnings: list[str],
    ) -> str:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": self.config.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        options = self.config.provider_options
        temperature = options.get("temperature")
        if temperature is not None:
            request["temperature"] = temperature
        top_p = options.get("top_p")
        if top_p is not None:
            request["top_p"] = top_p
        thinking_budget = options.get("thinking_budget")
        if thinking_budget is not None:
            request["thinking"] = {"type": "enabled", "budget_tokens": int(thinking_budget)}
        if output_contract and output_contract.require_json:
            request.update(self._anthropic_structured_output_config(output_contract))

        message = self._create_anthropic_message_with_model_compat(request, warnings=warnings)
        blocks = getattr(message, "content", None) or []
        text_parts: list[str] = []
        for block in blocks:
            block_text = getattr(block, "text", None)
            if block_text:
                text_parts.append(block_text)
                continue
            if isinstance(block, dict):
                maybe_text = block.get("text")
                if maybe_text:
                    text_parts.append(str(maybe_text))
        if text_parts:
            return "\n".join(text_parts).strip()
        return str(message)

    def _run_codex_cli(self, *, prompt: str, request: AgentRequest, model: str) -> str:
        cmd = [self._option_str("codex_cmd", "codex"), "exec", "--skip-git-repo-check"]
        if model:
            cmd.extend(["--model", model])
        for override in self._codex_config_overrides(request):
            cmd.extend(["-c", override])
        return self._run_subprocess(cmd=cmd, prompt=prompt)

    def _run_gemini_cli(self, *, prompt: str, request: AgentRequest, model: str) -> str:
        gemini_cmd = self._option_str("gemini_cmd", "gemini")
        with tempfile.TemporaryDirectory(prefix="llmctl-gemini-home-") as home:
            env = os.environ.copy()
            env["HOME"] = home
            env["XDG_CONFIG_HOME"] = str(Path(home) / ".config")
            env["XDG_DATA_HOME"] = str(Path(home) / ".local" / "share")
            env["XDG_CACHE_HOME"] = str(Path(home) / ".cache")

            for mcp in request.mcp_servers:
                add_cmd = [gemini_cmd, "mcp", "add", "--scope", "user"]
                transport = self._normalize_transport(mcp.transport)
                if transport:
                    add_cmd.extend(["--transport", transport])
                for header_key, header_value in sorted(mcp.headers.items()):
                    add_cmd.extend(["-H", f"{header_key}: {header_value}"])
                add_cmd.extend([mcp.name, mcp.url])
                self._run_subprocess(cmd=add_cmd, prompt=None, env=env)

            run_cmd = [gemini_cmd]
            if model:
                run_cmd.extend(["--model", model])
            if request.mcp_servers:
                run_cmd.append("--allowed-mcp-server-names")
                run_cmd.extend(sorted(mcp.name for mcp in request.mcp_servers))
            return self._run_subprocess(cmd=run_cmd, prompt=prompt, env=env)

    def _run_claude_cli(self, *, prompt: str, request: AgentRequest, model: str) -> str:
        claude_cmd = self._option_str("claude_cmd", "claude")
        cmd = [claude_cmd, "--print"]
        if model:
            cmd.extend(["--model", model])
        if request.mcp_servers:
            payload: dict[str, Any] = {"mcpServers": {}}
            for mcp in request.mcp_servers:
                payload["mcpServers"][mcp.name] = {
                    "url": mcp.url,
                    "transport": mcp.transport or "streamable-http",
                }
                if mcp.headers:
                    payload["mcpServers"][mcp.name]["headers"] = dict(mcp.headers)
            cmd.extend(
                [
                    "--mcp-config",
                    json.dumps(payload, separators=(",", ":")),
                    "--strict-mcp-config",
                ]
            )
        return self._run_subprocess(cmd=cmd, prompt=prompt)

    def _resolve_output_contract(
        self, raw: OutputContract | dict[str, Any] | None
    ) -> OutputContract | None:
        if raw is None:
            return None
        if isinstance(raw, OutputContract):
            contract = raw
        elif isinstance(raw, dict):
            contract = OutputContract(
                type=str(raw.get("type") or "json_object"),
                schema=raw.get("schema") if isinstance(raw.get("schema"), dict) else None,
                schema_name=str(raw.get("schema_name") or "response"),
                strict=self._coerce_bool(raw.get("strict"), default=True),
                require_json=self._coerce_bool(raw.get("require_json"), default=True),
                max_validation_retries=self._coerce_non_negative_int(
                    raw.get("max_validation_retries"),
                    default=1,
                ),
            )
        else:
            raise ValueError("output_contract must be OutputContract, dict, or None.")
        normalized_type = str(contract.type or "json_object").strip().lower()
        if normalized_type not in {"json_object", "json_schema"}:
            raise ValueError("output_contract.type must be json_object or json_schema.")
        return OutputContract(
            type=normalized_type,
            schema=contract.schema if isinstance(contract.schema, dict) else None,
            schema_name=self._safe_schema_name(contract.schema_name),
            strict=bool(contract.strict),
            require_json=bool(contract.require_json),
            max_validation_retries=max(0, int(contract.max_validation_retries)),
        )

    def _coerce_bool(self, value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default

    def _coerce_non_negative_int(self, value: Any, *, default: int) -> int:
        if value is None:
            return default
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return default
        return max(0, parsed)

    def _output_contract_instructions(self, output_contract: OutputContract | None) -> str:
        if output_contract is None or not output_contract.require_json:
            return ""
        lines = [
            "Output contract (hard requirement):",
            "- Final response MUST be valid JSON.",
            "- Do not include markdown fences or any non-JSON text.",
        ]
        if output_contract.type == "json_object":
            lines.append("- The top-level JSON value MUST be an object.")
        if output_contract.type == "json_schema":
            schema = self._contract_schema(output_contract)
            lines.append("- The JSON MUST satisfy this schema:")
            lines.append(json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines)

    def _safe_schema_name(self, value: str | None) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
        return cleaned or "response"

    def _contract_schema(self, output_contract: OutputContract) -> dict[str, Any]:
        if output_contract.type == "json_schema" and isinstance(output_contract.schema, dict):
            return output_contract.schema
        return {
            "type": "object",
            "additionalProperties": True,
        }

    def _openai_text_format(self, output_contract: OutputContract) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "name": output_contract.schema_name,
            "schema": self._contract_schema(output_contract),
            "strict": bool(output_contract.strict),
        }

    def _google_structured_output_config(
        self, output_contract: OutputContract
    ) -> dict[str, Any]:
        return {
            "response_mime_type": "application/json",
            "response_schema": self._contract_schema(output_contract),
        }

    def _anthropic_structured_output_config(
        self, output_contract: OutputContract
    ) -> dict[str, Any]:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_contract.schema_name,
                    "schema": self._contract_schema(output_contract),
                },
            }
        }

    def _prune_google_unsupported_config(
        self,
        request_config: dict[str, Any],
        exc: Exception,
    ) -> list[str]:
        removed: list[str] = []
        drop_order = [
            "response_schema",
            "response_mime_type",
            "thinking_config",
            "candidate_count",
            "top_k",
            "top_p",
            "temperature",
        ]
        requested_key = self._infer_generic_unsupported_param_key(exc, request_config)
        if requested_key and requested_key in request_config:
            request_config.pop(requested_key, None)
            removed.append(requested_key)
            return removed
        message = str(exc).lower()
        for key in drop_order:
            if key in request_config and (key in message or "unsupported" in message or "unknown" in message):
                request_config.pop(key, None)
                removed.append(key)
                if "response" in key:
                    continue
                break
        return removed

    def _create_anthropic_message_with_model_compat(
        self,
        request: dict[str, Any],
        *,
        warnings: list[str],
    ) -> Any:
        candidate = dict(request)
        drop_order = ["response_format", "thinking", "top_p", "temperature"]
        last_exc: Exception | None = None
        for _ in range(8):
            try:
                return self._client.messages.create(**candidate)
            except Exception as exc:
                last_exc = exc
                message = str(exc).lower()
                if "unsupported" not in message and "unknown" not in message and "invalid" not in message:
                    raise
                drop_key = self._infer_generic_unsupported_param_key(exc, candidate)
                if drop_key is None:
                    for fallback_key in drop_order:
                        if fallback_key in candidate:
                            drop_key = fallback_key
                            break
                if not drop_key or drop_key not in candidate:
                    raise
                candidate.pop(drop_key, None)
                warnings.append(f"Anthropic SDK removed unsupported request key '{drop_key}'.")
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Failed to create Anthropic message after compatibility retries.")

    def _infer_generic_unsupported_param_key(
        self,
        exc: Exception,
        request: dict[str, Any],
    ) -> str | None:
        message = str(exc)
        patterns = (
            r"unsupported parameter[:\s]+['\"]?([A-Za-z0-9_.-]+)['\"]?",
            r"unknown parameter[:\s]+['\"]?([A-Za-z0-9_.-]+)['\"]?",
            r"invalid parameter[:\s]+['\"]?([A-Za-z0-9_.-]+)['\"]?",
            r"unexpected keyword argument ['\"]([A-Za-z0-9_.-]+)['\"]",
            r"field ['\"]([A-Za-z0-9_.-]+)['\"]",
            r"property ['\"]([A-Za-z0-9_.-]+)['\"]",
        )
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if not match:
                continue
            top_level = match.group(1).split(".", 1)[0].strip()
            if top_level in request:
                return top_level
        return None

    def _finalize_response_text(
        self,
        raw_output: str,
        *,
        output_contract: OutputContract | None,
        warnings: list[str],
    ) -> str:
        if output_contract is None or not output_contract.require_json:
            return (raw_output or "").strip()
        payload = self._extract_json_payload(raw_output)
        if payload is None:
            warnings.append("Model output was not valid JSON; returned JSON error envelope.")
            return json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_json_output",
                        "message": "Model output was not valid JSON.",
                    },
                    "raw_text": (raw_output or "").strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        is_valid, reason = self._validate_output_contract_payload(payload, output_contract)
        if not is_valid:
            warnings.append(f"Model output failed output contract validation: {reason}")
            return json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "output_contract_validation_failed",
                        "message": reason,
                    },
                    "data": payload,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _extract_json_payload(self, raw_output: str) -> Any | None:
        cleaned = (raw_output or "").strip()
        if not cleaned:
            return None
        direct = self._try_json_load(cleaned)
        if direct is not None:
            return direct
        for fenced in re.findall(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE):
            parsed = self._try_json_load(fenced.strip())
            if parsed is not None:
                return parsed
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            segment = cleaned[index:]
            try:
                parsed, _end = decoder.raw_decode(segment)
            except json.JSONDecodeError:
                continue
            return parsed
        return None

    def _try_json_load(self, candidate: str) -> Any | None:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    def _validate_output_contract_payload(
        self,
        payload: Any,
        output_contract: OutputContract,
    ) -> tuple[bool, str]:
        if output_contract.type == "json_object" and not isinstance(payload, dict):
            return False, "Expected top-level JSON object."
        if output_contract.type != "json_schema":
            return True, ""
        schema = self._contract_schema(output_contract)
        validator_status, validator_message = self._validate_with_jsonschema(payload, schema)
        if validator_status is True:
            return True, ""
        if validator_status is False:
            return False, validator_message
        return self._validate_schema_basic(payload, schema, path="$")

    def _validate_with_jsonschema(
        self, payload: Any, schema: dict[str, Any]
    ) -> tuple[bool | None, str]:
        try:
            from jsonschema import ValidationError, validate
        except Exception:
            return None, "jsonschema package unavailable for strict schema validation."
        try:
            validate(instance=payload, schema=schema)
        except ValidationError as exc:
            return False, str(exc.message or "Schema validation failed.")
        return True, ""

    def _validate_schema_basic(
        self,
        payload: Any,
        schema: dict[str, Any],
        *,
        path: str,
    ) -> tuple[bool, str]:
        expected_type = schema.get("type")
        if isinstance(expected_type, str) and not self._json_type_matches(payload, expected_type):
            return False, f"{path} expected type '{expected_type}'."
        if expected_type == "object" and isinstance(payload, dict):
            required = schema.get("required")
            if isinstance(required, list):
                for item in required:
                    key = str(item)
                    if key not in payload:
                        return False, f"{path}.{key} is required."
            properties = schema.get("properties")
            if isinstance(properties, dict):
                for key, subschema in properties.items():
                    if key not in payload or not isinstance(subschema, dict):
                        continue
                    valid, reason = self._validate_schema_basic(
                        payload[key],
                        subschema,
                        path=f"{path}.{key}",
                    )
                    if not valid:
                        return False, reason
        if expected_type == "array" and isinstance(payload, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(payload):
                    valid, reason = self._validate_schema_basic(
                        item,
                        item_schema,
                        path=f"{path}[{index}]",
                    )
                    if not valid:
                        return False, reason
        return True, ""

    def _json_type_matches(self, payload: Any, expected_type: str) -> bool:
        if expected_type == "object":
            return isinstance(payload, dict)
        if expected_type == "array":
            return isinstance(payload, list)
        if expected_type == "string":
            return isinstance(payload, str)
        if expected_type == "number":
            return isinstance(payload, (int, float)) and not isinstance(payload, bool)
        if expected_type == "integer":
            return isinstance(payload, int) and not isinstance(payload, bool)
        if expected_type == "boolean":
            return isinstance(payload, bool)
        if expected_type == "null":
            return payload is None
        return True

    def _run_subprocess(
        self,
        *,
        cmd: list[str],
        prompt: str | None,
        env: dict[str, str] | None = None,
    ) -> str:
        timeout_seconds = float(self._option_float("timeout_seconds", 180.0))
        run_env = dict(env or os.environ.copy())
        if self.config.provider == "openai":
            run_env.setdefault("OPENAI_API_KEY", self.config.api_key)
            run_env.setdefault("CODEX_API_KEY", self.config.api_key)
        elif self.config.provider == "google":
            run_env.setdefault("GOOGLE_API_KEY", self.config.api_key)
            run_env.setdefault("GEMINI_API_KEY", self.config.api_key)
        else:
            run_env.setdefault("ANTHROPIC_API_KEY", self.config.api_key)
        result = subprocess.run(
            cmd,
            input=prompt,
            text=True,
            capture_output=True,
            env=run_env,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            error_text = (result.stderr or "").strip() or (result.stdout or "").strip()
            raise RuntimeError(error_text or f"Command failed: {' '.join(cmd)}")
        return (result.stdout or "").strip()

    def _codex_config_overrides(self, request: AgentRequest) -> list[str]:
        overrides: list[str] = []
        for mcp in sorted(request.mcp_servers, key=lambda item: item.name):
            key = self._safe_codex_segment(mcp.name)
            overrides.append(self._codex_override(["mcp_servers", key, "url"], mcp.url))
            transport = mcp.transport or "streamable-http"
            overrides.append(self._codex_override(["mcp_servers", key, "transport"], transport))
            if mcp.timeout_seconds is not None:
                overrides.append(
                    self._codex_override(["mcp_servers", key, "timeout"], int(mcp.timeout_seconds))
                )
            if mcp.sse_read_timeout_seconds is not None:
                overrides.append(
                    self._codex_override(
                        ["mcp_servers", key, "sse_read_timeout"],
                        int(mcp.sse_read_timeout_seconds),
                    )
                )
            for header_key, header_value in sorted(mcp.headers.items()):
                overrides.append(
                    self._codex_override(
                        ["mcp_servers", key, "headers", header_key],
                        header_value,
                    )
                )

        skill_entries: list[str] = []
        for skill in request.skills:
            if not skill.enabled or not str(skill.path or "").strip():
                continue
            skill_path = str(Path(skill.path).expanduser().resolve())
            escaped = self._toml_escape(skill_path)
            skill_entries.append(f"{{enabled=true,path=\"{escaped}\"}}")
        if skill_entries:
            overrides.append(f"skills.config=[{','.join(skill_entries)}]")
        return overrides

    def _safe_codex_segment(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
        return cleaned or "mcp"

    def _codex_override(self, key_path: list[str], value: Any) -> str:
        return f"{self._format_codex_key_path(key_path)}={self._toml_value(value)}"

    def _format_codex_key_path(self, segments: list[str]) -> str:
        rendered: list[str] = []
        for segment in segments:
            if re.fullmatch(r"[A-Za-z0-9_-]+", segment):
                rendered.append(segment)
                continue
            escaped = segment.replace("\\", "\\\\").replace('"', '\\"')
            rendered.append(f'"{escaped}"')
        return ".".join(rendered)

    def _toml_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(value)
        escaped = self._toml_escape(str(value))
        return f'"{escaped}"'

    def _toml_escape(self, value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    def _normalize_transport(self, transport: str | None) -> str:
        value = str(transport or "").strip().lower()
        if value in {"streamable-http", "streamable_http", "streamablehttp"}:
            return "http"
        return value

    def _render_transcript(self, conversation: list[dict[str, str]]) -> str:
        parts: list[str] = []
        for message in conversation:
            role = str(message.get("role") or "user").strip().upper()
            content = str(message.get("content") or "").strip()
            parts.append(f"[{role}]\n{content}")
        return "\n\n".join(parts)

    def _extract_tool_call(self, output_text: str) -> dict[str, Any] | None:
        raw = (output_text or "").strip()
        if not raw:
            return None

        candidates = [raw]
        fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if "tool_call" in payload and isinstance(payload["tool_call"], dict):
                call = payload["tool_call"]
                return {
                    "name": call.get("name"),
                    "arguments": call.get("arguments") or {},
                }
            if "name" in payload and "arguments" in payload:
                return {
                    "name": payload.get("name"),
                    "arguments": payload.get("arguments") or {},
                }
        return None

    def _create_openai_response_with_model_compat(self, request: dict[str, Any]) -> Any:
        optional_drop_order = ["reasoning", "text", "temperature", "top_p"]
        required_keys = {"model", "input"}
        candidate = dict(request)
        last_exc: Exception | None = None
        for _ in range(8):
            try:
                return self._client.responses.create(**candidate)
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable_openai_param_error(exc):
                    raise
                drop_key = self._infer_openai_unsupported_param_key(exc, candidate)
                if drop_key is None:
                    for fallback_key in optional_drop_order:
                        if fallback_key in candidate:
                            drop_key = fallback_key
                            break
                if not drop_key or drop_key in required_keys or drop_key not in candidate:
                    raise
                candidate.pop(drop_key, None)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Failed to create OpenAI response after compatibility retries.")

    def _is_retryable_openai_param_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code not in (400, 422):
            return False
        message = self._openai_error_message(exc).lower()
        needles = (
            "unsupported parameter",
            "unknown parameter",
            "not supported",
            "is not supported",
            "invalid parameter",
            "unrecognized request argument",
        )
        return any(needle in message for needle in needles)

    def _infer_openai_unsupported_param_key(
        self, exc: Exception, request: dict[str, Any]
    ) -> str | None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error_obj = body.get("error")
            if isinstance(error_obj, dict):
                param = error_obj.get("param")
                if isinstance(param, str) and param:
                    top_level = param.split(".", 1)[0].strip()
                    if top_level in request:
                        return top_level

        message = self._openai_error_message(exc)
        patterns = (
            r"unsupported parameter:\s*'([^']+)'",
            r'unsupported parameter:\s*"([^"]+)"',
            r"unknown parameter:\s*'([^']+)'",
            r'unknown parameter:\s*"([^"]+)"',
            r"unrecognized request argument:\s*'([^']+)'",
            r'unrecognized request argument:\s*"([^"]+)"',
            r"parameter\s*'([^']+)'",
            r'parameter\s*"([^"]+)"',
        )
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if not match:
                continue
            top_level = match.group(1).split(".", 1)[0].strip()
            if top_level in request:
                return top_level
        return None

    def _openai_error_message(self, exc: Exception) -> str:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error_obj = body.get("error")
            if isinstance(error_obj, dict):
                message = error_obj.get("message")
                if isinstance(message, str) and message:
                    return message
        return str(exc)

    def _option_str(self, key: str, default: str) -> str:
        value = self.config.provider_options.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    def _option_float(self, key: str, default: float) -> float:
        value = self.config.provider_options.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _unique_in_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
