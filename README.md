# Marketing Content Studio

A full-stack app for generating marketing assets across major social platforms.

## What it does

- Generates campaign-ready **images** for Instagram, Facebook, TikTok, YouTube Shorts, LinkedIn, X, and Pinterest.
- Generates **8-12 second MP4 clips** for the same platforms.
- Accepts **file uploads** (images/videos) as source media.
- Accepts **website links** to extract title, description, and open-graph images for content generation.
- Produces per-platform output:
  - post copy
  - downloadable image
  - downloadable short clip

## Tech stack

- Backend: FastAPI
- Frontend: Vanilla HTML/CSS/JS
- Media processing: Pillow + ffmpeg
- Website parsing: requests + BeautifulSoup

## Run locally

1. Install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start the app:

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. Open:

   ```text
   http://localhost:8000
   ```

## API endpoints

- `GET /api/platforms`  
  Returns supported platform presets.

- `POST /api/website-insights`  
  Body: `{ "links": "https://example.com, https://another.com" }`  
  Returns scraped metadata.

- `POST /api/generate` (multipart form)  
  Fields:
  - `project_name` (required if brand name absent)
  - `brand_name`
  - `product_description`
  - `call_to_action`
  - `website_links` (comma/newline separated)
  - `clip_duration` (8-12)
  - `platforms` (repeat field)
  - `files` (multiple uploads)

Generated assets are served from `/generated/<campaign-id>/...`.

## Notes

- ffmpeg must be available on your machine (already available in this cloud environment).
- The app currently uses template-based copy generation and website metadata extraction.
