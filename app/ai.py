from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import requests


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TEXT_MODEL = "openai/gpt-4o-mini"
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image-preview"
DEFAULT_TEXT_FALLBACKS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.0-flash-001",
]
DEFAULT_IMAGE_FALLBACKS = [
    "google/gemini-2.5-flash-image-preview",
    "black-forest-labs/flux.2-flex",
]


def ai_status() -> dict[str, Any]:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    return {
        "enabled": bool(key),
        "provider": "openrouter",
        "text_model": os.getenv("OPENROUTER_TEXT_MODEL", DEFAULT_TEXT_MODEL),
        "image_model": os.getenv("OPENROUTER_IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
        "text_fallbacks": DEFAULT_TEXT_FALLBACKS,
        "image_fallbacks": DEFAULT_IMAGE_FALLBACKS,
        "mode": "live" if key else "sample_fallback",
        "message": (
            "OpenRouter connected."
            if key
            else "Sample mode: add OPENROUTER_API_KEY in Cursor Secrets for live multi-model generation."
        ),
    }


def _headers() -> dict[str, str] | None:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return None
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://emarketster.local",
        "X-Title": "eMarketster",
    }


def chat_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1800,
) -> dict[str, Any] | None:
    headers = _headers()
    if not headers:
        return None

    primary = model or os.getenv("OPENROUTER_TEXT_MODEL", DEFAULT_TEXT_MODEL)
    payload: dict[str, Any] = {
        "model": primary,
        "models": [primary] + [m for m in DEFAULT_TEXT_FALLBACKS if m != primary],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return json.loads(content)
    except Exception:
        return None


def chat_text(
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1200,
) -> str | None:
    headers = _headers()
    if not headers:
        return None
    primary = model or os.getenv("OPENROUTER_TEXT_MODEL", DEFAULT_TEXT_MODEL)
    payload = {
        "model": primary,
        "models": [primary] + [m for m in DEFAULT_TEXT_FALLBACKS if m != primary],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            ).strip()
        return str(content).strip()
    except Exception:
        return None


def generate_image_bytes(
    prompt: str,
    *,
    model: str | None = None,
    aspect_ratio: str = "1:1",
) -> bytes | None:
    headers = _headers()
    if not headers:
        return None

    primary = model or os.getenv("OPENROUTER_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
    payload: dict[str, Any] = {
        "model": primary,
        "models": [primary] + [m for m in DEFAULT_IMAGE_FALLBACKS if m != primary],
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect_ratio, "image_size": "1K"},
    }
    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        images = message.get("images") or []
        if not images:
            return None
        data_url = images[0].get("image_url", {}).get("url") or ""
        match = re.match(r"data:image/[^;]+;base64,(.+)", data_url, flags=re.DOTALL)
        if not match:
            return None
        return base64.b64decode(match.group(1))
    except Exception:
        return None


def enrich_brand_voice(brand: dict[str, Any]) -> dict[str, Any]:
    result = chat_json(
        system=(
            "You are a brand strategist. Return JSON with keys: "
            "primary_tone, secondary_tone, style_rules (array of 4 short strings), "
            "do (array of 3), dont (array of 3), sample_phrases (array of 3)."
        ),
        user=json.dumps(
            {
                "name": brand.get("name"),
                "tagline": brand.get("tagline"),
                "description": brand.get("description"),
                "keywords": brand.get("keywords"),
                "values": brand.get("values"),
                "extra_notes": brand.get("extra_notes"),
                "current_voice": brand.get("voice"),
            }
        ),
        temperature=0.5,
    )
    if not result:
        return brand
    voice = brand.get("voice") or {}
    voice.update(
        {
            "primary_tone": result.get("primary_tone") or voice.get("primary_tone"),
            "secondary_tone": result.get("secondary_tone") or voice.get("secondary_tone"),
            "style_rules": result.get("style_rules") or voice.get("style_rules"),
            "do": result.get("do") or voice.get("do"),
            "dont": result.get("dont") or voice.get("dont"),
            "sample_phrases": result.get("sample_phrases") or voice.get("sample_phrases"),
            "ai_enriched": True,
        }
    )
    brand["voice"] = voice
    if result.get("tagline_ refinement") or result.get("refined_tagline"):
        brand["tagline"] = result.get("refined_tagline") or brand.get("tagline")
    return brand


def ai_campaign_ideas(
    brand: dict[str, Any],
    product_name: str = "",
    custom_prompt: str = "",
) -> list[dict[str, str]] | None:
    result = chat_json(
        system=(
            "You are a senior campaign strategist for Jasper-style multi-channel marketing. "
            "Return JSON: {\"ideas\":[{\"title\",\"angle\",\"objective\",\"channels\"}]} with 6 ideas."
        ),
        user=json.dumps(
            {
                "brand": {
                    "name": brand.get("name"),
                    "tagline": brand.get("tagline"),
                    "description": brand.get("description"),
                    "voice": brand.get("voice"),
                    "keywords": brand.get("keywords"),
                },
                "product_name": product_name,
                "custom_prompt": custom_prompt,
            }
        ),
        temperature=0.8,
    )
    if not result or not isinstance(result.get("ideas"), list):
        return None
    ideas = []
    for item in result["ideas"][:6]:
        if not isinstance(item, dict):
            continue
        ideas.append(
            {
                "title": str(item.get("title") or "Campaign Idea")[:80],
                "angle": str(item.get("angle") or "")[:240],
                "objective": str(item.get("objective") or "")[:160],
                "channels": str(item.get("channels") or "Multi-channel")[:120],
            }
        )
    return ideas or None


def ai_channel_copy(
    brand: dict[str, Any],
    campaign_title: str,
    brief: str,
    call_to_action: str,
    platforms: list[str],
) -> dict[str, Any] | None:
    result = chat_json(
        system=(
            "You write on-brand multi-channel campaign copy. Return JSON with keys: "
            "social (object keyed by platform with hook, caption, cta), "
            "email (subject_variants array, preview_text, body), "
            "blog (title, intro, outline array), "
            "ads (primary_text, headline, description, cta), "
            "landing (hero_headline, hero_subhead, proof_points array, cta), "
            "voice (string)."
        ),
        user=json.dumps(
            {
                "brand": {
                    "name": brand.get("name"),
                    "tagline": brand.get("tagline"),
                    "description": brand.get("description"),
                    "voice": brand.get("voice"),
                    "keywords": brand.get("keywords"),
                    "palette": brand.get("palette"),
                },
                "campaign_title": campaign_title,
                "brief": brief,
                "call_to_action": call_to_action,
                "platforms": platforms,
            }
        ),
        temperature=0.7,
        max_tokens=2500,
    )
    return result if isinstance(result, dict) else None


def ai_image_prompt(
    brand: dict[str, Any],
    headline: str,
    body: str,
    platform_label: str,
) -> str:
    generated = chat_text(
        system="Write one concise image-generation prompt for an on-brand social ad. No quotes.",
        user=json.dumps(
            {
                "brand": brand.get("name"),
                "palette": brand.get("palette"),
                "voice": brand.get("voice"),
                "headline": headline,
                "body": body,
                "platform": platform_label,
            }
        ),
        temperature=0.7,
        max_tokens=180,
    )
    if generated:
        return generated
    palette = brand.get("palette") or {}
    return (
        f"On-brand marketing creative for {brand.get('name', 'brand')}, "
        f"colors {palette.get('primary')} and {palette.get('accent')}, "
        f"platform {platform_label}, theme: {headline}. Clean modern composition, no watermarks."
    )


def save_data_url_image(data: bytes, destination: Path) -> Path | None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination
    except Exception:
        return None
