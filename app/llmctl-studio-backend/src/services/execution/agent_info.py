from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

    @classmethod
    def from_payload(cls, payload: Any) -> "AgentInfo" | None:
        if payload is None:
            return None
        if isinstance(payload, cls):
            return payload
        if isinstance(payload, dict):
            raw_id = payload.get("id")
            try:
                identifier = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                identifier = None
            name = str(payload.get("name") or "")
            description = str(payload.get("description") or "").strip() or name
            return cls(id=identifier, name=name, description=description)
        return None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "description": self.description,
        }
        if self.id is not None:
            payload["id"] = self.id
        return payload


def coerce_agent_profile_payload(value: Any) -> dict[str, Any]:
    info = AgentInfo.from_payload(value)
    if info is not None:
        return dict(info.to_payload())
    if isinstance(value, dict):
        return dict(value)
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        payload = to_payload()
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def build_agent_payload(agent: Any) -> dict[str, object]:
    return AgentInfo.from_model(agent).to_payload()
