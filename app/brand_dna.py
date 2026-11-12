from __future__ import annotations

import colorsys
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


def _download_bytes(url: str, timeout: int = 15) -> bytes | None:
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


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
            content = _download_bytes(absolute, timeout=10)
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


def _extract_copy_signals(soup: BeautifulSoup) -> dict[str, Any]:
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
    tagline = headings[0] if headings else (description[:110] if description else "Built for modern brands")

    brand_name = title.split("|")[0].split("-")[0].strip() if title else urlparse("").netloc
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
    response = requests.get(website_url, timeout=25, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    assert_public_http_url(str(response.url))
    response.raise_for_status()
    final_url = str(response.url)
    soup = BeautifulSoup(response.text, "html.parser")

    css_blob = _extract_css_blob(soup, final_url)
    page_blob = response.text + "\n" + css_blob
    css_colors = _extract_colors_from_text(page_blob)
    fonts = _extract_fonts(css_blob, soup)
    copy = _extract_copy_signals(soup)

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
    if not brand_name or brand_name.lower() in {"home", "welcome"}:
        brand_name = urlparse(final_url).netloc.replace("www.", "").split(".")[0].title()

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
