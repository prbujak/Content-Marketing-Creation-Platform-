from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai import ai_status
from .brand_dna import brand_summary, build_brand_dna
from .content_engine import (
    PLATFORM_PRESETS,
    build_branded_campaign,
    generate_campaign_ideas,
    parse_links,
)
from .storage import (
    get_brand,
    get_campaign,
    list_brands,
    list_campaigns,
    list_catalog,
    sanitize_id,
    save_campaign,
    save_catalog_item,
    update_brand,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = BASE_DIR / "generated"
UPLOAD_DIR = BASE_DIR / "uploads"

MAX_UPLOAD_FILES = 5
MAX_UPLOAD_BYTES_PER_FILE = 15 * 1024 * 1024  # 15 MB
MAX_UPLOAD_BYTES_TOTAL = 40 * 1024 * 1024  # 40 MB
MAX_PLATFORMS_PER_REQUEST = 4

for directory in (STATIC_DIR, GENERATED_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="eMarketster",
    summary="Pomelli-style Business DNA + Jasper-style multi-channel campaign studio.",
)
app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class BrandDNARequest(BaseModel):
    website_url: str
    brand_name: str = ""
    extra_notes: str = ""


class BrandUpdateRequest(BaseModel):
    name: str | None = None
    tagline: str | None = None
    description: str | None = None
    cta: str | None = None
    extra_notes: str | None = None
    voice: dict | None = None


class IdeasRequest(BaseModel):
    brand_id: str
    product_name: str = ""
    custom_prompt: str = ""
    text_model: str = ""


class CatalogRequest(BaseModel):
    brand_id: str
    name: str
    description: str = ""
    source_url: str = ""
    image_url: str = ""


class CreativeEditRequest(BaseModel):
    campaign_id: str
    platform_key: str
    headline: str = ""
    body: str = ""
    cta: str = ""
    regenerate_ai_image: bool = True


class CampaignGenerateRequest(BaseModel):
    brand_id: str
    title: str = ""
    brief: str = ""
    call_to_action: str = ""
    platforms: list[str] = Field(default_factory=list)
    clip_duration: int = 10
    idea: dict = Field(default_factory=dict)


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", filename).strip("-")
    return cleaned or f"upload-{uuid4().hex[:6]}"


def _normalize_platforms(raw_platforms: list[str]) -> list[str]:
    selected: list[str] = []
    for chunk in raw_platforms:
        for candidate in str(chunk).split(","):
            value = candidate.strip().lower()
            if value and value in PLATFORM_PRESETS and value not in selected:
                selected.append(value)
            if len(selected) >= MAX_PLATFORMS_PER_REQUEST:
                return selected
    return selected


async def _save_uploads(files: list[UploadFile] | None) -> list[Path]:
    if not files:
        return []

    usable = [uploaded for uploaded in files if uploaded.filename]
    if len(usable) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many uploads. Maximum is {MAX_UPLOAD_FILES} files.",
        )

    request_upload_dir = UPLOAD_DIR / f"request-{uuid4().hex[:8]}"
    request_upload_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[Path] = []
    total_bytes = 0

    for uploaded in usable:
        safe_name = _sanitize_filename(uploaded.filename)
        destination = request_upload_dir / f"{uuid4().hex[:8]}-{safe_name}"
        written = 0
        with destination.open("wb") as file_buffer:
            while True:
                chunk = await uploaded.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                total_bytes += len(chunk)
                if written > MAX_UPLOAD_BYTES_PER_FILE or total_bytes > MAX_UPLOAD_BYTES_TOTAL:
                    file_buffer.close()
                    destination.unlink(missing_ok=True)
                    await uploaded.close()
                    raise HTTPException(
                        status_code=400,
                        detail="Upload exceeds size limits (15MB/file, 40MB total).",
                    )
                file_buffer.write(chunk)
        saved_files.append(destination)
        await uploaded.close()
    return saved_files



def _require_brand(brand_id: str) -> dict:
    try:
        safe_id = sanitize_id(brand_id, label="brand_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    brand = get_brand(safe_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found.")
    return brand


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/platforms")
def get_platforms() -> dict[str, list[dict[str, str]]]:
    platforms = [
        {"key": key, "label": preset["label"], "tone": preset["tone"]}
        for key, preset in PLATFORM_PRESETS.items()
    ]
    return {"platforms": platforms}


@app.get("/api/ai-status")
def api_ai_status() -> dict:
    return ai_status()


@app.get("/api/brands")
def api_list_brands() -> dict:
    return {"brands": [brand_summary(item) for item in list_brands()]}


@app.get("/api/brands/{brand_id}")
def api_get_brand(brand_id: str) -> dict:
    return brand_summary(_require_brand(brand_id))


@app.post("/api/brand-dna")
def api_build_brand_dna(payload: BrandDNARequest) -> dict:
    url = payload.website_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Website URL is required.")
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    try:
        brand = build_brand_dna(
            website_url=url,
            asset_root=GENERATED_DIR,
            brand_name_override=payload.brand_name,
            extra_notes=payload.extra_notes,
        )
        return brand_summary(brand)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=400, detail=f"Could not build Brand DNA: {exc}") from exc


@app.patch("/api/brands/{brand_id}")
def api_update_brand(brand_id: str, payload: BrandUpdateRequest) -> dict:
    _require_brand(brand_id)
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        brand = update_brand(brand_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found.")
    return brand_summary(brand)


@app.post("/api/campaign-ideas")
def api_campaign_ideas(payload: IdeasRequest) -> dict:
    brand = _require_brand(payload.brand_id)
    ideas = generate_campaign_ideas(
        brand=brand,
        product_name=payload.product_name,
        custom_prompt=payload.custom_prompt,
    )
    return {"ideas": ideas}


@app.get("/api/catalog")
def api_list_catalog(brand_id: str | None = None) -> dict:
    if brand_id:
        try:
            brand_id = sanitize_id(brand_id, label="brand_id")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": list_catalog(brand_id)}


@app.post("/api/catalog")
def api_create_catalog_item(payload: CatalogRequest) -> dict:
    _require_brand(payload.brand_id)
    try:
        item = save_catalog_item(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@app.get("/api/campaigns")
def api_list_campaigns(brand_id: str | None = None) -> dict:
    if brand_id:
        try:
            brand_id = sanitize_id(brand_id, label="brand_id")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"campaigns": list_campaigns(brand_id)}


@app.get("/api/campaigns/{campaign_id}")
def api_get_campaign(campaign_id: str) -> dict:
    try:
        sanitize_id(campaign_id, label="campaign_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    campaign = get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


@app.post("/api/campaigns/generate")
async def api_generate_campaign(
    brand_id: str = Form(...),
    title: str = Form(default=""),
    brief: str = Form(default=""),
    call_to_action: str = Form(default=""),
    clip_duration: int = Form(default=10),
    platforms: list[str] = Form(default=[]),
    idea_title: str = Form(default=""),
    idea_angle: str = Form(default=""),
    idea_objective: str = Form(default=""),
    idea_channels: str = Form(default=""),
    files: list[UploadFile] | None = File(default=None),
) -> dict:
    brand = _require_brand(brand_id)

    selected = _normalize_platforms(platforms) or list(PLATFORM_PRESETS.keys())[:MAX_PLATFORMS_PER_REQUEST]
    saved_files = await _save_uploads(files)
    idea = {
        "title": idea_title,
        "angle": idea_angle,
        "objective": idea_objective,
        "channels": idea_channels,
    }
    try:
        payload = build_branded_campaign(
            brand=brand,
            campaign_title=title.strip() or idea_title or f"{brand.get('name')} Campaign",
            brief=brief.strip() or idea_angle,
            call_to_action=call_to_action.strip() or brand.get("cta") or "Learn more",
            platforms=selected,
            uploaded_files=saved_files,
            generated_root=GENERATED_DIR,
            clip_duration=clip_duration,
            idea=idea if any(idea.values()) else None,
        )
        return payload
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=f"Failed to generate campaign: {exc}") from exc



@app.post("/api/creatives/edit")
def api_edit_creative(payload: CreativeEditRequest) -> dict:
    from .ai import ai_image_prompt, generate_image_bytes, save_data_url_image
    from .content_engine import PLATFORM_PRESETS, create_marketing_video, render_marketing_image

    try:
        sanitize_id(payload.campaign_id, label="campaign_id")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    campaign = get_campaign(payload.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    platform = payload.platform_key.strip().lower()
    preset = PLATFORM_PRESETS.get(platform)
    if not preset:
        raise HTTPException(status_code=400, detail="Unknown platform.")

    brand = get_brand(campaign.get("brand_id") or "") if campaign.get("brand_id") else None
    brand = brand or {
        "name": campaign.get("brand_name") or "Brand",
        "palette": campaign.get("palette") or {},
        "voice": campaign.get("voice") or {},
    }

    result_item = None
    for item in campaign.get("results") or []:
        if item.get("platform_key") == platform:
            result_item = item
            break
    if not result_item:
        raise HTTPException(status_code=404, detail="Creative not found for platform.")

    headline = payload.headline.strip() or result_item.get("copy", "").split("\n")[0][:72]
    body = payload.body.strip() or campaign.get("brief") or ""
    cta = payload.cta.strip() or "Learn more"

    image_dir = GENERATED_DIR / payload.campaign_id / "images"
    video_dir = GENERATED_DIR / payload.campaign_id / "videos"
    copy_dir = GENERATED_DIR / payload.campaign_id / "copy"
    image_path = image_dir / f"{platform}.png"
    video_path = video_dir / f"{platform}.mp4"
    source_image = None

    if payload.regenerate_ai_image:
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
            source_image = save_data_url_image(raw, ai_path)

    try:
        render_marketing_image(
            output_path=image_path,
            size=tuple(preset["image_size"]),
            headline=headline,
            body=body,
            cta=cta,
            brand_name=brand.get("name", "Brand"),
            source_image=source_image,
            palette=brand.get("palette") or campaign.get("palette") or {},
        )
        create_marketing_video(
            output_path=video_path,
            size=tuple(preset["video_size"]),
            clip_duration=int(campaign.get("clip_duration_seconds") or 10),
            source_video=None,
            source_image=image_path,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=f"Failed to update creative: {exc}") from exc

    caption = f"{headline}\n\n{body}\n\n{cta}"
    copy_dir.mkdir(parents=True, exist_ok=True)
    (copy_dir / f"{platform}.txt").write_text(caption, encoding="utf-8")

    result_item["copy"] = caption
    result_item["image_url"] = f"/generated/{payload.campaign_id}/images/{platform}.png?v={uuid4().hex[:6]}"
    result_item["video_url"] = f"/generated/{payload.campaign_id}/videos/{platform}.mp4?v={uuid4().hex[:6]}"
    result_item["copy_url"] = f"/generated/{payload.campaign_id}/copy/{platform}.txt"
    result_item["errors"] = []

    for idx, item in enumerate(campaign.get("results") or []):
        if item.get("platform_key") == platform:
            campaign["results"][idx] = result_item
            break
    save_campaign(campaign)
    return {"campaign": campaign, "result": result_item}


# Compatibility endpoint kept for older clients.
@app.post("/api/generate")
async def generate_compat(
    project_name: str = Form(default=""),
    brand_name: str = Form(default=""),
    product_description: str = Form(default=""),
    call_to_action: str = Form(default="Learn more"),
    website_links: str = Form(default=""),
    clip_duration: int = Form(default=10),
    platforms: list[str] = Form(default=[]),
    files: list[UploadFile] | None = File(default=None),
) -> dict:
    links = parse_links([website_links])
    brand = None
    if links:
        try:
            brand = build_brand_dna(
                website_url=links[0],
                asset_root=GENERATED_DIR,
                brand_name_override=brand_name,
            )
        except Exception:
            brand = None
    if brand is None:
        # Fall back to ephemeral brand object via branded campaign helper path.
        from .content_engine import build_campaign

        selected = _normalize_platforms(platforms) or list(PLATFORM_PRESETS.keys())[:MAX_PLATFORMS_PER_REQUEST]
        saved_files = await _save_uploads(files)
        return build_campaign(
            project_name=project_name,
            brand_name=brand_name or project_name,
            product_description=product_description,
            call_to_action=call_to_action,
            platforms=selected,
            website_urls=links,
            uploaded_files=saved_files,
            generated_root=GENERATED_DIR,
            clip_duration=clip_duration,
        )

    selected = _normalize_platforms(platforms) or list(PLATFORM_PRESETS.keys())[:MAX_PLATFORMS_PER_REQUEST]
    saved_files = await _save_uploads(files)
    return build_branded_campaign(
        brand=brand,
        campaign_title=project_name or f"{brand.get('name')} Campaign",
        brief=product_description or brand.get("description", ""),
        call_to_action=call_to_action or brand.get("cta") or "Learn more",
        platforms=selected,
        uploaded_files=saved_files,
        generated_root=GENERATED_DIR,
        clip_duration=clip_duration,
    )
