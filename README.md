# eMarketster — Brand DNA Campaign Studio

eMarketster replicates the core workflows of **Google Pomelli** and **Jasper**, now with optional **OpenRouter** multi-model AI.

## What you get

1. **Business DNA** from a website (voice, palette, fonts, imagery)
2. **Campaign ideas** (AI when OpenRouter is configured)
3. **Multi-channel packs** — social, email, blog, ads, landing
4. **Creatives** — on-brand images + 8–12s clips
5. **Catalog** for products/services
6. **Creative editor** to revise headline/body/CTA and regenerate AI images

## OpenRouter setup (multi-model)

Add this secret in Cursor (Secrets / publish bindings):

- `OPENROUTER_API_KEY`

Optional env overrides:

- `OPENROUTER_TEXT_MODEL` (default `openai/gpt-4o-mini`)
- `OPENROUTER_IMAGE_MODEL` (default `google/gemini-2.5-flash-image-preview`)

Without a key, eMarketster still runs in **sample/template mode**.

OpenRouter can route across many models; eMarketster sends fallback model lists automatically.

## Run locally

```bash
python3 -m pip install --user -r requirements.txt
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

## Security notes

- Outbound website/asset fetches validate public http(s) targets and redirect hops
- Storage IDs are sanitized with path containment checks
- Uploads and ffmpeg/image work are size/timeout limited
