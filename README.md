# eMarketster — Jasper + Pomelli Workspace

One app that combines **Google Pomelli** Business DNA creatives with **Jasper** multi-channel content operations.

## Dual-world feature map

### Pomelli side
- Business DNA from website
- Brand Agent chat to refine DNA
- Catalog / product ingredients
- Campaign ideas + branded creatives
- Photoshoot generator
- Brand book export
- Mini website generator
- 8–12s animated clips

### Jasper side
- Brand voice + knowledge base
- Audiences
- Instant Magic content apps (LinkedIn, email, blog, landing, SEO, ads, PR, etc.)
- Social calendar planning
- Localization
- Content library
- Campaign channel packs (social/email/blog/ads/landing)

## Production behavior

- Cursor identity required on all `/api/*` routes in published/hosted runtimes (JWT locked to RS256)
- Per-user data scoping by signed-in identity
- Durable Postgres when `DATABASE_URL` is present (declared via `cursor-app.json`); local/dev falls back to filesystem JSON
- Rate limits on expensive generation routes
- HTML exports escaped with CSP
- OpenRouter multi-model AI with sample fallback when no key is bound

## Secrets

Required for live AI:

- `OPENROUTER_API_KEY`

Optional:

- `OPENROUTER_TEXT_MODEL` (default `openai/gpt-4o-mini`)
- `OPENROUTER_IMAGE_MODEL` (default `google/gemini-2.5-flash-image-preview`)
- `OPENROUTER_HTTP_REFERER`

`DATABASE_URL` is provided by Cursor when the app database is enabled. Do not put it in files.

## Run locally

```bash
python3 -m pip install --user -r requirements.txt
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET /health`
