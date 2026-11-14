from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.time()
        with self._lock:
            bucket = self._events[key]
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Try again in {window_seconds} seconds.",
                )
            bucket.append(now)


limiter = RateLimiter()

# Route prefixes / exact paths that are expensive.
EXPENSIVE_LIMITS = {
    "/api/brand-dna": (8, 60),
    "/api/campaigns/generate": (4, 60),
    "/api/creatives/edit": (8, 60),
    "/api/instant-magic": (10, 60),
    "/api/photoshoot": (3, 60),
    "/api/brand-book": (6, 60),
    "/api/website": (6, 60),
    "/api/social-calendar": (8, 60),
    "/api/localize": (10, 60),
    "/api/brand-agent": (12, 60),
    "/api/campaign-ideas": (12, 60),
    "/api/generate": (4, 60),
}


def enforce_expensive_rate_limit(request: Request, identity_sub: str = "anonymous") -> None:
    path = request.url.path.rstrip("/") or "/"
    matched = None
    for prefix, conf in EXPENSIVE_LIMITS.items():
        if path == prefix or path.startswith(prefix + "/"):
            matched = conf
            break
    if not matched:
        return
    limit, window = matched
    client = request.client.host if request.client else "unknown"
    key = f"{identity_sub}:{client}:{path}"
    limiter.check(key, limit=limit, window_seconds=window)
