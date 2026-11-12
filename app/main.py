from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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
    save_catalog_item,
    update_brand,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = BASE_DIR / "generated"
UPLOAD_DIR = BASE_DIR / "uploads"

for directory in (STATIC_DIR, GENERATED_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Helix",
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


class CatalogRequest(BaseModel):
    brand_id: str
    name: str
    description: str = ""
    source_url: str = ""
    image_url: str = ""


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
    return selected


async def _save_uploads(files: list[UploadFile] | None) -> list[Path]:
    if not files:
        return []
    request_upload_dir = UPLOAD_DIR / f"request-{uuid4().hex[:8]}"
    request_upload_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[Path] = []
    for uploaded in files:
        if not uploaded.filename:
            continue
        safe_name = _sanitize_filename(uploaded.filename)
        destination = request_upload_dir / f"{uuid4().hex[:8]}-{safe_name}"
        with destination.open("wb") as file_buffer:
            shutil.copyfileobj(uploaded.file, file_buffer)
        saved_files.append(destination)
        await uploaded.close()
    return saved_files


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


@app.get("/api/brands")
def api_list_brands() -> dict:
    return {"brands": [brand_summary(item) for item in list_brands()]}


@app.get("/api/brands/{brand_id}")
def api_get_brand(brand_id: str) -> dict:
    brand = get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found.")
    return brand_summary(brand)


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
    updates = {key: value for key, value in payload.model_dump().items() if value is not None}
    brand = update_brand(brand_id, updates)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found.")
    return brand_summary(brand)


@app.post("/api/campaign-ideas")
def api_campaign_ideas(payload: IdeasRequest) -> dict:
    brand = get_brand(payload.brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found.")
    ideas = generate_campaign_ideas(
        brand=brand,
        product_name=payload.product_name,
        custom_prompt=payload.custom_prompt,
    )
    return {"ideas": ideas}


@app.get("/api/catalog")
def api_list_catalog(brand_id: str | None = None) -> dict:
    return {"items": list_catalog(brand_id)}


@app.post("/api/catalog")
def api_create_catalog_item(payload: CatalogRequest) -> dict:
    brand = get_brand(payload.brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found.")
    item = save_catalog_item(payload.model_dump())
    return item


@app.get("/api/campaigns")
def api_list_campaigns(brand_id: str | None = None) -> dict:
    return {"campaigns": list_campaigns(brand_id)}


@app.get("/api/campaigns/{campaign_id}")
def api_get_campaign(campaign_id: str) -> dict:
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
    brand = get_brand(brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand DNA not found. Build Business DNA first.")

    selected = _normalize_platforms(platforms) or list(PLATFORM_PRESETS.keys())
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

        selected = _normalize_platforms(platforms) or list(PLATFORM_PRESETS.keys())
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

    selected = _normalize_platforms(platforms) or list(PLATFORM_PRESETS.keys())
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
