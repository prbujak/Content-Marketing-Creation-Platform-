from __future__ import annotations

import colorsys
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import ipaddress
import socket

import requests
from bs4 import BeautifulSoup
from PIL import Image

from .ai import enrich_brand_voice
from .storage import save_brand, save_catalog_item


def assert_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https website URLs are supported.")
    host = parsed.hostname
    if not host:
        raise ValueError("Website URL is missing a hostname.")
    blocked_hosts = {"localhost", "metadata.google.internal"}
    if host.lower() in blocked_hosts or host.lower().endswith(".local"):
        raise ValueError("Local or internal hosts are not allowed.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError("Private/internal network targets are not allowed.")
    return url


USER_AGENT = "eMarketsterBrandDNA/1.0 (+https://emarketster.local)"
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "our", "are", "was",
    "were", "have", "has", "will", "can", "you", "all", "not", "but", "about", "into",
    "their", "they", "them", "what", "when", "where", "which", "who", "how", "why",
    "more", "than", "also", "just", "over", "under", "into", "onto", "http", "https",
    "www", "com", "home", "page", "site", "click", "here", "learn", "read", "blog",
}

TONE_LEXICON = {
    "professional": {"enterprise", "reliable", "trusted", "secure", "precision", "expert", "solutions"},
    "friendly": {"welcome", "happy", "love", "community", "together", "care", "friendly"},
    "bold": {"power", "bold", "disrupt", "next", "future", "unleash", "transform"},
    "playful": {"fun", "play", "joy", "delight", "spark", "magic", "creative"},
    "luxury": {"premium", "exclusive", "artisan", "crafted", "elegant", "refined", "bespoke"},
    "technical": {"api", "platform", "data", "automation", "system", "infrastructure", "engineer"},
}


def _normalize_hex(value: str) -> str | None:
    raw = value.strip().lower()
    if not HEX_RE.fullmatch(raw):
        return None
    if len(raw) == 4:
        return "#" + "".join(ch * 2 for ch in raw[1:])
    return raw


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _luminance(hex_color: str) -> float:
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _is_near_neutral(hex_color: str) -> bool:
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return s < 0.12 or v < 0.12 or v > 0.95


MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024  # 8 MB cap for secondary assets
MAX_CSS_BYTES = 500_000
MAX_PAGE_BYTES = 2_000_000
MAX_IMAGE_PIXELS = 20_000_000


def _stream_limited(response: requests.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("Remote response exceeded size limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_public_url(
    url: str,
    *,
    timeout: int = 15,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    allow_empty: bool = False,
) -> tuple[str, bytes] | None:
    """Fetch a URL only if the start and final redirect targets are public http(s)."""
    try:
        assert_public_http_url(url)
    except ValueError:
        return None

    try:
        with requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
            stream=True,
        ) as response:
            # Re-validate every hop and the final URL to block redirect-based SSRF.
            for hop in list(response.history) + [response]:
                try:
                    assert_public_http_url(str(hop.url))
                except ValueError:
                    return None
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        return None
                except ValueError:
                    pass
            body = _stream_limited(response, max_bytes=max_bytes)
            if not body and not allow_empty:
                return None
            return str(response.url), body
    except (requests.RequestException, ValueError):
        return None


def _download_bytes(url: str, timeout: int = 15, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes | None:
    result = fetch_public_url(url, timeout=timeout, max_bytes=max_bytes)
    return result[1] if result else None


def _extract_css_blob(soup: BeautifulSoup, base_url: str) -> str:
    chunks: list[str] = []
    for style in soup.find_all("style"):
        if style.string:
            chunks.append(style.string)
    for link in soup.find_all("link", rel=True):
        rel = " ".join(link.get("rel", [])).lower()
        href = link.get("href")
        if "stylesheet" in rel and href:
            absolute = urljoin(base_url, href)
            content = _download_bytes(absolute, timeout=10, max_bytes=MAX_CSS_BYTES)
            if content:
                try:
                    chunks.append(content.decode("utf-8", errors="ignore")[:120000])
                except Exception:
                    continue
    return "\n".join(chunks)


def _extract_colors_from_text(blob: str) -> list[str]:
    found: list[str] = []
    for match in HEX_RE.findall(blob):
        normalized = _normalize_hex(match)
        if normalized:
            found.append(normalized)
    for match in RGB_RE.findall(blob):
        r, g, b = (max(0, min(255, int(part))) for part in match)
        found.append(_rgb_to_hex(r, g, b))
    return found


def _dominant_colors_from_image(path: Path, limit: int = 4) -> list[str]:
    try:
        with Image.open(path) as img:
            sample = img.convert("RGB").resize((96, 96))
            pixels = list(sample.getdata())
    except Exception:
        return []

    quantized = []
    for r, g, b in pixels:
        qr, qg, qb = (r // 24) * 24, (g // 24) * 24, (b // 24) * 24
        hex_color = _rgb_to_hex(qr, qg, qb)
        if not _is_near_neutral(hex_color):
            quantized.append(hex_color)
    counts = Counter(quantized)
    return [color for color, _ in counts.most_common(limit)]


def _rank_palette(candidates: list[str], image_colors: list[str]) -> list[str]:
    counts = Counter(candidates + image_colors * 2)
    ranked = []
    for color, _ in counts.most_common(20):
        if color not in ranked and not _is_near_neutral(color):
            ranked.append(color)
        if len(ranked) >= 5:
            break
    if len(ranked) < 3:
        ranked.extend(["#0f766e", "#134e4a", "#f59e0b"][: 3 - len(ranked)])
    return ranked[:5]


def _extract_fonts(css_blob: str, soup: BeautifulSoup) -> list[str]:
    families: list[str] = []
    for match in FONT_FAMILY_RE.findall(css_blob):
        for part in match.split(","):
            family = part.strip().strip("'\"").strip()
            if family and family.lower() not in {"inherit", "serif", "sans-serif", "monospace", "system-ui"}:
                families.append(family)
    for node in soup.find_all(style=True):
        style = node.get("style", "")
        for match in FONT_FAMILY_RE.findall(style):
            for part in match.split(","):
                family = part.strip().strip("'\"").strip()
                if family:
                    families.append(family)
    ranked = [name for name, _ in Counter(families).most_common(4)]
    return ranked or ["Syne", "Sora"]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _domain_brand_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().replace("www.", "")
    if not host:
        return "Your Brand"
    label = host.split(".")[0]
    label = label.replace("-", " ").replace("_", " ").strip()
    if not label:
        return "Your Brand"
    # Keep short brand tokens like "notion" / "stripe" title-cased.
    if " " in label:
        return " ".join(part.capitalize() for part in label.split())
    return label[:1].upper() + label[1:]


def _looks_like_tagline(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    words = text.split()
    if len(words) >= 5:
        return True
    if len(text) > 40:
        return True
    if text.endswith((".", "!", "?")):
        return True
    lowered = text.lower()
    headline_markers = (
        " the ", " that ", " your ", " for ", " with ", " from ", " into ",
        " workspace ", " platform ", " software ", " help ", " make ", " build ",
    )
    padded = f" {lowered} "
    if any(marker in padded for marker in headline_markers) and len(words) >= 3:
        return True
    return False


def _meta_content(soup: BeautifulSoup, attrs: dict[str, str]) -> str:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return _clean_text(tag["content"])
    return ""


def _json_ld_brand_name(soup: BeautifulSoup) -> str:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            type_names = types if isinstance(types, list) else [types]
            type_names = [str(name).lower() for name in type_names if name]
            if any(name in {"organization", "brand", "website", "corporation"} for name in type_names):
                candidate = _clean_text(str(item.get("name") or item.get("legalName") or ""))
                if candidate and not _looks_like_tagline(candidate):
                    return candidate
            # Nested publisher / brand blocks
            for key in ("publisher", "brand", "organizer"):
                nested = item.get(key)
                if isinstance(nested, dict):
                    candidate = _clean_text(str(nested.get("name") or ""))
                    if candidate and not _looks_like_tagline(candidate):
                        return candidate
    return ""


def _logo_alt_brand_name(soup: BeautifulSoup) -> str:
    for img in soup.find_all("img"):
        alt = _clean_text(img.get("alt") or "")
        classes = " ".join(img.get("class", [])).lower()
        src = (img.get("src") or "").lower()
        if not alt:
            continue
        if "logo" in alt.lower() or "logo" in classes or "logo" in src:
            cleaned = re.sub(r"\blogo\b", "", alt, flags=re.IGNORECASE).strip(" -|:·")
            cleaned = _clean_text(cleaned)
            if cleaned and not _looks_like_tagline(cleaned):
                return cleaned
    return ""


def _title_brand_candidate(title: str) -> str:
    if not title:
        return ""
    # Prefer left segment for "Brand | Tagline" / "Brand - Tagline" / "Brand: Tagline"
    parts = re.split(r"\s*[|–—:\-]\s*", title)
    parts = [part.strip() for part in parts if part.strip()]
    if not parts:
        return ""
    first = parts[0]
    if not _looks_like_tagline(first):
        return first
    # Sometimes title is "Tagline | Brand"
    last = parts[-1]
    if last != first and not _looks_like_tagline(last):
        return last
    return ""


def _resolve_brand_name(soup: BeautifulSoup, page_url: str, title: str) -> str:
    candidates = [
        _meta_content(soup, {"property": "og:site_name"}),
        _meta_content(soup, {"name": "application-name"}),
        _meta_content(soup, {"name": "apple-mobile-web-app-title"}),
        _meta_content(soup, {"name": "twitter:app:name:iphone"}),
        _json_ld_brand_name(soup),
        _logo_alt_brand_name(soup),
        _title_brand_candidate(title),
        _domain_brand_name(page_url),
    ]
    for candidate in candidates:
        cleaned = _clean_text(candidate)
        if not cleaned:
            continue
        if cleaned.lower() in {"home", "welcome", "website", "official site"}:
            continue
        if _looks_like_tagline(cleaned):
            continue
        return cleaned
    return _domain_brand_name(page_url)


def _extract_copy_signals(soup: BeautifulSoup, page_url: str = "") -> dict[str, Any]:
    title = _clean_text(soup.title.string if soup.title and soup.title.string else "")
    description = ""
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = _clean_text(tag["content"])
            break

    headings = [_clean_text(node.get_text(" ", strip=True)) for node in soup.find_all(["h1", "h2", "h3"])]
    headings = [item for item in headings if item][:12]
    paragraphs = [_clean_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
    paragraphs = [item for item in paragraphs if len(item) > 40][:12]
    cta_candidates = []
    for node in soup.find_all(["a", "button"]):
        text = _clean_text(node.get_text(" ", strip=True))
        if 2 <= len(text.split()) <= 5 and text:
            cta_candidates.append(text)
    cta = Counter(cta_candidates).most_common(1)[0][0] if cta_candidates else "Learn more"

    corpus = " ".join([title, description] + headings + paragraphs).lower()
    words = [word for word in WORD_RE.findall(corpus) if word.lower() not in STOPWORDS]
    keywords = [word for word, _ in Counter(word.lower() for word in words).most_common(12)]

    tone_scores = {}
    for tone, lexicon in TONE_LEXICON.items():
        tone_scores[tone] = sum(1 for word in keywords if word in lexicon) + sum(
            corpus.count(token) for token in lexicon
        )
    primary_tone = max(tone_scores, key=tone_scores.get) if any(tone_scores.values()) else "professional"
    secondary = sorted(
        ((name, score) for name, score in tone_scores.items() if name != primary_tone),
        key=lambda item: item[1],
        reverse=True,
    )
    secondary_tone = secondary[0][0] if secondary and secondary[0][1] > 0 else "friendly"

    values = headings[:4] or keywords[:4]
    brand_name = _resolve_brand_name(soup, page_url, title)

    def _clean_tagline(value: str) -> str:
        text = _clean_text(value)
        if not text:
            return ""
        # Drop trailing/leading brand segments like "Headline | Notion".
        parts = [part.strip() for part in re.split(r"\s*[|–—]\s*", text) if part.strip()]
        filtered = [part for part in parts if part.lower() != brand_name.lower()]
        text = filtered[0] if filtered else text
        if text.lower() == brand_name.lower():
            return ""
        return text[:120]

    # Prefer a marketing headline for tagline, not the brand name itself.
    tagline_candidates = []
    og_title = _clean_tagline(_meta_content(soup, {"property": "og:title"}))
    if og_title:
        tagline_candidates.append(og_title)
    for heading in headings:
        cleaned = _clean_tagline(heading)
        if cleaned:
            tagline_candidates.append(cleaned)
    if description:
        tagline_candidates.append(_clean_tagline(description[:110]) or description[:110])
    tagline = next((item for item in tagline_candidates if item), f"{brand_name} campaigns that convert")

    return {
        "title": title,
        "brand_name": brand_name or "Your Brand",
        "tagline": tagline,
        "description": description or (paragraphs[0] if paragraphs else "A brand ready for multi-channel campaigns."),
        "headings": headings,
        "paragraphs": paragraphs,
        "keywords": keywords,
        "cta": cta,
        "tone_primary": primary_tone,
        "tone_secondary": secondary_tone,
        "values": values,
        "tone_scores": tone_scores,
    }


def _extract_image_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    for attrs in (
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"property": "og:image:url"},
        {"itemprop": "image"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            urls.append(urljoin(base_url, tag["content"].strip()))

    logo_candidates = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        absolute = urljoin(base_url, src)
        alt = (img.get("alt") or "").lower()
        classes = " ".join(img.get("class", [])).lower()
        score = 0
        if "logo" in alt or "logo" in classes or "logo" in absolute.lower():
            score += 5
        if any(token in absolute.lower() for token in (".svg", ".png", ".webp", ".jpg", ".jpeg")):
            score += 1
        if score:
            logo_candidates.append((score, absolute))
        urls.append(absolute)

    logo_candidates.sort(key=lambda item: item[0], reverse=True)
    ordered = []
    if logo_candidates:
        ordered.append(logo_candidates[0][1])
    for url in urls:
        if url not in ordered:
            ordered.append(url)
    return ordered[:10]


def _save_image(content: bytes, destination: Path) -> Path | None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    try:
        with Image.open(destination) as img:
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Image too large")
            img.verify()
        return destination
    except Exception:
        if destination.exists():
            destination.unlink(missing_ok=True)
        return None


def build_brand_dna(
    website_url: str,
    asset_root: Path,
    brand_name_override: str = "",
    extra_notes: str = "",
) -> dict[str, Any]:
    brand_id = f"brand-{uuid4().hex[:8]}"
    brand_dir = asset_root / brand_id
    image_dir = brand_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    website_url = assert_public_http_url(website_url)
    fetched = fetch_public_url(website_url, timeout=25, max_bytes=MAX_PAGE_BYTES)
    if not fetched:
        raise ValueError("Could not safely fetch the website URL.")
    final_url, page_bytes = fetched
    page_text = page_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(page_text, "html.parser")

    css_blob = _extract_css_blob(soup, final_url)
    page_blob = page_text + "\n" + css_blob
    css_colors = _extract_colors_from_text(page_blob)
    fonts = _extract_fonts(css_blob, soup)
    copy = _extract_copy_signals(soup, final_url)

    image_urls = _extract_image_urls(soup, final_url)
    saved_images: list[dict[str, str]] = []
    image_colors: list[str] = []
    for index, image_url in enumerate(image_urls[:6]):
        content = _download_bytes(image_url)
        if not content:
            continue
        suffix = Path(urlparse(image_url).path).suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
            suffix = ".jpg"
        saved = _save_image(content, image_dir / f"source-{index}{suffix}")
        if not saved:
            continue
        saved_images.append(
            {
                "url": image_url,
                "path": str(saved),
                "public_url": f"/generated/{brand_id}/images/{saved.name}",
            }
        )
        image_colors.extend(_dominant_colors_from_image(saved, limit=3))

    palette = _rank_palette(css_colors, image_colors)
    brand_name = brand_name_override.strip() or copy["brand_name"]
    if not brand_name or brand_name.lower() in {"home", "welcome"} or _looks_like_tagline(brand_name):
        brand_name = _domain_brand_name(final_url)

    voice = {
        "primary_tone": copy["tone_primary"],
        "secondary_tone": copy["tone_secondary"],
        "style_rules": [
            f"Lead with {copy['tone_primary']} language grounded in the brand promise.",
            f"Blend in {copy['tone_secondary']} warmth without diluting clarity.",
            "Prefer concrete benefits over jargon.",
            "Keep CTAs action-oriented and specific.",
        ],
        "do": [
            f"Sound {copy['tone_primary']}",
            "Highlight customer outcomes",
            "Stay visually consistent with brand colors",
        ],
        "dont": [
            "Sound generic or interchangeable",
            "Overpromise without proof points",
            "Use off-palette accent colors",
        ],
        "sample_phrases": copy["headings"][:3] or copy["keywords"][:3],
    }

    brand = {
        "id": brand_id,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_url": final_url,
        "name": brand_name,
        "tagline": copy["tagline"],
        "description": copy["description"],
        "cta": copy["cta"],
        "keywords": copy["keywords"],
        "values": copy["values"],
        "palette": {
            "primary": palette[0],
            "secondary": palette[1] if len(palette) > 1 else palette[0],
            "accent": palette[2] if len(palette) > 2 else "#f59e0b",
            "all": palette,
        },
        "fonts": {
            "display": fonts[0],
            "body": fonts[1] if len(fonts) > 1 else fonts[0],
            "all": fonts,
        },
        "voice": voice,
        "images": saved_images,
        "logo_url": saved_images[0]["public_url"] if saved_images else "",
        "extra_notes": extra_notes.strip(),
        "assets_dir": str(brand_dir),
    }

    # Seed catalog with a default product/service entry from homepage copy.
    save_catalog_item(
        {
            "brand_id": brand_id,
            "name": brand_name,
            "description": copy["description"],
            "source_url": final_url,
            "image_url": saved_images[0]["public_url"] if saved_images else "",
            "image_path": saved_images[0]["path"] if saved_images else "",
        }
    )

    brand = enrich_brand_voice(brand)
    return save_brand(brand)


def brand_summary(brand: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": brand.get("id"),
        "name": brand.get("name"),
        "tagline": brand.get("tagline"),
        "description": brand.get("description"),
        "source_url": brand.get("source_url"),
        "palette": brand.get("palette"),
        "fonts": brand.get("fonts"),
        "voice": brand.get("voice"),
        "logo_url": brand.get("logo_url"),
        "images": brand.get("images", [])[:6],
        "cta": brand.get("cta"),
        "keywords": brand.get("keywords", []),
        "values": brand.get("values", []),
    }
