# Free daily deploy (GitHub Actions)

This project runs on **GitHub Actions** (free hosted runners) once per day.  
It is **not** a 24/7 VPS — each run boots Docker, verifies the pipeline with `DRY_RUN=true`, then shuts down. **Nothing is published** to Instagram, Facebook, Pinterest, or YouTube Shorts.

## Schedule

The time is **not** in the workflow file. It comes from `config/schedule.json`, which the dashboard edits (see [DASHBOARD.md](DASHBOARD.md)).

- A light **gate** job runs every 15 minutes (`*/15 * * * *`). It reads `config/schedule.json` and starts the full dry-run only once the selected local time (Asia/Kolkata) has passed today.
- After a successful scheduled run, a `daily-run-marker-<date>` cache entry stops further runs that day.
- Changing the time on the dashboard pushes `config/schedule.json` to this repo (when `GITHUB_SYNC_TOKEN` is set locally), so the next gate check follows the new time with no code change.
- GitHub may delay scheduled jobs by a few minutes; the run happens at the first gate check after the selected time.
- Also runs on manual **workflow_dispatch** and on pushes that touch the stack (those always run)

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

1. Offline tests: schedule rules, queue advancement, duplicate prevention, persistence, GitHub sync (`scripts/test_schedule_queue.py`) and workflow validation  
2. `tracking-api` + `n8n` healthy  
3. `DRY_RUN=true` blocks publish  
4. Dashboard, `/schedule` (matches `config/schedule.json`) and `/queue` respond  
5. Workflows imported (including **07 YouTube Shorts Publisher** and **16 Content Queue Preparer**)  
6. Public Drive folder list (when folder id present)  
7. If `GEMINI_API_KEY` is set: runs one Daily Publisher dry-run (prepares the queue head and finalizes it without posting)  

## Manual run

Actions → **Daily social dry-run** → **Run workflow**
