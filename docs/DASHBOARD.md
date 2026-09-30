# Dashboard

Open **http://localhost:8081/dashboard** while the Docker stack is running (`docker compose up -d`). It is served by the existing `tracking-api` container and reads the same SQLite database and n8n executions — no extra service, database, or hosting cost. The port is bound to `127.0.0.1`, so it is only reachable from this PC.

## What it shows

- **System status** (read-only): Tracking API, database, n8n, scheduler, GitHub sync, and a prominent **DRY RUN / LIVE MODE** bar. DRY_RUN can only be changed in `.env`, never from the page.
- **Totals**: products, published, queue fill (x/3), platform successes / failures / skips.
- **Today's post** and **Next post** (the queue head and when it will go out).
- **Rolling queue**: the next 3 products with content already generated.
- **Per platform**: Instagram, Facebook Page, Pinterest, YouTube Shorts — success/failed/skipped counts and the latest post link.
- **Executions**: last/next run, AI provider used, retries and errors in the last 24 h.
- **Workflow runs** with a step-by-step detail panel, the **Products** table (status and platform post IDs per product), and **Recent activity**.

The page refreshes every 10 seconds. Tokens that appear in logs are redacted before they reach the browser.

## Schedule settings

Pick a time with the time picker and click **Save**.

- The time is written to `config/schedule.json` — the single source of truth. Timezone: **Asia/Kolkata**.
- The `tracking-api` scheduler checks every 30 seconds and starts **01 Daily Publisher** once per day at or after that time. If the PC was off at that time, it catches up the same day when the stack starts again (it never posts twice in one day).
- If you save a time that has already passed today, today's run is skipped and the new time applies from tomorrow. If today's post already went out, changing the time does not post again today.
- The file lives in the repo, so the time survives rebuilds and redeploys.

### Keep GitHub Actions on the same time (optional)

GitHub Actions reads `config/schedule.json` from the repository. To have a dashboard change pushed to GitHub automatically:

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Repository access**: *Only select repositories* → this repository.
3. **Permissions → Repository permissions → Contents**: *Read and write*. Nothing else.
4. Put the values in your local `.env` (never in chat, never committed):

   ```
   GITHUB_SYNC_TOKEN=<the token>
   GITHUB_REPOSITORY=<owner>/<repo>
   GITHUB_BRANCH=main
   ```

5. `docker compose up -d` so `tracking-api` picks them up.

The dashboard shows the sync result next to the schedule. If a push fails (e.g. offline), it is retried every 10 minutes. Without a token the local schedule still works; only GitHub Actions keeps the time committed in the repo.

## Rolling queue

- **16 Content Queue Preparer** keeps up to 3 products prepared (Drive media + AI content + saved preview), always in Product ID order, skipping products already published or queued. Saved previews are reused instead of calling the AI again.
- At the scheduled time, **01 Daily Publisher** claims only the queue head — one product per day — and publishes it (or logs a preview in DRY_RUN).
- When the product finishes, it leaves the queue and the preparer refills the free slot. A failed publish returns the product to the queue so it is retried; platforms that already succeeded are never re-posted.

## Local checks

```powershell
python scripts/test_schedule_queue.py     # offline: schedule, queue, duplicates, persistence, GitHub sync
python scripts/test_finalize_dry_run.py   # live stack: DRY_RUN daily run claims the queue head and advances
```
