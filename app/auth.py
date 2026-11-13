from __future__ import annotations

import os
import time
from typing import Any

import jwt
import requests
from fastapi import HTTPException, Request


_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "keys": {}}


def _is_published_runtime() -> bool:
    return bool((os.getenv("CURSOR_APP_ID") or "").strip())


def _issuer() -> str:
    return (os.getenv("CURSOR_APP_IDENTITY_ISSUER") or "").rstrip("/")


def _get_jwks() -> dict[str, Any]:
    now = time.time()
    if _JWKS_CACHE["keys"] and now - float(_JWKS_CACHE["fetched_at"]) < 3600:
        return _JWKS_CACHE["keys"]
    issuer = _issuer()
    if not issuer:
        return {}
    response = requests.get(f"{issuer}/keys", timeout=10)
    response.raise_for_status()
    payload = response.json()
    keys = {}
    for item in payload.get("keys") or []:
        kid = item.get("kid")
        if kid:
            keys[kid] = item
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["fetched_at"] = now
    return keys


def _extract_token(request: Request) -> str | None:
    for header in ("x-cursor-identity-v2", "x-cursor-identity"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _simulate_local_identity() -> dict[str, Any]:
    return {
        "verified": True,
        "simulated": True,
        "sub": "local-dev-user",
        "email": "dev@example.com",
        "name": "Local Developer",
        "kind": "person",
        "appVisibility": "team",
        "teamRole": "admin",
    }


def verify_request_identity(request: Request) -> dict[str, Any]:
    """Require a verified Cursor identity in published runtime; simulate locally."""
    if not _is_published_runtime():
        return _simulate_local_identity()

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    app_id = (os.getenv("CURSOR_APP_ID") or "").strip()
    issuer = _issuer()
    if not app_id or not issuer:
        raise HTTPException(status_code=401, detail="Identity configuration unavailable.")

    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        keys = _get_jwks()
        jwk = keys.get(kid) if kid else None
        if not jwk:
            # Refresh once if kid missing from cache.
            _JWKS_CACHE["fetched_at"] = 0
            keys = _get_jwks()
            jwk = keys.get(kid) if kid else None
        if not jwk:
            raise HTTPException(status_code=401, detail="Unknown identity key.")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=[header.get("alg") or "RS256"],
            audience=app_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid identity token.") from exc

    return {
        "verified": True,
        "simulated": False,
        "sub": claims.get("sub"),
        "email": claims.get("email") or "",
        "name": claims.get("name") or "",
        "kind": claims.get("kind") or "person",
        "appVisibility": claims.get("app_visibility") or "",
        "teamRole": claims.get("team_role") or "",
        "claims": claims,
    }
