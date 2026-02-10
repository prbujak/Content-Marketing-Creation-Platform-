from __future__ import annotations

import json
import re
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps


PLATFORM_PRESETS: dict[str, dict[str, Any]] = {
    "instagram": {
        "label": "Instagram",
        "tone": "visual-first, energetic, and conversion-ready",
        "hashtags": ["#InstagramMarketing", "#CreatorTools", "#Growth"],
        "image_size": (1080, 1080),
        "video_size": (1080, 1920),
    },
    "facebook": {
        "label": "Facebook",
        "tone": "friendly, story-led, and audience-building",
        "hashtags": ["#FacebookAds", "#DigitalMarketing", "#BrandAwareness"],
        "image_size": (1200, 630),
        "video_size": (1080, 1080),
    },
    "tiktok": {
        "label": "TikTok",
        "tone": "short, trendy, and punchy",
        "hashtags": ["#TikTokMarketing", "#SmallBusiness", "#ViralContent"],
        "image_size": (1080, 1920),
        "video_size": (1080, 1920),
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "tone": "hook-driven and educational",
        "hashtags": ["#YouTubeShorts", "#MarketingTips", "#BusinessGrowth"],
        "image_size": (1280, 720),
        "video_size": (1080, 1920),
    },
    "linkedin": {
        "label": "LinkedIn",
        "tone": "professional, insight-led, and trust-building",
        "hashtags": ["#B2BMarketing", "#LinkedInGrowth", "#ThoughtLeadership"],
        "image_size": (1200, 627),
        "video_size": (1080, 1080),
    },
    "x": {
        "label": "X (Twitter)",
        "tone": "concise, opinionated, and timely",
        "hashtags": ["#Marketing", "#BuildInPublic", "#Startups"],
        "image_size": (1600, 900),
        "video_size": (1280, 720),
    },
    "pinterest": {
        "label": "Pinterest",
        "tone": "inspirational and discovery-oriented",
        "hashtags": ["#PinterestMarketing", "#Inspiration", "#Design"],
        "image_size": (1000, 1500),
        "video_size": (1080, 1920),
    },
}

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

RESAMPLE_METHOD = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


def slugify(value: str, fallback: str = "campaign") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return cleaned or fallback


def parse_links(raw_links: list[str]) -> list[str]:
    links: list[str] = []
    for chunk in raw_links:
        for part in re.split(r"[\n,]+", chunk or ""):
            candidate = part.strip()
            if candidate:
                links.append(candidate)
    return links


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES


def split_media(files: list[Path]) -> tuple[list[Path], list[Path]]:
    images = [path for path in files if _is_image(path)]
    videos = [path for path in files if _is_video(path)]
    return images, videos


def _download_image(image_url: str, output_path: Path) -> Path | None:
    try:
        response = requests.get(image_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return None

    content_type = response.headers.get("Content-Type", "")
    if "image" not in content_type.lower():
        return None

    output_path.write_bytes(response.content)
    return output_path


def extract_website_metadata(url: str, download_dir: Path, source_index: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "url": url,
        "title": "",
        "description": "",
        "source_image_url": "",
        "downloaded_image_path": None,
        "error": "",
    }

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "MarketingContentStudio/1.0 (+https://example.local)"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
        description = ""
        description_meta = soup.find("meta", attrs={"name": "description"})
        if description_meta and description_meta.get("content"):
            description = description_meta["content"].strip()

        og_description = soup.find("meta", attrs={"property": "og:description"})
        if not description and og_description and og_description.get("content"):
            description = og_description["content"].strip()

        source_image = ""
        for attr_set in (
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:image:url"},
        ):
            tag = soup.find("meta", attrs=attr_set)
            if tag and tag.get("content"):
                source_image = tag["content"].strip()
                break

        if source_image:
            source_image = urljoin(str(response.url), source_image)
            image_name = f"website-{source_index}.jpg"
            downloaded = _download_image(source_image, download_dir / image_name)
            metadata["downloaded_image_path"] = downloaded

        metadata.update(
            {
                "title": page_title,
                "description": description,
                "source_image_url": source_image,
            }
        )
        return metadata
    except requests.RequestException as exc:
        metadata["error"] = str(exc)
        return metadata


def _pick_website_context(sources: list[dict[str, Any]]) -> dict[str, str]:
    context = {"title": "", "description": "", "url": ""}
    for source in sources:
        if source.get("title") and not context["title"]:
            context["title"] = source["title"]
            context["url"] = source.get("url", "")
        if source.get("description") and not context["description"]:
            context["description"] = source["description"]
        if context["title"] and context["description"]:
            break
    return context


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    words = text.split()
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

    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


def _gradient_background(size: tuple[int, int]) -> Image.Image:
    width, height = size
    top = (26, 58, 112)
    bottom = (34, 197, 94)
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


def _base_canvas(size: tuple[int, int], source_image: Path | None) -> Image.Image:
    if source_image and source_image.exists():
        with Image.open(source_image) as img:
            return ImageOps.fit(img.convert("RGB"), size, method=RESAMPLE_METHOD)
    return _gradient_background(size)


def render_marketing_image(
    output_path: Path,
    size: tuple[int, int],
    headline: str,
    body: str,
    cta: str,
    source_image: Path | None,
) -> None:
    canvas = _base_canvas(size, source_image).convert("RGBA")
    width, height = size

    dark_overlay = Image.new("RGBA", size, (7, 11, 20, 80))
    canvas = Image.alpha_composite(canvas, dark_overlay)
    draw = ImageDraw.Draw(canvas)

    panel_height = int(height * 0.45)
    panel_top = height - panel_height - int(height * 0.04)
    panel_left = int(width * 0.06)
    panel_right = int(width * 0.94)
    panel_bottom = height - int(height * 0.04)
    draw.rounded_rectangle(
        [(panel_left, panel_top), (panel_right, panel_bottom)],
        radius=max(18, int(min(width, height) * 0.02)),
        fill=(12, 18, 33, 190),
    )

    headline_font = _font(max(26, int(height * 0.065)), bold=True)
    body_font = _font(max(18, int(height * 0.036)))
    cta_font = _font(max(18, int(height * 0.032)), bold=True)

    cursor_y = panel_top + int(height * 0.04)
    content_x = panel_left + int(width * 0.04)
    content_width = (panel_right - panel_left) - int(width * 0.08)

    headline_lines = _wrap_text(draw, headline, headline_font, content_width, max_lines=3)
    for line in headline_lines:
        draw.text((content_x, cursor_y), line, font=headline_font, fill=(245, 247, 255, 255))
        cursor_y += int(headline_font.size * 1.2)

    cursor_y += int(height * 0.01)
    body_lines = _wrap_text(draw, body, body_font, content_width, max_lines=4)
    for line in body_lines:
        draw.text((content_x, cursor_y), line, font=body_font, fill=(223, 229, 245, 255))
        cursor_y += int(body_font.size * 1.35)

    button_text = cta[:55]
    button_width = _line_width(draw, button_text, cta_font) + int(width * 0.05)
    button_height = int(cta_font.size * 2)
    button_x = content_x
    button_y = panel_bottom - button_height - int(height * 0.03)

    draw.rounded_rectangle(
        [(button_x, button_y), (button_x + button_width, button_y + button_height)],
        radius=max(10, int(button_height * 0.33)),
        fill=(59, 130, 246, 255),
    )
    draw.text(
        (button_x + int(width * 0.018), button_y + int(button_height * 0.24)),
        button_text,
        font=cta_font,
        fill=(255, 255, 255, 255),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, format="PNG", optimize=True)


def build_copy_text(
    preset: dict[str, Any],
    brand_name: str,
    product_description: str,
    call_to_action: str,
    context: dict[str, str],
) -> str:
    title_seed = context.get("title") or product_description.split(".")[0][:85]
    if not title_seed:
        title_seed = f"{brand_name} helps your audience act faster."
    description_seed = context.get("description") or product_description
    if not description_seed:
        description_seed = "Automate your content workflow across major platforms."

    short_description = textwrap.shorten(description_seed, width=180, placeholder="...")
    hook = textwrap.shorten(title_seed, width=90, placeholder="...")
    hashtags = " ".join(preset["hashtags"])

    return (
        f"Hook: {hook}\n"
        f"Caption ({preset['label']} tone - {preset['tone']}):\n"
        f"{short_description}\n\n"
        f"CTA: {call_to_action}\n"
        f"Hashtags: {hashtags}\n"
    )


def _run_command(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
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
    result = subprocess.run(command, capture_output=True, text=True, check=False)
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
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if source_video and source_video.exists():
        source_duration = _probe_duration(source_video)
        if source_duration and source_duration < clip_duration:
            command = [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(source_video),
                "-t",
                str(clip_duration),
                "-vf",
                base_filter,
                "-r",
                "30",
                "-an",
                str(output_path),
            ]
        else:
            start_time = max(((source_duration or clip_duration) - clip_duration) / 2.0, 0.0)
            command = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start_time:.2f}",
                "-i",
                str(source_video),
                "-t",
                str(clip_duration),
                "-vf",
                base_filter,
                "-r",
                "30",
                "-an",
                str(output_path),
            ]
        _run_command(command)
        return

    if not source_image.exists():
        raise RuntimeError("Could not build video because no source image was available.")

    command = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(source_image),
        "-t",
        str(clip_duration),
        "-vf",
        base_filter,
        "-r",
        "30",
        "-an",
        str(output_path),
    ]
    _run_command(command)


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
    safe_project = slugify(project_name or brand_name or "campaign")
    campaign_id = f"{safe_project}-{uuid4().hex[:8]}"
    campaign_dir = generated_root / campaign_id
    copy_dir = campaign_dir / "copy"
    image_dir = campaign_dir / "images"
    video_dir = campaign_dir / "videos"
    website_dir = campaign_dir / "website"
    for directory in (copy_dir, image_dir, video_dir, website_dir):
        directory.mkdir(parents=True, exist_ok=True)

    website_sources = [
        extract_website_metadata(url=url, download_dir=website_dir, source_index=index)
        for index, url in enumerate(website_urls)
    ]
    context = _pick_website_context(website_sources)

    uploaded_images, uploaded_videos = split_media(uploaded_files)
    website_images = [
        source["downloaded_image_path"]
        for source in website_sources
        if isinstance(source.get("downloaded_image_path"), Path)
    ]

    default_image = uploaded_images[0] if uploaded_images else (website_images[0] if website_images else None)
    default_video = uploaded_videos[0] if uploaded_videos else None
    duration = max(8, min(12, int(clip_duration)))

    results: list[dict[str, Any]] = []

    for platform in platforms:
        preset = PLATFORM_PRESETS.get(platform)
        if not preset:
            continue

        platform_label = preset["label"]
        copy_text = build_copy_text(
            preset=preset,
            brand_name=brand_name,
            product_description=product_description,
            call_to_action=call_to_action,
            context=context,
        )

        copy_path = copy_dir / f"{platform}.txt"
        copy_path.write_text(copy_text, encoding="utf-8")

        card_headline = textwrap.shorten(
            context.get("title") or f"{brand_name} campaign for {platform_label}",
            width=72,
            placeholder="...",
        )
        card_body = textwrap.shorten(
            context.get("description") or product_description or "Launch a cross-platform campaign faster.",
            width=140,
            placeholder="...",
        )

        image_url = ""
        video_url = ""
        errors: list[str] = []
        image_source_for_video: Path | None = None

        if preset.get("image_size"):
            image_path = image_dir / f"{platform}.png"
            try:
                render_marketing_image(
                    output_path=image_path,
                    size=tuple(preset["image_size"]),
                    headline=card_headline,
                    body=card_body,
                    cta=call_to_action,
                    source_image=default_image,
                )
                image_url = f"/generated/{campaign_id}/images/{platform}.png"
                image_source_for_video = image_path
            except Exception as exc:  # pylint: disable=broad-exception-caught
                errors.append(f"Image generation failed: {exc}")

        if preset.get("video_size"):
            video_path = video_dir / f"{platform}.mp4"
            if image_source_for_video is None:
                temp_image = campaign_dir / "temp" / f"{platform}.png"
                render_marketing_image(
                    output_path=temp_image,
                    size=tuple(preset["video_size"]),
                    headline=card_headline,
                    body=card_body,
                    cta=call_to_action,
                    source_image=default_image,
                )
                image_source_for_video = temp_image

            try:
                create_marketing_video(
                    output_path=video_path,
                    size=tuple(preset["video_size"]),
                    clip_duration=duration,
                    source_video=default_video,
                    source_image=image_source_for_video,
                )
                video_url = f"/generated/{campaign_id}/videos/{platform}.mp4"
            except Exception as exc:  # pylint: disable=broad-exception-caught
                errors.append(f"Video generation failed: {exc}")

        results.append(
            {
                "platform_key": platform,
                "platform_label": platform_label,
                "copy": copy_text,
                "copy_url": f"/generated/{campaign_id}/copy/{platform}.txt",
                "image_url": image_url,
                "video_url": video_url,
                "errors": errors,
            }
        )

    public_sources: list[dict[str, Any]] = []
    for source in website_sources:
        clean = {
            "url": source.get("url", ""),
            "title": source.get("title", ""),
            "description": source.get("description", ""),
            "source_image_url": source.get("source_image_url", ""),
            "error": source.get("error", ""),
            "downloaded_image_url": "",
        }
        downloaded_path = source.get("downloaded_image_path")
        if isinstance(downloaded_path, Path) and downloaded_path.exists():
            clean["downloaded_image_url"] = (
                f"/generated/{campaign_id}/website/{downloaded_path.name}"
            )
        public_sources.append(clean)

    payload = {
        "campaign_id": campaign_id,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "clip_duration_seconds": duration,
        "platform_count": len(results),
        "website_sources": public_sources,
        "results": results,
    }
    (campaign_dir / "metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
