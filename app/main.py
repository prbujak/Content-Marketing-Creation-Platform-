from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .content_engine import PLATFORM_PRESETS, build_campaign, extract_website_metadata, parse_links


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = BASE_DIR / "generated"
UPLOAD_DIR = BASE_DIR / "uploads"

for directory in (STATIC_DIR, GENERATED_DIR, UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Marketing Content Studio",
    summary="Create platform-ready images and 8-12 second clips from uploads or website links.",
)
app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class WebsiteInsightRequest(BaseModel):
    links: str


def _sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", filename).strip("-")
    return cleaned or f"upload-{uuid4().hex[:6]}"


def _normalize_platforms(raw_platforms: list[str]) -> list[str]:
    selected: list[str] = []
    for chunk in raw_platforms:
        for candidate in chunk.split(","):
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


@app.post("/api/website-insights")
def website_insights(payload: WebsiteInsightRequest) -> dict[str, list[dict[str, str]]]:
    links = parse_links([payload.links])
    if not links:
        raise HTTPException(status_code=400, detail="Please provide at least one website URL.")

    insight_dir = UPLOAD_DIR / f"insights-{uuid4().hex[:8]}"
    insight_dir.mkdir(parents=True, exist_ok=True)
    details = []
    for index, link in enumerate(links):
        metadata = extract_website_metadata(url=link, download_dir=insight_dir, source_index=index)
        details.append(
            {
                "url": metadata.get("url", ""),
                "title": metadata.get("title", ""),
                "description": metadata.get("description", ""),
                "source_image_url": metadata.get("source_image_url", ""),
                "error": metadata.get("error", ""),
            }
        )
    return {"insights": details}


@app.post("/api/generate")
async def generate(
    project_name: str = Form(default=""),
    brand_name: str = Form(default=""),
    product_description: str = Form(default=""),
    call_to_action: str = Form(default="Learn more"),
    website_links: str = Form(default=""),
    clip_duration: int = Form(default=10),
    platforms: list[str] = Form(default=[]),
    files: list[UploadFile] | None = File(default=None),
) -> dict:
    if not (project_name.strip() or brand_name.strip()):
        raise HTTPException(status_code=400, detail="Project name or brand name is required.")

    selected_platforms = _normalize_platforms(platforms)
    if not selected_platforms:
        selected_platforms = list(PLATFORM_PRESETS.keys())

    cleaned_links = parse_links([website_links])
    saved_files = await _save_uploads(files)

    try:
        payload = build_campaign(
            project_name=project_name.strip(),
            brand_name=brand_name.strip() or project_name.strip(),
            product_description=product_description.strip(),
            call_to_action=call_to_action.strip() or "Learn more",
            platforms=selected_platforms,
            website_urls=cleaned_links,
            uploaded_files=saved_files,
            generated_root=GENERATED_DIR,
            clip_duration=clip_duration,
        )
        return payload
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(status_code=500, detail=f"Failed to generate campaign: {exc}") from exc
