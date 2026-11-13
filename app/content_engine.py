from __future__ import annotations

import json
import re
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .ai import ai_campaign_ideas, ai_channel_copy, ai_image_prompt, ai_status, generate_image_bytes, save_data_url_image
from .storage import save_campaign


PLATFORM_PRESETS: dict[str, dict[str, Any]] = {
    "instagram": {
        "label": "Instagram",
        "tone": "visual-first and conversion-ready",
        "hashtags": ["#BrandCampaign", "#InstagramMarketing", "#OnBrand"],
        "image_size": (1080, 1080),
        "video_size": (1080, 1920),
    },
    "facebook": {
        "label": "Facebook",
        "tone": "story-led and community-building",
        "hashtags": ["#FacebookAds", "#SocialGrowth", "#BrandStory"],
        "image_size": (1200, 630),
        "video_size": (1080, 1080),
    },
    "tiktok": {
        "label": "TikTok",
        "tone": "punchy, trend-aware, and hook-driven",
        "hashtags": ["#TikTokMarketing", "#ShortForm", "#CreateDaily"],
        "image_size": (1080, 1920),
        "video_size": (1080, 1920),
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "tone": "educational and curiosity-led",
        "hashtags": ["#YouTubeShorts", "#MarketingTips", "#BrandFilm"],
        "image_size": (1280, 720),
        "video_size": (1080, 1920),
    },
    "linkedin": {
        "label": "LinkedIn",
        "tone": "insightful and trust-building",
        "hashtags": ["#B2BMarketing", "#ThoughtLeadership", "#BrandVoice"],
        "image_size": (1200, 627),
        "video_size": (1080, 1080),
    },
    "x": {
        "label": "X",
        "tone": "concise and timely",
        "hashtags": ["#Marketing", "#Campaigns", "#BuildInPublic"],
        "image_size": (1600, 900),
        "video_size": (1280, 720),
    },
    "pinterest": {
        "label": "Pinterest",
        "tone": "inspirational and discovery-oriented",
        "hashtags": ["#PinterestMarketing", "#Inspiration", "#BrandDesign"],
        "image_size": (1000, 1500),
        "video_size": (1080, 1920),
    },
}

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
RESAMPLE_METHOD = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


def slugify(value: str, fallback: str = "campaign") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").lower()).strip("-")
    return cleaned or fallback


def parse_links(raw_links: list[str]) -> list[str]:
    links: list[str] = []
    for chunk in raw_links:
        for part in re.split(r"[\n,]+", chunk or ""):
            candidate = part.strip()
            if candidate:
                links.append(candidate)
    return links


def split_media(files: list[Path]) -> tuple[list[Path], list[Path]]:
    images = [path for path in files if path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES]
    videos = [path for path in files if path.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES]
    return images, videos


def _hex_to_rgb(value: str, fallback: tuple[int, int, int] = (15, 118, 110)) -> tuple[int, int, int]:
    try:
        raw = value.lstrip("#")
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except Exception:
        return fallback


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _line_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        tentative = f"{current} {word}"
        if _line_width(draw, tentative, font) <= max_width:
            current = tentative
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines and current:
        lines.append(current)
    return lines[:max_lines]


def _gradient_background(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = (
            int(top[0] + (bottom[0] - top[0]) * ratio),
            int(top[1] + (bottom[1] - top[1]) * ratio),
            int(top[2] + (bottom[2] - top[2]) * ratio),
        )
        draw.line((0, y, width, y), fill=color)
    return image


def _open_image_limited(path: Path) -> Image.Image:
    with Image.open(path) as img:
        width, height = img.size
        if width * height > MAX_SOURCE_IMAGE_PIXELS:
            raise ValueError("Source image is too large.")
        return img.convert("RGB")


def _base_canvas(size: tuple[int, int], source_image: Path | None, palette: dict[str, Any]) -> Image.Image:
    if source_image and source_image.exists():
        try:
            img = _open_image_limited(source_image)
            return ImageOps.fit(img, size, method=RESAMPLE_METHOD)
        except Exception:
            pass
    top = _hex_to_rgb(palette.get("primary", "#0f766e"))
    bottom = _hex_to_rgb(palette.get("secondary", "#134e4a"))
    return _gradient_background(size, top, bottom)


def render_marketing_image(
    output_path: Path,
    size: tuple[int, int],
    headline: str,
    body: str,
    cta: str,
    brand_name: str,
    source_image: Path | None,
    palette: dict[str, Any],
) -> None:
    canvas = _base_canvas(size, source_image, palette).convert("RGBA")
    width, height = size
    overlay = Image.new("RGBA", size, (8, 12, 18, 72))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    primary = _hex_to_rgb(palette.get("primary", "#0f766e")) + (220,)
    accent = _hex_to_rgb(palette.get("accent", "#f59e0b")) + (255,)

    panel_height = int(height * 0.46)
    panel_top = height - panel_height - int(height * 0.04)
    panel_left = int(width * 0.06)
    panel_right = int(width * 0.94)
    panel_bottom = height - int(height * 0.04)
    draw.rounded_rectangle(
        [(panel_left, panel_top), (panel_right, panel_bottom)],
        radius=max(16, int(min(width, height) * 0.02)),
        fill=(10, 16, 28, 198),
    )

    brand_font = _font(max(18, int(height * 0.028)), bold=True)
    headline_font = _font(max(26, int(height * 0.062)), bold=True)
    body_font = _font(max(16, int(height * 0.032)))
    cta_font = _font(max(16, int(height * 0.03)), bold=True)

    content_x = panel_left + int(width * 0.04)
    content_width = (panel_right - panel_left) - int(width * 0.08)
    cursor_y = panel_top + int(height * 0.035)

    draw.text((content_x, cursor_y), brand_name[:42], font=brand_font, fill=accent)
    cursor_y += int(brand_font.size * 1.5)

    for line in _wrap_text(draw, headline, headline_font, content_width, 3):
        draw.text((content_x, cursor_y), line, font=headline_font, fill=(248, 250, 252, 255))
        cursor_y += int(headline_font.size * 1.18)

    cursor_y += int(height * 0.012)
    for line in _wrap_text(draw, body, body_font, content_width, 4):
        draw.text((content_x, cursor_y), line, font=body_font, fill=(226, 232, 240, 255))
        cursor_y += int(body_font.size * 1.32)

    button_text = cta[:48]
    button_width = _line_width(draw, button_text, cta_font) + int(width * 0.05)
    button_height = int(cta_font.size * 2.05)
    button_x = content_x
    button_y = panel_bottom - button_height - int(height * 0.028)
    draw.rounded_rectangle(
        [(button_x, button_y), (button_x + button_width, button_y + button_height)],
        radius=max(10, int(button_height * 0.28)),
        fill=primary,
    )
    draw.text(
        (button_x + int(width * 0.018), button_y + int(button_height * 0.24)),
        button_text,
        font=cta_font,
        fill=(255, 255, 255, 255),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, format="PNG", optimize=True)


FFMPEG_TIMEOUT_SECONDS = 60
FFPROBE_TIMEOUT_SECONDS = 15
MAX_SOURCE_IMAGE_PIXELS = 20_000_000


def _run_command(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Media processing timed out.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "Unknown ffmpeg error"
        raise RuntimeError(stderr) from exc


def _probe_duration(video_path: Path) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(video_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def create_marketing_video(
    output_path: Path,
    size: tuple[int, int],
    clip_duration: int,
    source_video: Path | None,
    source_image: Path,
) -> None:
    width, height = size
    base_filter = (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p,"
        f"zoompan=z='min(zoom+0.0015,1.12)':d={clip_duration * 30}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if source_video and source_video.exists():
        source_duration = _probe_duration(source_video)
        simple_filter = (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        )
        if source_duration and source_duration < clip_duration:
            command = [
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(source_video),
                "-t", str(clip_duration), "-vf", simple_filter, "-r", "30", "-an", str(output_path),
            ]
        else:
            start_time = max(((source_duration or clip_duration) - clip_duration) / 2.0, 0.0)
            command = [
                "ffmpeg", "-y", "-ss", f"{start_time:.2f}", "-i", str(source_video),
                "-t", str(clip_duration), "-vf", simple_filter, "-r", "30", "-an", str(output_path),
            ]
        _run_command(command)
        return

    if not source_image.exists():
        raise RuntimeError("Could not build video because no source image was available.")

    command = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(source_image),
        "-t", str(clip_duration), "-vf", base_filter, "-r", "30", "-an", str(output_path),
    ]
    try:
        _run_command(command)
    except RuntimeError:
        # Fallback without zoompan if filter chain fails on some ffmpeg builds.
        fallback = (
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        )
        command = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(source_image),
            "-t", str(clip_duration), "-vf", fallback, "-r", "30", "-an", str(output_path),
        ]
        _run_command(command)


def generate_campaign_ideas(brand: dict[str, Any], product_name: str = "", custom_prompt: str = "") -> list[dict[str, str]]:
    ai_ideas = ai_campaign_ideas(brand, product_name=product_name, custom_prompt=custom_prompt)
    if ai_ideas:
        return ai_ideas

    name = brand.get("name", "Brand")
    tagline = brand.get("tagline", "")
    keywords = brand.get("keywords") or []
    tone = brand.get("voice", {}).get("primary_tone", "professional")
    product = product_name or name
    focus = custom_prompt.strip()

    seeds = [
        {
            "title": f"{product} Launch Pulse",
            "angle": f"Introduce {product} with a benefit-led story that feels {tone}.",
            "objective": "Drive awareness and first conversions",
            "channels": "Instagram, LinkedIn, Email",
        },
        {
            "title": "Proof Over Promises",
            "angle": f"Turn {name}'s strengths ({', '.join(keywords[:3]) or tagline}) into social proof creatives.",
            "objective": "Build trust and consideration",
            "channels": "LinkedIn, Facebook, Landing page",
        },
        {
            "title": "Offer Sprint",
            "angle": f"Create a short-window offer campaign with crisp CTAs around {product}.",
            "objective": "Increase clicks and demo requests",
            "channels": "Ads, TikTok, X",
        },
        {
            "title": "Behind the Brand",
            "angle": f"Show the people/process behind {name} while staying on-voice ({tone}).",
            "objective": "Deepen brand affinity",
            "channels": "Instagram, YouTube Shorts, Blog",
        },
        {
            "title": "Problem → Outcome",
            "angle": f"Contrast the before/after journey using {name}'s core promise.",
            "objective": "Improve message clarity and conversion",
            "channels": "LinkedIn, Email, Landing page",
        },
        {
            "title": "Seasonal Spotlight",
            "angle": f"Adapt {product} messaging to a timely seasonal moment without losing brand DNA.",
            "objective": "Capture timely demand",
            "channels": "Pinterest, Instagram, Ads",
        },
    ]

    if focus:
        seeds.insert(
            0,
            {
                "title": "Custom Brief Campaign",
                "angle": focus,
                "objective": "Execute the exact campaign vision from your brief",
                "channels": "Multi-channel pack",
            },
        )
    return seeds[:6]


def _voice_line(brand: dict[str, Any]) -> str:
    voice = brand.get("voice", {})
    return (
        f"Brand voice: {voice.get('primary_tone', 'professional')} with "
        f"{voice.get('secondary_tone', 'friendly')} undertones."
    )


def build_channel_copy(
    brand: dict[str, Any],
    campaign_title: str,
    brief: str,
    call_to_action: str,
    platforms: list[str],
) -> dict[str, Any]:
    ai_copy = ai_channel_copy(
        brand=brand,
        campaign_title=campaign_title,
        brief=brief,
        call_to_action=call_to_action,
        platforms=platforms,
    )
    if ai_copy and isinstance(ai_copy.get("social"), dict):
        # Normalize expected keys with safe defaults.
        social = {}
        for platform in platforms:
            item = ai_copy["social"].get(platform) or {}
            social[platform] = {
                "label": PLATFORM_PRESETS.get(platform, {}).get("label", platform),
                "hook": str(item.get("hook") or campaign_title)[:120],
                "caption": str(item.get("caption") or brief)[:600],
                "cta": str(item.get("cta") or call_to_action),
                "tone_note": str(item.get("tone_note") or _voice_line(brand)),
            }
        email = ai_copy.get("email") or {}
        blog = ai_copy.get("blog") or {}
        ads = ai_copy.get("ads") or {}
        landing = ai_copy.get("landing") or {}
        return {
            "social": social,
            "email": {
                "subject_variants": email.get("subject_variants") or [campaign_title],
                "preview_text": email.get("preview_text") or brief[:90],
                "body": email.get("body") or brief,
            },
            "blog": {
                "title": blog.get("title") or campaign_title,
                "outline": blog.get("outline") or [brief],
                "intro": blog.get("intro") or brief,
            },
            "ads": {
                "primary_text": ads.get("primary_text") or brief[:140],
                "headline": ads.get("headline") or campaign_title[:40],
                "description": ads.get("description") or brand.get("tagline", "")[:70],
                "cta": ads.get("cta") or call_to_action,
            },
            "landing": {
                "hero_headline": landing.get("hero_headline") or campaign_title,
                "hero_subhead": landing.get("hero_subhead") or brief,
                "proof_points": landing.get("proof_points") or (brand.get("values") or [])[:3],
                "cta": landing.get("cta") or call_to_action,
            },
            "voice": ai_copy.get("voice") or _voice_line(brand),
            "ai_generated": True,
        }

    name = brand.get("name", "Brand")
    description = brand.get("description", "")
    tagline = brand.get("tagline", "")
    keywords = ", ".join((brand.get("keywords") or [])[:5])
    cta = call_to_action or brand.get("cta") or "Learn more"
    voice = _voice_line(brand)
    angle = brief or tagline or description

    social = {}
    for platform in platforms:
        preset = PLATFORM_PRESETS.get(platform)
        if not preset:
            continue
        hook = textwrap.shorten(f"{campaign_title}: {angle}", width=90, placeholder="...")
        caption = (
            f"{hook}\n\n"
            f"{textwrap.shorten(description or angle, width=160, placeholder='...')}\n\n"
            f"{cta}\n"
            f"{' '.join(preset['hashtags'])}"
        )
        social[platform] = {
            "label": preset["label"],
            "hook": hook,
            "caption": caption,
            "cta": cta,
            "tone_note": f"Write in a {preset['tone']} style. {voice}",
        }

    email = {
        "subject_variants": [
            f"{campaign_title}: a smarter way to grow with {name}",
            f"Inside {name}'s new campaign: {textwrap.shorten(angle, width=48, placeholder='...')}",
            f"{cta} — {textwrap.shorten(tagline or angle, width=42, placeholder='...')}",
        ],
        "preview_text": textwrap.shorten(description or angle, width=90, placeholder="..."),
        "body": (
            f"Hi there,\n\n"
            f"{name} just launched {campaign_title}.\n\n"
            f"{angle}\n\n"
            f"Why it matters:\n"
            f"- Stays true to our brand DNA\n"
            f"- Focuses on outcomes your audience cares about\n"
            f"- Built for quick activation across channels\n\n"
            f"{cta}.\n\n"
            f"Keywords in play: {keywords or 'brand, growth, campaign'}\n"
        ),
    }

    blog = {
        "title": f"How {name} turns brand DNA into campaigns that convert",
        "outline": [
            f"Opening hook around {campaign_title}",
            "The customer problem in plain language",
            f"How {name} solves it (with proof points)",
            "Campaign creative examples and messaging pillars",
            f"Clear CTA: {cta}",
        ],
        "intro": textwrap.shorten(
            f"{angle} This campaign shows how {name} keeps every channel on-brand while moving people to act.",
            width=220,
            placeholder="...",
        ),
    }

    ads = {
        "primary_text": textwrap.shorten(f"{angle} {description}", width=140, placeholder="..."),
        "headline": textwrap.shorten(f"{campaign_title} by {name}", width=40, placeholder="..."),
        "description": textwrap.shorten(tagline or description or angle, width=70, placeholder="..."),
        "cta": cta,
    }

    landing = {
        "hero_headline": textwrap.shorten(campaign_title or tagline or name, width=60, placeholder="..."),
        "hero_subhead": textwrap.shorten(angle or description, width=120, placeholder="..."),
        "proof_points": (brand.get("values") or keywords.split(", ") or [name])[:3],
        "cta": cta,
    }

    return {
        "social": social,
        "email": email,
        "blog": blog,
        "ads": ads,
        "landing": landing,
        "voice": voice,
    }


def build_branded_campaign(
    brand: dict[str, Any],
    campaign_title: str,
    brief: str,
    call_to_action: str,
    platforms: list[str],
    uploaded_files: list[Path],
    generated_root: Path,
    clip_duration: int,
    idea: dict[str, str] | None = None,
) -> dict[str, Any]:
    campaign_id = f"{slugify(campaign_title or brand.get('name', 'campaign'))[:100]}-{uuid4().hex[:8]}"
    campaign_dir = generated_root / campaign_id
    copy_dir = campaign_dir / "copy"
    image_dir = campaign_dir / "images"
    video_dir = campaign_dir / "videos"
    for directory in (copy_dir, image_dir, video_dir):
        directory.mkdir(parents=True, exist_ok=True)

    selected_platforms = [key for key in platforms if key in PLATFORM_PRESETS] or list(PLATFORM_PRESETS.keys())
    duration = max(8, min(12, int(clip_duration)))
    palette = brand.get("palette") or {"primary": "#0f766e", "secondary": "#134e4a", "accent": "#f59e0b"}
    cta = call_to_action or brand.get("cta") or "Learn more"
    title = campaign_title or f"{brand.get('name', 'Brand')} Campaign"
    angle = brief or (idea or {}).get("angle") or brand.get("tagline") or brand.get("description", "")

    channel_copy = build_channel_copy(
        brand=brand,
        campaign_title=title,
        brief=angle,
        call_to_action=cta,
        platforms=selected_platforms,
    )
    (copy_dir / "channels.json").write_text(json.dumps(channel_copy, indent=2), encoding="utf-8")
    (copy_dir / "email.txt").write_text(
        "SUBJECT VARIANTS\n"
        + "\n".join(f"- {item}" for item in channel_copy["email"]["subject_variants"])
        + "\n\nPREVIEW\n"
        + channel_copy["email"]["preview_text"]
        + "\n\nBODY\n"
        + channel_copy["email"]["body"],
        encoding="utf-8",
    )
    (copy_dir / "blog.txt").write_text(
        channel_copy["blog"]["title"]
        + "\n\n"
        + channel_copy["blog"]["intro"]
        + "\n\nOutline:\n"
        + "\n".join(f"- {item}" for item in channel_copy["blog"]["outline"]),
        encoding="utf-8",
    )
    (copy_dir / "ads.txt").write_text(
        f"Primary: {channel_copy['ads']['primary_text']}\n"
        f"Headline: {channel_copy['ads']['headline']}\n"
        f"Description: {channel_copy['ads']['description']}\n"
        f"CTA: {channel_copy['ads']['cta']}\n",
        encoding="utf-8",
    )
    (copy_dir / "landing.txt").write_text(
        f"Hero: {channel_copy['landing']['hero_headline']}\n"
        f"Subhead: {channel_copy['landing']['hero_subhead']}\n"
        f"CTA: {channel_copy['landing']['cta']}\n"
        + "Proof points:\n"
        + "\n".join(f"- {item}" for item in channel_copy["landing"]["proof_points"]),
        encoding="utf-8",
    )

    uploaded_images, uploaded_videos = split_media(uploaded_files)
    brand_images = []
    for item in brand.get("images") or []:
        path_value = item.get("path")
        if path_value and Path(path_value).exists():
            brand_images.append(Path(path_value))
    default_image = uploaded_images[0] if uploaded_images else (brand_images[0] if brand_images else None)
    default_video = uploaded_videos[0] if uploaded_videos else None

    creative_results = []
    for platform in selected_platforms:
        preset = PLATFORM_PRESETS[platform]
        social = channel_copy["social"].get(platform, {})
        copy_text = social.get("caption") or f"{title}\n{angle}\n{cta}"
        (copy_dir / f"{platform}.txt").write_text(copy_text, encoding="utf-8")

        headline = textwrap.shorten(social.get("hook") or title, width=72, placeholder="...")
        body = textwrap.shorten(angle or brand.get("description", ""), width=140, placeholder="...")
        image_url = ""
        video_url = ""
        errors: list[str] = []
        image_path = image_dir / f"{platform}.png"
        video_path = video_dir / f"{platform}.mp4"
        image_for_video: Path | None = None

        # Prefer OpenRouter AI image, then fall back to template overlay.
        ai_source = None
        try:
            ratio = "1:1"
            w, h = preset["image_size"]
            if h > w * 1.2:
                ratio = "9:16"
            elif w > h * 1.2:
                ratio = "16:9"
            prompt = ai_image_prompt(brand, headline, body, preset["label"])
            raw = generate_image_bytes(prompt, aspect_ratio=ratio)
            if raw:
                ai_path = image_dir / f"{platform}-ai.png"
                if save_data_url_image(raw, ai_path):
                    ai_source = ai_path
        except Exception as exc:  # pylint: disable=broad-exception-caught
            errors.append(f"AI image skipped: {exc}")

        try:
            render_marketing_image(
                output_path=image_path,
                size=tuple(preset["image_size"]),
                headline=headline,
                body=body,
                cta=cta,
                brand_name=brand.get("name", "Brand"),
                source_image=ai_source or default_image,
                palette=palette,
            )
            image_url = f"/generated/{campaign_id}/images/{platform}.png"
            image_for_video = image_path
        except Exception as exc:  # pylint: disable=broad-exception-caught
            errors.append(f"Image generation failed: {exc}")

        try:
            if image_for_video is None:
                temp_image = campaign_dir / "temp" / f"{platform}.png"
                render_marketing_image(
                    output_path=temp_image,
                    size=tuple(preset["video_size"]),
                    headline=headline,
                    body=body,
                    cta=cta,
                    brand_name=brand.get("name", "Brand"),
                    source_image=default_image,
                    palette=palette,
                )
                image_for_video = temp_image
            create_marketing_video(
                output_path=video_path,
                size=tuple(preset["video_size"]),
                clip_duration=duration,
                source_video=default_video,
                source_image=image_for_video,
            )
            video_url = f"/generated/{campaign_id}/videos/{platform}.mp4"
        except Exception as exc:  # pylint: disable=broad-exception-caught
            errors.append(f"Video generation failed: {exc}")

        creative_results.append(
            {
                "platform_key": platform,
                "platform_label": preset["label"],
                "copy": copy_text,
                "copy_url": f"/generated/{campaign_id}/copy/{platform}.txt",
                "image_url": image_url,
                "video_url": video_url,
                "errors": errors,
            }
        )

    payload = {
        "id": campaign_id,
        "campaign_id": campaign_id,
        "brand_id": brand.get("id"),
        "brand_name": brand.get("name"),
        "title": title,
        "brief": angle,
        "idea": idea or {},
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "clip_duration_seconds": duration,
        "platform_count": len(creative_results),
        "channels": {
            "email_url": f"/generated/{campaign_id}/copy/email.txt",
            "blog_url": f"/generated/{campaign_id}/copy/blog.txt",
            "ads_url": f"/generated/{campaign_id}/copy/ads.txt",
            "landing_url": f"/generated/{campaign_id}/copy/landing.txt",
            "channels_json_url": f"/generated/{campaign_id}/copy/channels.json",
            "content": channel_copy,
        },
        "results": creative_results,
        "palette": palette,
        "voice": brand.get("voice", {}),
        "ai": ai_status(),
    }
    (campaign_dir / "metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return save_campaign(payload)


# Backwards-compatible wrapper used by older smoke tests / routes.
def build_campaign(
    project_name: str,
    brand_name: str,
    product_description: str,
    call_to_action: str,
    platforms: list[str],
    website_urls: list[str],
    uploaded_files: list[Path],
    generated_root: Path,
    clip_duration: int,
) -> dict[str, Any]:
    brand = {
        "id": f"ad-hoc-{uuid4().hex[:6]}",
        "name": brand_name or project_name or "Brand",
        "tagline": product_description.split(".")[0][:120] if product_description else project_name,
        "description": product_description,
        "cta": call_to_action,
        "keywords": [part.strip() for part in re.split(r"[,\s]+", product_description) if part.strip()][:8],
        "values": [],
        "palette": {"primary": "#0f766e", "secondary": "#134e4a", "accent": "#f59e0b", "all": ["#0f766e", "#134e4a", "#f59e0b"]},
        "voice": {"primary_tone": "professional", "secondary_tone": "friendly"},
        "images": [],
        "source_url": website_urls[0] if website_urls else "",
    }
    return build_branded_campaign(
        brand=brand,
        campaign_title=project_name or f"{brand_name} Campaign",
        brief=product_description,
        call_to_action=call_to_action,
        platforms=platforms,
        uploaded_files=uploaded_files,
        generated_root=generated_root,
        clip_duration=clip_duration,
    )


def extract_website_metadata(url: str, download_dir: Path, source_index: int) -> dict[str, Any]:
    # Compatibility shim for older API route.
    from .brand_dna import _download_bytes, _save_image, assert_public_http_url, fetch_public_url
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup

    metadata = {
        "url": url,
        "title": "",
        "description": "",
        "source_image_url": "",
        "downloaded_image_path": None,
        "error": "",
    }
    try:
        assert_public_http_url(url)
        fetched = fetch_public_url(url, timeout=20, max_bytes=2_000_000)
        if not fetched:
            raise ValueError("Could not safely fetch website URL.")
        final_url, page_bytes = fetched
        soup = BeautifulSoup(page_bytes.decode("utf-8", errors="ignore"), "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        description = ""
        description_meta = soup.find("meta", attrs={"name": "description"})
        if description_meta and description_meta.get("content"):
            description = description_meta["content"].strip()
        source_image = ""
        for attr_set in ({"property": "og:image"}, {"name": "twitter:image"}):
            tag = soup.find("meta", attrs=attr_set)
            if tag and tag.get("content"):
                source_image = urljoin(final_url, tag["content"].strip())
                break
        downloaded = None
        if source_image:
            content = _download_bytes(source_image)
            if content:
                downloaded = _save_image(content, download_dir / f"website-{source_index}.jpg")
        metadata.update(
            {
                "title": title,
                "description": description,
                "source_image_url": source_image,
                "downloaded_image_path": downloaded,
            }
        )
        return metadata
    except Exception as exc:  # pylint: disable=broad-exception-caught
        metadata["error"] = str(exc)
        return metadata
