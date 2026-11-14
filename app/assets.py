from __future__ import annotations

import os
from pathlib import Path

from .context import current_owner_id
from .storage import OwnershipError, sanitize_id


OWNER_MARKER = ".owner"


def mark_generated_owner(asset_root: Path, owner_id: str | None = None) -> None:
    """Stamp a generated asset directory with the owning caller."""
    owner = (owner_id or current_owner_id()).strip() or "local-dev-user"
    asset_root.mkdir(parents=True, exist_ok=True)
    marker = asset_root / OWNER_MARKER
    if marker.exists():
        existing = marker.read_text(encoding="utf-8").strip()
        if existing and existing != owner:
            raise OwnershipError("Generated asset belongs to another user.")
    marker.write_text(owner, encoding="utf-8")


def resolve_generated_file(generated_root: Path, asset_path: str) -> tuple[Path, Path]:
    """Return (file_path, top_level_asset_dir) under generated_root, rejecting traversal."""
    cleaned = (asset_path or "").strip().lstrip("/")
    if not cleaned:
        raise OwnershipError("Invalid generated asset path.")
    raw_parts = [part for part in cleaned.split("/") if part]
    if not raw_parts or any(part in {".", ".."} for part in raw_parts):
        raise OwnershipError("Invalid generated asset path.")

    top = sanitize_id(raw_parts[0], label="asset_id")
    root = generated_root.resolve()
    top_dir = (root / top).resolve()
    if top_dir != root and not str(top_dir).startswith(str(root) + os.sep):
        raise OwnershipError("Invalid generated asset path.")

    safe_parts = [top, *raw_parts[1:]]
    for part in safe_parts[1:]:
        if "/" in part or "\\" in part or part in {".", ".."}:
            raise OwnershipError("Invalid generated asset path.")

    file_path = root.joinpath(*safe_parts).resolve()
    if file_path != root and not str(file_path).startswith(str(root) + os.sep):
        raise OwnershipError("Invalid generated asset path.")
    if file_path.name == OWNER_MARKER:
        raise OwnershipError("Not found.")
    return file_path, top_dir


def assert_generated_owner(asset_root: Path, owner_id: str | None = None) -> None:
    owner = (owner_id or current_owner_id()).strip() or "local-dev-user"
    marker = asset_root / OWNER_MARKER
    if not marker.exists():
        # Legacy unmarked local assets remain readable only in local-dev.
        if owner == "local-dev-user":
            return
        raise OwnershipError("Generated asset owner is unknown.")
    recorded = marker.read_text(encoding="utf-8").strip()
    if recorded != owner:
        raise OwnershipError("Generated asset belongs to another user.")
