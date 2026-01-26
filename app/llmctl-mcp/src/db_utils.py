from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, select
from sqlalchemy import inspect as sa_inspect

from constants import MODEL_REGISTRY, READONLY_COLUMNS


def _normalize_model_name(model_name: str) -> str:
    return model_name.strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_model(model_name: str):
    if not model_name:
        raise ValueError("Model name is required.")
    key = _normalize_model_name(model_name)
    model = MODEL_REGISTRY.get(key)
    if model is None:
        known = sorted({cls.__name__ for cls in MODEL_REGISTRY.values()})
        raise ValueError(f"Unknown model '{model_name}'. Available: {', '.join(known)}")
    return model


def _column_map(model) -> dict[str, Any]:
    mapper = sa_inspect(model)
    return {column.key: column for column in mapper.columns}


def _relationship_map(model) -> dict[str, Any]:
    mapper = sa_inspect(model)
    return {rel.key: rel for rel in mapper.relationships}


def _coerce_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(column.type, Integer):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value
    if isinstance(column.type, DateTime):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_relationships(obj, include: bool) -> dict[str, Any]:
    if not include:
        return {}
    data: dict[str, Any] = {}
    mapper = sa_inspect(obj.__class__)
    for rel in mapper.relationships:
        key = rel.key
        if rel.uselist:
            items = getattr(obj, key) or []
            data[f"{key}_ids"] = [getattr(item, "id", None) for item in items]
        else:
            item = getattr(obj, key)
            data[f"{key}_id"] = getattr(item, "id", None) if item else None
    return data


def _serialize_model(obj, include_relationships: bool = False) -> dict[str, Any]:
    data = {}
    for column in sa_inspect(obj.__class__).columns:
        data[column.key] = _serialize_value(getattr(obj, column.key))
    data.update(_serialize_relationships(obj, include_relationships))
    return data


def _apply_relationship(obj, rel_key: str, value: Any, session) -> None:
    relationships = _relationship_map(obj.__class__)
    rel = relationships[rel_key]
    related_cls = rel.mapper.class_

    def _coerce_id(raw: Any) -> int:
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        raise ValueError(f"Relationship '{rel_key}' expects an id.")

    if rel.uselist:
        if value is None:
            setattr(obj, rel_key, [])
            return
        if not isinstance(value, list):
            raise ValueError(f"Relationship '{rel_key}' expects a list of ids.")
        if not value:
            setattr(obj, rel_key, [])
            return
        ids = [_coerce_id(item_id) for item_id in value]
        items = (
            session.execute(select(related_cls).where(related_cls.id.in_(ids)))
            .scalars()
            .all()
        )
        items_by_id = {item.id: item for item in items}
        ordered = [items_by_id[item_id] for item_id in ids if item_id in items_by_id]
        setattr(obj, rel_key, ordered)
    else:
        if value is None:
            setattr(obj, rel_key, None)
            return
        item_id = _coerce_id(value)
        item = session.get(related_cls, item_id)
        if item is None:
            raise ValueError(f"Related id {item_id} not found for '{rel_key}'.")
        setattr(obj, rel_key, item)


def _apply_data(obj, data: dict[str, Any], session) -> None:
    if not isinstance(data, dict):
        raise ValueError("Data must be a dictionary.")
    columns = _column_map(obj.__class__)
    relationships = _relationship_map(obj.__class__)
    unknown = set(data.keys()) - set(columns.keys()) - set(relationships.keys())
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    for key, value in data.items():
        if key in columns:
            if key in READONLY_COLUMNS:
                continue
            setattr(obj, key, _coerce_value(columns[key], value))
        elif key in relationships:
            _apply_relationship(obj, key, value, session)


def _clamp_limit(limit: int | None, max_limit: int) -> int | None:
    if limit is None:
        return None
    limit = max(0, int(limit))
    return min(limit, max_limit)
