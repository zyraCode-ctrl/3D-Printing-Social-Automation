# 3D Printing Store Social Media Automation

Cursor is the control environment. **n8n** is the automation engine. It runs locally in Docker on this PC and can later move to a 24/7 server without a rewrite.

This project does **not** use Zapier, Make, Buffer, upload-post.com, or a custom Node.js posting engine.

## What you have

| Piece | Role |
| --- | --- |
| n8n at http://localhost:5678 | Schedule, Google Drive, AI calls, official social APIs |
| Tracking API at http://localhost:8081 | SQLite product tracker, duplicate protection, logs, previews |
| Dashboard (GitHub Pages for production, http://localhost:8081/dashboard locally) | LIVE/DRY_RUN status, editable daily times, today's posts, next 6 posts, queue, per-platform results and post IDs ([docs/DASHBOARD.md](docs/DASHBOARD.md)) |

Local default: **`DRY_RUN=true`**. Live publishing runs only in GitHub Actions when the `PRODUCTION_LIVE` repository variable is `true` ([docs/PRODUCTION.md](docs/PRODUCTION.md)).

## Integration priority

Exact order: [docs/INTEGRATION_PRIORITY.md](docs/INTEGRATION_PRIORITY.md)

1. Google Drive — done  
2. Gemini — done  
3. Content generation — done  
4. YouTube Shorts API/OAuth — done → [docs/YOUTUBE_SHORTS_SETUP.md](docs/YOUTUBE_SHORTS_SETUP.md)  
5. **Pinterest API/OAuth — do now** → [docs/PINTEREST_SETUP.md](docs/PINTEREST_SETUP.md)  
6. Instagram Meta — after Meta access  
7. Facebook Meta — after Instagram  
8. Final full-system DRY_RUN  
9. Real publishing — only after your explicit approval  

## Production (GitHub Actions)

See [docs/PRODUCTION.md](docs/PRODUCTION.md). Production publishes on free GitHub-hosted runners at the dashboard times (default 6:00 PM and 10:00 PM IST) — no PC or local n8n required. Every push is also verified end-to-end in DRY_RUN ([docs/GITHUB_ACTIONS_DEPLOY.md](docs/GITHUB_ACTIONS_DEPLOY.md)).

## Daily behaviour

The publishing times are chosen on the dashboard (**Schedule settings**) and stored in `config/schedule.json`, the single source of truth (timezone **Asia/Kolkata**). There is no hard-coded time.

Continuously, **16 Content Queue Preparer** keeps the next **8** products ready in advance (at least 3 days of posts):

1. List files in the configured Google Drive folder.
2. Parse numeric Product IDs (`1.jpg`, `4.mp4`, …). `4.jpg` and `4.mp4` are the same product.
3. Pick the **lowest Product ID that is not fully completed and not already queued**.
4. Download the actual media and run **real vision AI**. No invented specs. No website URL.
5. Save the preview and add the product to the rolling queue.

At each selected time, **01 Daily Publisher**:

1. Takes the **queue head** (one product per time slot).
2. If `DRY_RUN=true`, logs the preview and stops. If `DRY_RUN=false`, publishes only platforms that have not already succeeded.
3. Marks the Product ID completed only when every **required** platform succeeded, then the queue advances and the preparer refills it.

Required platforms:

- Image-only: Instagram, Facebook Page, Pinterest. YouTube Shorts are skipped (Shorts need video).
- Video-only: Instagram Reels, Facebook Page, **YouTube Shorts**. Pinterest image Pins are skipped.
- Both image+video: Instagram, Facebook, Pinterest, **YouTube Shorts**.
- Image + video: all four, using the video where the platform is video-capable and the image for Pinterest.

## Start locally

From this folder, in PowerShell:

```powershell
python scripts/setup_env.py
python scripts/generate_samples.py
python scripts/generate_workflows.py
python scripts/validate_workflows.py
docker compose up -d --build
python scripts/import_workflows.py
python scripts/test_dry_run.py
```

Then open:

- n8n editor: http://localhost:5678
- Dashboard: http://localhost:8081/dashboard

Sign in at http://localhost:5678 using `N8N_OWNER_EMAIL` and `N8N_OWNER_PASSWORD` from `.env`.

The tracking-api scheduler starts 01 Daily Publisher at the dashboard time; you can also click **01 Daily Publisher** → **Execute workflow** for a one-off dry run. Admin webhooks need **02 Admin Control** published.

## First real dry run (Drive + vision AI, no social posting)

Keep `DRY_RUN=true`.

1. Confirm the Gemini key is saved in n8n (**Credentials** → **Google Gemini account**). Do not create an OpenAI API key.
2. Keep `GOOGLE_DRIVE_FOLDER_ID=1MU6xHdcI18mCbDsp1IxAyA9YoDfeRQKD` and `DRY_RUN=true`.
3. Open http://localhost:5678 and sign in with values from `.env`.
4. Open **01 Daily Publisher**.
5. Click **Execute workflow**. This lists the public Drive folder, downloads Product `1` (`001.mp4`), runs Gemini vision, saves a preview, and **does not post**.
6. Open http://localhost:8081/dashboard and `data/previews/1.json` to read the generated copy.

Do **not** set `DRY_RUN=false`.

Admin webhooks after publish:

- `POST http://localhost:5678/webhook/admin/run-now`
- `POST http://localhost:5678/webhook/admin/preview`
- `POST http://localhost:5678/webhook/admin/retry`
- `GET http://localhost:5678/webhook/admin/status`

## Connect Google Drive

This dry-run path uses the **public shared folder** (`DRIVE_ACCESS_MODE=public`). n8n lists and downloads media through the tracking API, not through the Google Drive OAuth node. That avoids the OAuth `SERVICE_DISABLED` / 403 path.

Folder ID is already set to `1MU6xHdcI18mCbDsp1IxAyA9YoDfeRQKD`. Keep the folder shared as **Anyone with the link**.

Optional later (not required for dry-run): OAuth Drive credentials can still be kept in n8n for private folders.

Supported files: `jpg`, `jpeg`, `png`, `webp`, `mp4`, `mov` named like `1.jpg` or `001.mp4`. Other files are ignored.

## Connect AI (Google Gemini free tier)

The production workflow uses **Google Gemini vision** through the n8n **Google Gemini account** credential (`googlePalmApi`). There is no mock fallback and **no OpenAI API**. ChatGPT Pro is not used.

If every Gemini model fails, the same prompt and schema go to **Groq** in one call (n8n credential **Groq account**). Setup and `GROQ_API_KEY`: [docs/GROQ_FALLBACK_SETUP.md](docs/GROQ_FALLBACK_SETUP.md).

Model: `gemini-3.6-flash` (vision-capable, Google AI Studio free tier). One product per day stays within the free quota. Do not enable paid billing.

### Create the Gemini API key

1. Open [Google AI Studio API keys](https://aistudio.google.com/app/apikey) and sign in with your Google account.
2. Click **Create API key**.
3. If asked, create or select a Google Cloud project. That does not require a paid plan for this free-tier key.
4. Copy the API key. Keep it private. Do not put it in `.env` and do not commit it.
5. Open http://localhost:5678 and sign in with `N8N_OWNER_EMAIL` / `N8N_OWNER_PASSWORD` from `.env`.
6. Go to **Credentials** → open **Google Gemini account** (already created by import).
7. Confirm **Host** is `https://generativelanguage.googleapis.com`.
8. Paste the API key into **API Key** → **Save**.
9. Open **03 AI Content Generator** and confirm **Gemini Vision** uses **Google Gemini account**.

Stop there until the key is saved. Then continue with Google Drive if that credential is not connected yet.

## Connect social accounts (do not publish yet)

Follow [docs/INTEGRATION_PRIORITY.md](docs/INTEGRATION_PRIORITY.md). **Current work: Pinterest API OAuth only.**

Keep `DRY_RUN=true`. Live posting needs your later explicit approval (priority step 9).

### YouTube Shorts (YouTube Data API v3) — done

In this project, **YouTube means YouTube Shorts only** — never long-form videos.

Setup guide: [docs/YOUTUBE_SHORTS_SETUP.md](docs/YOUTUBE_SHORTS_SETUP.md)

1. Enable **YouTube Data API v3** in Google Cloud.
2. Create an OAuth client (Web application) with redirect `http://localhost:5678/rest/oauth2-credential/callback`.
3. In n8n, open **YouTube account** and complete OAuth (Client ID/Secret stay in n8n only).
4. Keep `YOUTUBE_PRIVACY_STATUS=private`.
5. Keep `DRY_RUN=true` until you explicitly approve publishing.

Drive video products are treated as Shorts. Image-only products skip YouTube.

### Pinterest (API v5) — do now

Image Pins only. Videos are skipped on purpose.

Full click-by-click setup: [docs/PINTEREST_SETUP.md](docs/PINTEREST_SETUP.md)

1. Open [Pinterest Developers → My apps](https://developers.pinterest.com/apps/) with a **business** account and **Connect app** (trial access).
2. Add redirect `http://localhost:5678/rest/oauth2-credential/callback`.
3. In n8n, open **Pinterest account** (OAuth2 API), paste App ID/Secret, and connect.
4. Run **11 Pinterest Auth Probe** (lists account + boards; does not create Pins).
5. Set `PINTEREST_BOARD_ID` in `.env` from a board id returned by the probe.
6. Keep `DRY_RUN=true` until you explicitly approve publishing.

### Instagram + Facebook Page (Meta Graph API) — after Meta access

Configure only after Meta developer access is available, and **after** YouTube + Pinterest in the priority list. Instagram first, then Facebook.

Full click-by-click setup: [docs/META_IG_FB_SETUP.md](docs/META_IG_FB_SETUP.md)

1. Create a Meta Developer **Business** app and connect a Facebook Page + Instagram Professional account.
2. Generate a **Page access token** with the required Graph scopes.
3. Put `FACEBOOK_PAGE_ID` and `INSTAGRAM_BUSINESS_ACCOUNT_ID` in `.env`.
4. In n8n, open **Facebook Graph account** and paste the Page token (never into chat).
5. Run **09 Meta Auth Probe** to verify auth (does not publish).

Instagram live publish needs a **publicly reachable** media URL when you eventually go live.

## Website URL later

Leave `WEBSITE_URL` empty and `INCLUDE_WEBSITE_URL=false`. When the store is live, set both and regenerate content. Prompts already support a URL without requiring one now.

## Duplicate protection

Before every platform publish the workflow asks the tracker:

- If that Product ID + platform is already `published`, it will **not** post again.
- Retries only hit `pending` / `failed` platforms.
- A successful Instagram post is never repeated because Facebook failed.

Statuses: `pending`, `processing`, `published`, `failed`, `partial`. `skipped` is used when the official API cannot take that media type.

## Backup / restore

```powershell
./scripts/backup.ps1
./scripts/restore.ps1 -BackupDir .\data\backups\YYYYMMDD-HHMMSS
```

Keep `.env`’s `N8N_ENCRYPTION_KEY` forever. Credentials in the `n8n_data` Docker volume are encrypted with it. Losing the key means re-connecting every account.

## Move to a 24/7 server later

1. Copy this repo, `.env`, `data/`, and export n8n workflows/credentials.
2. Install Docker, run the same Compose file.
3. Point `WEBHOOK_URL`, `N8N_HOST`, and `N8N_PROTOCOL` at the public hostname.
4. Re-do OAuth redirect URLs for that hostname.
5. Only then consider `DRY_RUN=false`.

## Project layout

```
docker-compose.yml
.env.example
config/settings.json
config/schedule.json      # daily publishing time (edited from the dashboard)
config/prompts/
db/schema.sql
n8n/workflows/
services/tracking-api/
samples/
scripts/
```

## Live publishing

Do **not** set `DRY_RUN=false` until you say so. The first live YouTube run should still use `YOUTUBE_PRIVACY_STATUS=private` and publish a Short only (never long-form).
