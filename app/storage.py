from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BRANDS_DIR = DATA_DIR / "brands"
CAMPAIGNS_DIR = DATA_DIR / "campaigns"
CATALOG_DIR = DATA_DIR / "catalog"

SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")

for directory in (BRANDS_DIR, CAMPAIGNS_DIR, CATALOG_DIR):
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
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_brands() -> list[dict[str, Any]]:
    brands = []
    for path in sorted(BRANDS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = _read_json(path)
        if data:
            brands.append(data)
    return brands


def get_brand(brand_id: str) -> dict[str, Any] | None:
    return _read_json(_safe_json_path(BRANDS_DIR, brand_id, label="brand_id"))


def save_brand(payload: dict[str, Any]) -> dict[str, Any]:
    brand_id = sanitize_id(payload.get("id") or f"brand-{uuid4().hex[:8]}", label="brand_id")
    payload["id"] = brand_id
    return _write_json(_safe_json_path(BRANDS_DIR, brand_id, label="brand_id"), payload)


def update_brand(brand_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_brand(brand_id)
    if not existing:
        return None
    existing.update(updates)
    existing["id"] = sanitize_id(brand_id, label="brand_id")
    return save_brand(existing)


def list_campaigns(brand_id: str | None = None) -> list[dict[str, Any]]:
    if brand_id is not None:
        brand_id = sanitize_id(brand_id, label="brand_id")
    campaigns = []
    for path in sorted(CAMPAIGNS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = _read_json(path)
        if not data:
            continue
        if brand_id and data.get("brand_id") != brand_id:
            continue
        campaigns.append(data)
    return campaigns


def get_campaign(campaign_id: str) -> dict[str, Any] | None:
    return _read_json(_safe_json_path(CAMPAIGNS_DIR, campaign_id, label="campaign_id"))


def save_campaign(payload: dict[str, Any]) -> dict[str, Any]:
    campaign_id = sanitize_id(payload.get("id") or f"campaign-{uuid4().hex[:8]}", label="campaign_id")
    payload["id"] = campaign_id
    if payload.get("brand_id"):
        payload["brand_id"] = sanitize_id(str(payload["brand_id"]), label="brand_id")
    return _write_json(_safe_json_path(CAMPAIGNS_DIR, campaign_id, label="campaign_id"), payload)


def list_catalog(brand_id: str | None = None) -> list[dict[str, Any]]:
    if brand_id is not None:
        brand_id = sanitize_id(brand_id, label="brand_id")
    items = []
    for path in sorted(CATALOG_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = _read_json(path)
        if not data:
            continue
        if brand_id and data.get("brand_id") != brand_id:
            continue
        items.append(data)
    return items


def save_catalog_item(payload: dict[str, Any]) -> dict[str, Any]:
    item_id = sanitize_id(payload.get("id") or f"item-{uuid4().hex[:8]}", label="item_id")
    payload["id"] = item_id
    if payload.get("brand_id"):
        payload["brand_id"] = sanitize_id(str(payload["brand_id"]), label="brand_id")
    return _write_json(_safe_json_path(CATALOG_DIR, item_id, label="item_id"), payload)
