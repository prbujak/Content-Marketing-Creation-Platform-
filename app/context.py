from __future__ import annotations

from contextvars import ContextVar

_owner_id: ContextVar[str] = ContextVar("owner_id", default="local-dev-user")


def set_owner_id(owner_id: str):
    return _owner_id.set((owner_id or "local-dev-user").strip() or "local-dev-user")


def reset_owner_id(token) -> None:
    _owner_id.reset(token)


def current_owner_id() -> str:
    return _owner_id.get()
