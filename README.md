# eMarketster — Brand DNA Campaign Studio

eMarketster replicates the core workflows of **Google Pomelli** and **Jasper**:

1. **Business DNA** (Pomelli): paste a website URL to extract brand voice, palette, fonts, imagery, and values.
2. **Campaign ideas** (Pomelli + Jasper): generate tailored campaign concepts or use a custom brief.
3. **Multi-channel creatives** (Jasper + Pomelli): produce social posts, email, blog, ads, landing copy, on-brand images, and **8–12 second clips**.

## Features

- Website → Brand DNA extraction
- Brand voice rules and palette swatches
- Campaign idea generator
- Jasper-style channel pack (email / blog / ads / landing / social)
- Platform-ready images + short MP4 clips
- Upload extra images/videos as creative source media
- Local JSON persistence for brands, campaigns, and catalog seeds

## Supported platforms

Instagram, Facebook, TikTok, YouTube Shorts, LinkedIn, X, Pinterest

## Run locally

```bash
python3 -m pip install --user -r requirements.txt
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

## API

- `POST /api/brand-dna` — build Business DNA from a website
- `GET /api/brands` — list Brand DNA profiles
- `POST /api/campaign-ideas` — generate campaign ideas for a brand
- `POST /api/campaigns/generate` — create multi-channel creatives + clips
- `GET /api/platforms` — platform presets
- `GET/POST /api/catalog` — product/catalog helpers

## Notes

- ffmpeg is required for clip generation.
- Copy generation is deterministic/template-based and grounded in extracted Brand DNA (no external LLM key required).
- Connect an LLM provider later if you want fully free-form generative copy.
