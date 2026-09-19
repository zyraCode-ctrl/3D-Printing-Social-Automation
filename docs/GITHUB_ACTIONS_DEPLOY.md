# Free daily deploy (GitHub Actions)

This project runs on **GitHub Actions** (free hosted runners) once per day.  
It is **not** a 24/7 VPS — each run boots Docker, verifies the pipeline with `DRY_RUN=true`, then shuts down. **Nothing is published** to Instagram, Facebook, Pinterest, or YouTube Shorts.

## Schedule

- Cron: `30 3 * * *` UTC = **09:00 Asia/Kolkata**
- Also runs on manual **workflow_dispatch** and on pushes that touch the stack

## Required GitHub secrets

Repo → **Settings → Secrets and variables → Actions**:

| Secret | Purpose |
| --- | --- |
| `N8N_ENCRYPTION_KEY` | Long random string (≥32 chars) for n8n |
| `N8N_OWNER_PASSWORD` | n8n owner password for headless import |
| `N8N_OWNER_EMAIL` | Optional (default `admin@localhost.local`) |
| `GOOGLE_DRIVE_FOLDER_ID` | Optional (defaults to the public folder already in `config/settings.json`) |
| `GEMINI_API_KEY` | Free-tier Gemini key for AI dry-run |
| `YOUTUBE_OAUTH_CLIENT_ID` | Optional — Google OAuth Web client ID (no tokens) |
| `YOUTUBE_OAUTH_CLIENT_SECRET` | Optional — Google OAuth Web client secret (no tokens) |

YouTube **Sign in with Google** (refresh token) cannot be completed headlessly in Actions. Store client id/secret only if you want import to prefill the n8n credential shell; browser consent stays on a local n8n session. Keep social **upload** blocked with `DRY_RUN=true`.

## What each run verifies

1. `tracking-api` + `n8n` healthy  
2. `DRY_RUN=true` blocks publish  
3. Workflows imported (including **07 YouTube Shorts Publisher**)  
4. Public Drive folder list (when folder id present)  
5. If `GEMINI_API_KEY` is set: attempts one daily dry-run execution  

## Manual run

Actions → **Daily social dry-run** → **Run workflow**
