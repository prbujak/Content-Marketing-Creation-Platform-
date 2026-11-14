from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import db
from .context import current_owner_id


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BRANDS_DIR = DATA_DIR / "brands"
CAMPAIGNS_DIR = DATA_DIR / "campaigns"
CATALOG_DIR = DATA_DIR / "catalog"
AUDIENCES_DIR = DATA_DIR / "audiences"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
CONTENT_DIR = DATA_DIR / "content"

SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")

KIND_DIRS = {
    "brand": BRANDS_DIR,
    "campaign": CAMPAIGNS_DIR,
    "catalog": CATALOG_DIR,
    "audience": AUDIENCES_DIR,
    "knowledge": KNOWLEDGE_DIR,
    "content": CONTENT_DIR,
}

for directory in KIND_DIRS.values():
    directory.mkdir(parents=True, exist_ok=True)


def sanitize_id(value: str, *, label: str = "id") -> str:
    cleaned = (value or "").strip()
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"Invalid {label}.")
    cleaned = cleaned[:120]
    if not cleaned or not SAFE_ID_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid {label}.")
    return cleaned


def _safe_json_path(directory: Path, item_id: str, *, label: str) -> Path:
    safe_id = sanitize_id(item_id, label=label)
    root = directory.resolve()
    path = (directory / f"{safe_id}.json").resolve()
    if path.parent != root:
        raise ValueError(f"Invalid {label} path.")
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return payload


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_owner(owner_id: str | None) -> str:
    owner = (owner_id or "local-dev-user").strip() or "local-dev-user"
    return owner[:180]


def _owns(payload: dict[str, Any] | None, owner_id: str) -> bool:
    if not payload:
        return False
    recorded = (payload.get("owner_id") or "").strip()
    # Legacy local records without owner remain visible only to local-dev-user.
    if not recorded:
        return owner_id == "local-dev-user"
    return recorded == owner_id


def _upsert_record(kind: str, payload: dict[str, Any], *, owner_id: str) -> dict[str, Any]:
    item_id = sanitize_id(payload["id"], label=f"{kind}_id")
    owner = _normalize_owner(owner_id)
    payload["id"] = item_id
    payload["owner_id"] = owner
    brand_id = payload.get("brand_id")
    if brand_id:
        payload["brand_id"] = sanitize_id(str(brand_id), label="brand_id")

    if db.using_postgres():
        db.execute(
            """
            insert into records (kind, id, owner_id, brand_id, payload, updated_at)
            values (%s, %s, %s, %s, %s::jsonb, now())
            on conflict (kind, id) do update set
              owner_id = excluded.owner_id,
              brand_id = excluded.brand_id,
              payload = excluded.payload,
              updated_at = now()
            """,
            (
                kind,
                item_id,
                owner,
                payload.get("brand_id"),
                json.dumps(payload),
            ),
        )
        return payload

    directory = KIND_DIRS[kind]
    return _write_json(_safe_json_path(directory, item_id, label=f"{kind}_id"), payload)


def _get_record(kind: str, item_id: str, *, owner_id: str) -> dict[str, Any] | None:
    safe_id = sanitize_id(item_id, label=f"{kind}_id")
    owner = _normalize_owner(owner_id)
    if db.using_postgres():
        row = db.fetch_one(
            """
            select payload
            from records
            where kind = %s and id = %s and owner_id = %s
            """,
            (kind, safe_id, owner),
        )
        if not row:
            return None
        payload = row["payload"]
        return payload if isinstance(payload, dict) else json.loads(payload)

    payload = _read_json(_safe_json_path(KIND_DIRS[kind], safe_id, label=f"{kind}_id"))
    return payload if _owns(payload, owner) else None


def _list_records(
    kind: str,
    *,
    owner_id: str,
    brand_id: str | None = None,
) -> list[dict[str, Any]]:
    owner = _normalize_owner(owner_id)
    if brand_id is not None:
        brand_id = sanitize_id(brand_id, label="brand_id")

    if db.using_postgres():
        if brand_id:
            rows = db.fetch_all(
                """
                select payload
                from records
                where kind = %s and owner_id = %s and brand_id = %s
                order by updated_at desc
                """,
                (kind, owner, brand_id),
            )
        else:
            rows = db.fetch_all(
                """
                select payload
                from records
                where kind = %s and owner_id = %s
                order by updated_at desc
                """,
                (kind, owner),
            )
        items = []
        for row in rows:
            payload = row["payload"]
            items.append(payload if isinstance(payload, dict) else json.loads(payload))
        return items

    items = []
    for path in sorted(
        KIND_DIRS[kind].glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        data = _read_json(path)
        if not data or not _owns(data, owner):
            continue
        if brand_id and data.get("brand_id") != brand_id:
            continue
        items.append(data)
    return items


def list_brands(*, owner_id: str | None = None) -> list[dict[str, Any]]:
    return _list_records("brand", owner_id=owner_id or current_owner_id())


def get_brand(brand_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    return _get_record("brand", brand_id, owner_id=owner_id or current_owner_id())


def save_brand(payload: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    brand_id = sanitize_id(payload.get("id") or f"brand-{uuid4().hex[:8]}", label="brand_id")
    payload["id"] = brand_id
    return _upsert_record("brand", payload, owner_id=owner_id or current_owner_id())


def update_brand(brand_id: str, updates: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any] | None:
    owner = owner_id or current_owner_id()
    existing = get_brand(brand_id, owner_id=owner)
    if not existing:
        return None
    existing.update(updates)
    existing["id"] = sanitize_id(brand_id, label="brand_id")
    return save_brand(existing, owner_id=owner)


def list_campaigns(*, owner_id: str | None = None, brand_id: str | None = None) -> list[dict[str, Any]]:
    return _list_records("campaign", owner_id=owner_id or current_owner_id(), brand_id=brand_id)


def get_campaign(campaign_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    return _get_record("campaign", campaign_id, owner_id=owner_id or current_owner_id())


def save_campaign(payload: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    campaign_id = sanitize_id(payload.get("id") or f"campaign-{uuid4().hex[:8]}", label="campaign_id")
    payload["id"] = campaign_id
    return _upsert_record("campaign", payload, owner_id=owner_id or current_owner_id())


def list_catalog(*, owner_id: str | None = None, brand_id: str | None = None) -> list[dict[str, Any]]:
    return _list_records("catalog", owner_id=owner_id or current_owner_id(), brand_id=brand_id)


def save_catalog_item(payload: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    item_id = sanitize_id(payload.get("id") or f"item-{uuid4().hex[:8]}", label="item_id")
    payload["id"] = item_id
    return _upsert_record("catalog", payload, owner_id=owner_id or current_owner_id())


def list_audiences(*, owner_id: str | None = None, brand_id: str | None = None) -> list[dict[str, Any]]:
    return _list_records("audience", owner_id=owner_id or current_owner_id(), brand_id=brand_id)


def save_audience(payload: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    item_id = sanitize_id(payload.get("id") or f"aud-{uuid4().hex[:8]}", label="audience_id")
    payload["id"] = item_id
    return _upsert_record("audience", payload, owner_id=owner_id or current_owner_id())


def get_audience(audience_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    return _get_record("audience", audience_id, owner_id=owner_id or current_owner_id())


def list_knowledge(*, owner_id: str | None = None, brand_id: str | None = None) -> list[dict[str, Any]]:
    return _list_records("knowledge", owner_id=owner_id or current_owner_id(), brand_id=brand_id)


def save_knowledge(payload: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    item_id = sanitize_id(payload.get("id") or f"know-{uuid4().hex[:8]}", label="knowledge_id")
    payload["id"] = item_id
    return _upsert_record("knowledge", payload, owner_id=owner_id or current_owner_id())


def list_content(*, owner_id: str | None = None, brand_id: str | None = None) -> list[dict[str, Any]]:
    return _list_records("content", owner_id=owner_id or current_owner_id(), brand_id=brand_id)


def save_content(payload: dict[str, Any], *, owner_id: str | None = None) -> dict[str, Any]:
    item_id = sanitize_id(payload.get("id") or f"content-{uuid4().hex[:8]}", label="content_id")
    payload["id"] = item_id
    return _upsert_record("content", payload, owner_id=owner_id or current_owner_id())


def get_content(content_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    return _get_record("content", content_id, owner_id=owner_id or current_owner_id())
