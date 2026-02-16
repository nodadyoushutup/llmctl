from __future__ import annotations

import json
from pathlib import Path

from core.config import Config


def _safe_model_manifest(model_dir: Path) -> dict[str, str]:
    manifest_path = model_dir / "model.json"
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, str] = {}
    for key in ("name", "model", "description"):
        value = payload.get(key)
        if isinstance(value, str):
            normalized[key] = value.strip()
    return normalized


def discover_vllm_local_models() -> list[dict[str, str]]:
    discovered: list[dict[str, str]] = []
    seen_values: set[str] = set()
    roots = (("custom", Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR)),)
    for source, root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not entry.is_dir():
                continue
            manifest = _safe_model_manifest(entry)
            value = manifest.get("model") or str(entry)
            value = value.strip()
            if not value or value in seen_values:
                continue
            label = manifest.get("name") or entry.name
            description = manifest.get("description") or ""
            discovered.append(
                {
                    "value": value,
                    "label": label,
                    "source": source,
                    "path": str(entry),
                    "description": description,
                }
            )
            seen_values.add(value)
    fallback_model = Config.VLLM_LOCAL_FALLBACK_MODEL.strip()
    if fallback_model and fallback_model not in seen_values:
        discovered.insert(
            0,
            {
                "value": fallback_model,
                "label": fallback_model,
                "source": "custom",
                "path": "",
                "description": "Configured fallback local model.",
            },
        )
    return discovered
