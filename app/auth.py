from __future__ import annotations

import os
import time
from typing import Any

import jwt
import requests
from fastapi import HTTPException, Request


_JWKS_CACHE: dict[str, Any] = {"fetched_at": 0.0, "keys": {}}
_ALLOWED_ALGORITHMS = ["RS256"]
_DEFAULT_ISSUER = "https://api.cursor.com/apps/identity"


def _is_local_dev() -> bool:
    """Allow simulated identity only on a true local runtime.

    Mirrors cursor/identity.js: any published/hosted marker (CURSOR_APP_ID or
    VERCEL) forces real token verification and never trusts a simulated user.
    """
    if (os.getenv("CURSOR_APP_ID") or "").strip():
        return False
    if (os.getenv("VERCEL") or "").strip():
        return False
    return True


def _issuer() -> str:
    return (os.getenv("CURSOR_APP_IDENTITY_ISSUER") or _DEFAULT_ISSUER).rstrip("/")


def _get_jwks() -> dict[str, Any]:
    now = time.time()
    if _JWKS_CACHE["keys"] and now - float(_JWKS_CACHE["fetched_at"]) < 3600:
        return _JWKS_CACHE["keys"]
    issuer = _issuer()
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
    """Require a verified Cursor identity outside local development."""
    if _is_local_dev():
        return _simulate_local_identity()

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    app_id = (os.getenv("CURSOR_APP_ID") or "").strip()
    if not app_id:
        # Hosted runtime without app id must fail closed — never simulate.
        raise HTTPException(status_code=401, detail="Identity configuration unavailable.")

    issuer = _issuer()

    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg not in _ALLOWED_ALGORITHMS:
            raise HTTPException(status_code=401, detail="Unsupported identity token algorithm.")

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
            algorithms=_ALLOWED_ALGORITHMS,
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
