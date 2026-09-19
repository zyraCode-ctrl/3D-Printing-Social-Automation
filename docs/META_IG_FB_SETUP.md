# Meta Instagram + Facebook setup (this phase only)

Keep `DRY_RUN=true`. Do **not** publish yet.

**Priority:** Instagram and Facebook are steps 6–7 in [INTEGRATION_PRIORITY.md](INTEGRATION_PRIORITY.md). Finish **YouTube Shorts OAuth** (step 4) and **Pinterest** (step 5) before this Meta phase unless Meta access arrives earlier and you deliberately pause those.

Pinterest is a separate later step. YouTube Shorts is the current active social OAuth phase.

## What Cursor already prepared

- Official Graph publishers for **04 Instagram** and **05 Facebook**
- Instagram two-step flow: create media container → `media_publish`
- Facebook Page `photos` / `videos` edges
- n8n credential slot **Facebook Graph account** (`facebookGraphApi`)
- Tracking endpoint `GET /meta/readiness` (shows which IDs are set; never prints tokens)
- Manual workflow **09 Meta Auth Probe** (tests token/Page/IG IDs; never posts)
- Env placeholders: `FACEBOOK_PAGE_ID`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `META_GRAPH_VERSION=v22.0`

## Credentials / IDs you will fill in locally (never paste into chat)

| Item | Where it goes |
|------|----------------|
| Meta App ID | Meta Developer dashboard only (used to create tokens) |
| Meta App Secret | Meta Developer dashboard only |
| **Page access token** | n8n → Credentials → **Facebook Graph account** → Access Token |
| **Facebook Page ID** | `.env` → `FACEBOOK_PAGE_ID=` |
| **Instagram Business Account ID** (`ig-user-id`) | `.env` → `INSTAGRAM_BUSINESS_ACCOUNT_ID=` |

Required Page token scopes (Facebook Login path):

- `pages_show_list`
- `pages_read_engagement`
- `pages_manage_posts`
- `instagram_basic`
- `instagram_content_publish`

## Click-by-click: Meta Developer

1. Open [https://developers.facebook.com/apps/](https://developers.facebook.com/apps/) and sign in with the Facebook account that manages your shop Page.
2. Click **Create App**.
3. Choose **Other** → **Next** (or Business if shown), then app type **Business**.
4. Enter an app name (e.g. `3D Print Social`) → create the app.
5. In the app dashboard, add **Facebook Login for Business** (or Facebook Login).
6. Add **Instagram** product if offered (Instagram Graph / API with Facebook Login).
7. Ensure you have:
   - A **Facebook Page** for the store
   - An **Instagram Professional** account (Business or Creator)
   - The Instagram account **linked** to that Facebook Page (Meta Business Suite / Page settings → Linked accounts / Instagram)
8. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
9. Select your app → **Generate Access Token** / Get Token → **Get Page Access Token**.
10. Select your Page and approve permissions listed above → **Allow** / **Continue**.
11. Copy the **Page access token** (long-lived preferred; exchange short-lived → long-lived if Meta shows that option).
12. In Graph Explorer, run:
    - `GET me/accounts?fields=id,name,instagram_business_account`
    - Note the Page `id` and `instagram_business_account.id`
13. Optionally confirm: `GET /{page-id}?fields=id,name,instagram_business_account`

## Click-by-click: local config (after Meta)

1. Open `.env` on this PC.
2. Set:
   - `FACEBOOK_PAGE_ID=<page id from step 12>`
   - `INSTAGRAM_BUSINESS_ACCOUNT_ID=<ig user id from step 12>`
   - Keep `DRY_RUN=true`
   - Keep `META_GRAPH_VERSION=v22.0`
3. Restart stack so config reloads:
   ```powershell
   docker compose up -d tracking-api
   python scripts/import_workflows.py
   ```
4. Open http://localhost:5678 → **Credentials** → **Facebook Graph account**.
5. Paste the **Page access token** into **Access Token** → **Save**.
6. Open workflow **09 Meta Auth Probe** → **Execute workflow**.
7. Confirm summary shows `graph_ok: true` and your Page/IG IDs.
8. Check http://127.0.0.1:8081/meta/readiness — both ID flags should be `true`, `dry_run: true`.

## Still blocked until you approve later

- Real Instagram/Facebook posts (requires `DRY_RUN=false` + your explicit approval)
- Public media URL for Meta to fetch files (Drive share or tunnel) — only needed for live publish
- Pinterest / YouTube integration

## Safety

Daily publisher still stops before social nodes while `DRY_RUN=true`. Duplicate protection remains via `/products/{id}/can-publish`.
