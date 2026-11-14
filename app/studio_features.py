from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .ai import ai_status, chat_json, chat_text, generate_image_bytes, save_data_url_image
from .content_engine import create_marketing_video, render_marketing_image
from .storage import save_brand, save_content, update_brand


CONTENT_APPS = [
    {"key": "linkedin_post", "label": "LinkedIn Post", "family": "social"},
    {"key": "instagram_caption", "label": "Instagram Caption", "family": "social"},
    {"key": "email_campaign", "label": "Email Campaign", "family": "lifecycle"},
    {"key": "blog_post", "label": "Blog Post", "family": "web"},
    {"key": "landing_page", "label": "Landing Page", "family": "web"},
    {"key": "product_description", "label": "Product Description", "family": "web"},
    {"key": "seo_metadata", "label": "SEO Meta Title & Description", "family": "seo"},
    {"key": "ad_variants", "label": "Ad Variants", "family": "ads"},
    {"key": "press_release", "label": "Press Release", "family": "pr"},
    {"key": "social_calendar", "label": "Social Calendar", "family": "planning"},
]


def brand_agent_turn(brand: dict[str, Any], message: str, knowledge: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Pomelli-style agent that proposes Business DNA updates from a chat prompt."""
    result = chat_json(
        system=(
            "You are the eMarketster Brand Agent (Pomelli-style). "
            "Given a brand profile and user instruction, return JSON with: "
            "reply (string), updates (object of brand fields to change: name, tagline, description, cta, "
            "voice, values, keywords, palette), and changed_fields (array of strings)."
        ),
        user=json.dumps(
            {
                "brand": {
                    "name": brand.get("name"),
                    "tagline": brand.get("tagline"),
                    "description": brand.get("description"),
                    "cta": brand.get("cta"),
                    "voice": brand.get("voice"),
                    "values": brand.get("values"),
                    "keywords": brand.get("keywords"),
                    "palette": brand.get("palette"),
                    "extra_notes": brand.get("extra_notes"),
                },
                "knowledge": [
                    {"title": item.get("title"), "summary": (item.get("body") or "")[:500]}
                    for item in (knowledge or [])[:8]
                ],
                "user_message": message,
            }
        ),
        temperature=0.4,
        max_tokens=1600,
    )

    if not result:
        # Deterministic fallback when OpenRouter is unavailable.
        note = (brand.get("extra_notes") or "").strip()
        brand["extra_notes"] = (note + "\n" + f"Agent note: {message}").strip()
        saved = save_brand(brand)
        return {
            "reply": "Sample mode: saved your instruction into brand notes. Add OpenRouter for live Brand Agent edits.",
            "changed_fields": ["extra_notes"],
            "brand": saved,
            "ai": ai_status(),
        }

    updates = result.get("updates") if isinstance(result.get("updates"), dict) else {}
    allowed = {"name", "tagline", "description", "cta", "voice", "values", "keywords", "palette", "extra_notes"}
    clean_updates = {key: value for key, value in updates.items() if key in allowed}
    if clean_updates:
        brand = update_brand(brand["id"], clean_updates) or brand
    return {
        "reply": str(result.get("reply") or "Updated your Business DNA."),
        "changed_fields": result.get("changed_fields") or list(clean_updates.keys()),
        "brand": brand,
        "ai": ai_status(),
    }


def instant_magic(
    *,
    brand: dict[str, Any],
    app_key: str,
    brief: str,
    audience: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
    language: str = "English",
) -> dict[str, Any]:
    app = next((item for item in CONTENT_APPS if item["key"] == app_key), None)
    if not app:
        raise ValueError("Unknown content app.")

    if app_key == "social_calendar":
        return build_social_calendar(
            brand=brand,
            campaign_title=(product or {}).get("name") or f"{brand.get('name', 'Brand')} Calendar",
            brief=brief or brand.get("description") or "",
            days=7,
        )

    result = chat_json(
        system=(
            "You are Jasper Instant Magic. Generate one on-brand content asset. "
            "Return JSON with title, body, summary, and extras (object)."
        ),
        user=json.dumps(
            {
                "app": app,
                "language": language,
                "brief": brief,
                "brand": {
                    "name": brand.get("name"),
                    "tagline": brand.get("tagline"),
                    "description": brand.get("description"),
                    "voice": brand.get("voice"),
                    "keywords": brand.get("keywords"),
                },
                "audience": audience,
                "product": product,
            }
        ),
        temperature=0.7,
        max_tokens=2200,
    )

    if not result:
        title = f"{app['label']} for {brand.get('name', 'Brand')}"
        body = (
            f"{brief or brand.get('description') or 'Campaign brief'}\n\n"
            f"Voice: {(brand.get('voice') or {}).get('primary_tone', 'professional')}\n"
            f"CTA: {brand.get('cta') or 'Learn more'}\n"
        )
        result = {"title": title, "body": body, "summary": brief[:160], "extras": {"sample": True}}

    payload = {
        "id": f"content-{uuid4().hex[:8]}",
        "brand_id": brand.get("id"),
        "app_key": app_key,
        "app_label": app["label"],
        "family": app["family"],
        "language": language,
        "title": str(result.get("title") or app["label"])[:140],
        "body": str(result.get("body") or ""),
        "summary": str(result.get("summary") or "")[:240],
        "extras": result.get("extras") if isinstance(result.get("extras"), dict) else {},
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "ai": ai_status(),
    }
    return save_content(payload)


def localize_text(text: str, language: str, brand: dict[str, Any]) -> dict[str, Any]:
    translated = chat_text(
        system=(
            "Localize marketing copy with cultural nuance (not literal translation). "
            "Keep brand voice. Return only the localized text."
        ),
        user=json.dumps({"language": language, "brand": brand.get("name"), "text": text}),
        temperature=0.4,
        max_tokens=1800,
    )
    if translated:
        return {"text": translated, "fallback": False}
    return {"text": text, "fallback": True}


def build_social_calendar(
    brand: dict[str, Any],
    campaign_title: str,
    brief: str,
    days: int = 7,
) -> dict[str, Any]:
    days = max(3, min(14, int(days)))
    result = chat_json(
        system=(
            "Create a social content calendar. Return JSON: "
            "{\"days\":[{\"day\", \"date_offset\", \"platform\", \"theme\", \"post\", \"cta\"}]}"
        ),
        user=json.dumps(
            {
                "brand": brand.get("name"),
                "voice": brand.get("voice"),
                "campaign_title": campaign_title,
                "brief": brief,
                "days": days,
            }
        ),
        temperature=0.7,
    )
    start = datetime.now(tz=timezone.utc).date()
    if result and isinstance(result.get("days"), list):
        schedule = []
        for index, item in enumerate(result["days"][:days]):
            schedule.append(
                {
                    "day": item.get("day") or f"Day {index + 1}",
                    "date": (start + timedelta(days=index)).isoformat(),
                    "platform": item.get("platform") or "Instagram",
                    "theme": item.get("theme") or campaign_title,
                    "post": item.get("post") or brief,
                    "cta": item.get("cta") or brand.get("cta") or "Learn more",
                }
            )
    else:
        schedule = [
            {
                "day": f"Day {index + 1}",
                "date": (start + timedelta(days=index)).isoformat(),
                "platform": ["Instagram", "LinkedIn", "TikTok", "X"][index % 4],
                "theme": campaign_title,
                "post": f"{brief} ({brand.get('name')})",
                "cta": brand.get("cta") or "Learn more",
            }
            for index in range(days)
        ]

    payload = {
        "id": f"content-{uuid4().hex[:8]}",
        "brand_id": brand.get("id"),
        "app_key": "social_calendar",
        "app_label": "Social Calendar",
        "family": "planning",
        "language": "English",
        "title": f"{campaign_title} · {days}-day calendar",
        "body": json.dumps(schedule, indent=2),
        "summary": f"{days}-day social calendar for {campaign_title}",
        "extras": {"schedule": schedule},
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "ai": ai_status(),
    }
    return save_content(payload)


def _safe_text(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_color(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", raw):
        return "#0f766e"
    return raw


def generate_brand_book(brand: dict[str, Any], output_root: Path) -> dict[str, Any]:
    voice = brand.get("voice") or {}
    palette = brand.get("palette") or {}
    name = _safe_text(brand.get("name"))
    tagline = _safe_text(brand.get("tagline"))
    description = _safe_text(brand.get("description"))
    cta = _safe_text(brand.get("cta") or "Learn more")
    primary_tone = _safe_text(voice.get("primary_tone"))
    secondary_tone = _safe_text(voice.get("secondary_tone"))
    rules = "".join(f"<li>{_safe_text(rule)}</li>" for rule in (voice.get("style_rules") or [])[:6])
    swatches = "".join(
        f"<span class='swatch' style='background:{_safe_color(color)}' title='{_safe_text(color)}'></span>"
        for color in (palette.get("all") or [])[:6]
    )
    html = f"""<!doctype html>
<html><head><meta charset='utf-8'>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
<title>{name} Brand Book</title>
<style>
body{{font-family:Georgia,serif;margin:40px;color:#10231f;background:#f7faf8}}
h1,h2{{font-family:Helvetica,Arial,sans-serif}}
.swatch{{display:inline-block;width:64px;height:64px;border-radius:12px;margin-right:8px;border:1px solid #ccc}}
.card{{border:1px solid #d7e3dc;border-radius:16px;padding:16px;margin:16px 0;background:#fff}}
</style></head><body>
<h1>{name} Brand Book</h1>
<p><em>{tagline}</em></p>
<div class='card'><h2>Brand Story</h2><p>{description}</p></div>
<div class='card'><h2>Voice</h2>
<p>{primary_tone} · {secondary_tone}</p>
<ul>{rules}</ul>
</div>
<div class='card'><h2>Palette</h2>
{swatches}
</div>
<div class='card'><h2>CTA</h2><p>{cta}</p></div>
</body></html>"""

    book_id = f"brandbook-{uuid4().hex[:8]}"
    out_dir = output_root / book_id
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "brand-book.html"
    html_path.write_text(html, encoding="utf-8")
    md = (
        f"# {brand.get('name') or 'Brand'} Brand Book\n\n"
        f"{brand.get('tagline') or ''}\n\n"
        f"## Story\n{brand.get('description') or ''}\n\n"
        f"## Voice\n{voice}\n\n"
        f"## Palette\n{palette}\n"
    )
    (out_dir / "brand-book.md").write_text(md, encoding="utf-8")
    payload = {
        "id": f"content-{uuid4().hex[:8]}",
        "brand_id": brand.get("id"),
        "app_key": "brand_book",
        "app_label": "Brand Book",
        "family": "brand",
        "language": "English",
        "title": f"{brand.get('name')} Brand Book",
        "body": md,
        "summary": "Brand book with voice, story, and palette",
        "extras": {
            "html_url": f"/generated/{book_id}/brand-book.html",
            "md_url": f"/generated/{book_id}/brand-book.md",
        },
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "ai": ai_status(),
    }
    return save_content(payload)


def generate_photoshoot(
    *,
    brand: dict[str, Any],
    product: dict[str, Any],
    output_root: Path,
    style: str = "clean product studio",
    count: int = 3,
) -> dict[str, Any]:
    count = max(1, min(4, int(count)))
    shoot_id = f"photoshoot-{uuid4().hex[:8]}"
    shoot_dir = output_root / shoot_id / "images"
    shoot_dir.mkdir(parents=True, exist_ok=True)
    images = []
    palette = brand.get("palette") or {}
    for index in range(count):
        prompt = (
            f"Professional product photoshoot for {product.get('name') or brand.get('name')}. "
            f"Style: {style}. Brand colors {palette.get('primary')} and {palette.get('accent')}. "
            f"Description: {product.get('description') or brand.get('description')}. "
            f"Shot variation {index + 1}. No watermark, high detail commerce photo."
        )
        raw = generate_image_bytes(prompt, aspect_ratio="1:1")
        image_name = f"shot-{index + 1}.png"
        image_path = shoot_dir / image_name
        if raw and save_data_url_image(raw, image_path):
            # Optional branded frame overlay for consistency
            framed = shoot_dir / f"shot-{index + 1}-framed.png"
            try:
                render_marketing_image(
                    output_path=framed,
                    size=(1080, 1080),
                    headline=str(product.get("name") or brand.get("name")),
                    body=str(product.get("description") or brand.get("tagline") or "")[:120],
                    cta=str(brand.get("cta") or "Shop now"),
                    brand_name=str(brand.get("name") or "Brand"),
                    source_image=image_path,
                    palette=palette,
                )
                public = f"/generated/{shoot_id}/images/{framed.name}"
            except Exception:
                public = f"/generated/{shoot_id}/images/{image_name}"
            images.append(public)
        else:
            # Template fallback card
            fallback = shoot_dir / image_name
            render_marketing_image(
                output_path=fallback,
                size=(1080, 1080),
                headline=str(product.get("name") or brand.get("name")),
                body=str(product.get("description") or brand.get("tagline") or "Product spotlight")[:120],
                cta=str(brand.get("cta") or "Shop now"),
                brand_name=str(brand.get("name") or "Brand"),
                source_image=None,
                palette=palette,
            )
            images.append(f"/generated/{shoot_id}/images/{image_name}")

    # Optional short clip from first frame
    video_url = ""
    if images:
        first_local = shoot_dir / Path(images[0]).name
        if first_local.exists():
            video_path = output_root / shoot_id / "videos" / "reel.mp4"
            try:
                create_marketing_video(
                    output_path=video_path,
                    size=(1080, 1920),
                    clip_duration=9,
                    source_video=None,
                    source_image=first_local,
                )
                video_url = f"/generated/{shoot_id}/videos/reel.mp4"
            except Exception:
                video_url = ""

    payload = {
        "id": f"content-{uuid4().hex[:8]}",
        "brand_id": brand.get("id"),
        "app_key": "photoshoot",
        "app_label": "Photoshoot",
        "family": "creative",
        "language": "English",
        "title": f"{product.get('name') or brand.get('name')} Photoshoot",
        "body": f"Style: {style}\nShots: {len(images)}",
        "summary": f"{len(images)} photoshoot frames",
        "extras": {"images": images, "video_url": video_url, "style": style},
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "ai": ai_status(),
    }
    return save_content(payload)


def generate_mini_website(brand: dict[str, Any], output_root: Path) -> dict[str, Any]:
    site_id = f"site-{uuid4().hex[:8]}"
    site_dir = output_root / site_id
    site_dir.mkdir(parents=True, exist_ok=True)
    palette = brand.get("palette") or {}
    name = _safe_text(brand.get("name"))
    tagline = _safe_text(brand.get("tagline"))
    description = _safe_text(brand.get("description"))
    cta = _safe_text(brand.get("cta") or "Get started")
    primary = _safe_color(palette.get("primary", "#0f766e"))
    accent = _safe_color(palette.get("accent", "#f59e0b"))
    values = "".join(
        f"<li>{_safe_text(value)}</li>"
        for value in (brand.get("values") or brand.get("keywords") or [])[:5]
    )
    html = f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
<title>{name}</title>
<style>
:root{{--p:{primary};--a:{accent};--ink:#10231f}}
body{{margin:0;font-family:Helvetica,Arial,sans-serif;color:var(--ink);background:linear-gradient(180deg,#f3f7f4,#e7f0ea)}}
.hero{{min-height:80vh;display:grid;place-content:center;padding:2rem;text-align:center}}
h1{{font-size:clamp(2rem,6vw,4rem);margin:0 0 .5rem}}
p{{max-width:40rem;margin:0 auto 1.2rem;line-height:1.5}}
a.cta{{display:inline-block;background:var(--p);color:#fff;text-decoration:none;padding:.9rem 1.2rem;border-radius:12px}}
section{{padding:2.5rem 1.2rem;max-width:900px;margin:0 auto}}
</style></head><body>
<header class='hero'>
  <h1>{name}</h1>
  <p>{tagline}</p>
  <p>{description}</p>
  <a class='cta' href='#'>{cta}</a>
</header>
<section>
  <h2>Why {name}</h2>
  <ul>{values}</ul>
</section>
</body></html>"""
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    payload = {
        "id": f"content-{uuid4().hex[:8]}",
        "brand_id": brand.get("id"),
        "app_key": "website",
        "app_label": "Website",
        "family": "web",
        "language": "English",
        "title": f"{brand.get('name')} mini website",
        "body": "One-page brand website generated from Business DNA.",
        "summary": "Generated website landing page",
        "extras": {"site_url": f"/generated/{site_id}/index.html"},
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "ai": ai_status(),
    }
    return save_content(payload)
