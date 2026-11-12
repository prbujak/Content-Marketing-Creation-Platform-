from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BRANDS_DIR = DATA_DIR / "brands"
CAMPAIGNS_DIR = DATA_DIR / "campaigns"
CATALOG_DIR = DATA_DIR / "catalog"

for directory in (BRANDS_DIR, CAMPAIGNS_DIR, CATALOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)


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
    return _read_json(BRANDS_DIR / f"{brand_id}.json")


def save_brand(payload: dict[str, Any]) -> dict[str, Any]:
    brand_id = payload.get("id") or f"brand-{uuid4().hex[:8]}"
    payload["id"] = brand_id
    return _write_json(BRANDS_DIR / f"{brand_id}.json", payload)


def update_brand(brand_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_brand(brand_id)
    if not existing:
        return None
    existing.update(updates)
    existing["id"] = brand_id
    return save_brand(existing)


def list_campaigns(brand_id: str | None = None) -> list[dict[str, Any]]:
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
    return _read_json(CAMPAIGNS_DIR / f"{campaign_id}.json")


def save_campaign(payload: dict[str, Any]) -> dict[str, Any]:
    campaign_id = payload.get("id") or f"campaign-{uuid4().hex[:8]}"
    payload["id"] = campaign_id
    return _write_json(CAMPAIGNS_DIR / f"{campaign_id}.json", payload)


def list_catalog(brand_id: str | None = None) -> list[dict[str, Any]]:
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
    item_id = payload.get("id") or f"item-{uuid4().hex[:8]}"
    payload["id"] = item_id
    return _write_json(CATALOG_DIR / f"{item_id}.json", payload)
