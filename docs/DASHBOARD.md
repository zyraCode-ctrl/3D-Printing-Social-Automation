# Dashboard

The same page runs in two places:

- **Production**: the repository's GitHub Pages site, refreshed by every production run (`site/data.json`). See [PRODUCTION.md](PRODUCTION.md).
- **Local**: **http://localhost:8081/dashboard** while the Docker stack is running. It is served by the `tracking-api` container and bound to `127.0.0.1`, so it is only reachable from this PC. Local stays in DRY_RUN.

## What it shows

- **Status**: a prominent **DRY RUN / LIVE** bar (the Facebook Page ID posts go to), validation result, buffer and system health. Live mode can only be changed with the `PRODUCTION_LIVE` repository variable, never from the page.
- **Totals**: products, published, queue fill (x/8, minimum 6), platform successes / failures / skips.
- **Today's posts**: both slots with state (scheduled, publishing, published, partial, failed, missed), platform statuses, post IDs, attempts, timestamps and errors.
- **Next scheduled posts**: the next 6+ slots and the product whose content is ready for each.
- **Rolling queue**: the products with content already generated, in publishing order.
- **Per platform**: Instagram, Facebook Page, Pinterest, YouTube Shorts — success/failed/skipped counts and the latest post link.
- **Executions**: last/next run, AI provider used, retries and errors in the last 24 h.
- **Workflow runs** with a step-by-step detail panel, the **Products** table (status and platform post IDs per product), and **Recent activity**.

The page refreshes every 10 seconds. Tokens that appear in logs are redacted before they reach the browser.

## Schedule settings

Edit the daily times (default **6:00 PM and 10:00 PM**, up to 6 per day), add or remove times, and click **Save schedule**.

- The times are written to `config/schedule.json` — the single source of truth. Timezone: **Asia/Kolkata**. The buffer target follows automatically (posts per day × 4, minimum posts per day × 3).
- On the production (GitHub Pages) dashboard, saving commits the file through the GitHub API with a fine-grained token (*Contents: read & write* on this repo) that stays in your browser. The production gate uses the new times from its next 10-minute check.
- A newly added time that has already passed today starts tomorrow (it is recorded in `skip_slots`, so there is no surprise post right after saving). Slots already published are never published again.
- The file lives in the repo, so the times survive rebuilds and redeploys.

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

- **16 Content Queue Preparer** keeps up to 8 products prepared (Drive media + one AI call for all platforms + saved preview), always in Product ID order, skipping products already published or queued. Saved previews are reused instead of calling the AI again.
- At each scheduled time, **01 Daily Publisher** claims only the queue head — one product per slot — and publishes it (or logs a preview in DRY_RUN).
- When the product finishes, it leaves the queue and the preparer refills the free slot. A failed publish returns the product to the queue and is retried up to 3 times; platforms that already succeeded are never re-posted.

## Local checks

```powershell
python scripts/test_schedule_queue.py     # offline: schedule, queue, duplicates, persistence, GitHub sync
python scripts/test_finalize_dry_run.py   # live stack: DRY_RUN daily run claims the queue head and advances
```
