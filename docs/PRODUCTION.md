# Production (live publishing on GitHub Actions)

Production runs entirely on free GitHub-hosted runners via `.github/workflows/production.yml`. Your PC and local n8n do not need to be running.

## Schedule

- Daily times live in `config/schedule.json` (default **18:00 and 22:00 Asia/Kolkata**, first day set by `start_date`). Edit them on the dashboard; the file is the single source of truth.
- A gate job decides on every tick: when one of today's times has passed and that slot has not been handled, it starts a publish run.
- Ticks come from two independent sources:
  - **Waiter job (primary)**: every run starts one `waiter` job (only one exists at a time). It sleeps until 90 s, 35 min and 80 min after each slot and dispatches a `tick` run; if the next slot is more than ~5.5 h away it sleeps the maximum and re-arms. The chain sustains itself without cron, so a 6:00 PM post normally goes out at about 6:02–6:10 PM.
  - **Cron (backup)**: `*/10` plus fixed ticks 1–107 minutes after 18:00 and 22:00 IST. GitHub throttles scheduled runs heavily (sometimes hours apart), so cron alone is not relied on. Any cron tick also restarts the waiter chain if it ever stopped.
- A slot missed by more than 3 hours (for example a GitHub outage) is not posted late; the product waits for the next slot.
- Each slot publishes exactly one product (the lowest Product ID in the queue). Retries for a failed platform happen at most 3 times per slot; platforms that already succeeded are never re-posted. A product that still fails after 3 attempts is set aside (visible on the dashboard) so the queue keeps moving.

## Content buffer

- The queue target is `posts per day × (buffer days + 1)` = **8** with 2 posts/day and a 3-day buffer, so at least **6** upcoming posts always have content ready.
- One AI call per product (Gemini, Groq fallback) generates every platform's content. After each publish the buffer refills automatically (and at most hourly when it is below target).

## Safety

- Nothing is published unless the repository variable **`PRODUCTION_LIVE`** is `true`.
- Every run validates first: Page token acts as Page `1294584743741605` (never a personal profile), the Instagram account is linked to that Page, duplicate prevention and queue integrity. Publishing is blocked if any of these fail. YouTube OAuth, the Pinterest board, the Groq fallback and the schedule are also checked and reported.
- The public dashboard data is scrubbed of anything token-shaped.

## State

The tracking DB, generated content and n8n credentials (including refreshed OAuth tokens) are stored on the **`production-state`** branch as `state/state.tar.gz.enc`, AES-256 encrypted with the `STATE_KEY` secret. It is saved right after each publish and at the end of every run.

## Settings

| Where | Name | Value |
| --- | --- | --- |
| Secret | `STATE_KEY` | Random key that encrypts production state |
| Secret | `N8N_ENCRYPTION_KEY`, `N8N_OWNER_PASSWORD`, `N8N_OWNER_EMAIL` | n8n runtime |
| Variable | `PRODUCTION_LIVE` | `true` to publish, anything else = DRY_RUN |
| Variable | `FACEBOOK_PAGE_ID` | `1294584743741605` |
| Variable | `INSTAGRAM_BUSINESS_ACCOUNT_ID` | `17841443595297445` |
| Variable | `PINTEREST_BOARD_ID` | `1074601229777946521` |
| Variable | `YOUTUBE_PRIVACY_STATUS` | `private`, `unlisted` or `public` |

## Operations

- **Dashboard**: the repository's GitHub Pages site. To change the times there, paste a fine-grained token with *Contents: read & write* on this repository (kept only in your browser).
- **Manual run**: Actions → *Production publisher* → *Run workflow* → `validate-only` (all checks plus **17 Publish Path Check**: uploads the queue head to Instagram (container reaches `FINISHED`) and to a Facebook Page Reel session, but never calls `media_publish` / finish and records nothing), `prepare-only` (refill the buffer), `auto`, or `tick` (behaves like a cron tick; also restarts the waiter chain). Manual runs never publish outside a scheduled slot.
- **Pause publishing**: set `PRODUCTION_LIVE` to `false`.
- **Re-seed state** (only if the branch is lost): export the local tracking DB, previews and n8n credentials into the same archive format as `scripts/production_state.sh save` and push it to `production-state`.

## Known limits

- Google OAuth consent screens in *Testing* mode issue refresh tokens that expire after 7 days. Publish the consent screen to *In production* so YouTube keeps working.
- Pinterest only publishes image Pins; video products skip Pinterest.
- GitHub disables scheduled workflows after 60 days without repository activity; production state commits count as activity.
