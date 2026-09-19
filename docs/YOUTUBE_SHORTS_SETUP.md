# YouTube Shorts setup (active phase)

In this automation, **YouTube always means YouTube Shorts**.  
Do **not** configure long-form YouTube uploads.

**Priority:** step 4 of [INTEGRATION_PRIORITY.md](INTEGRATION_PRIORITY.md) — do this now.  
Pinterest / Instagram / Facebook come after. Keep `DRY_RUN=true`. Do not publish. Do not paste secrets into chat.

## Already prepared in the project

- Shorts-only Gemini metadata (title, description, `#shorts` hashtags, tags)
- Workflow **07 YouTube Shorts Publisher** (YouTube Data API v3 upload)
- Drive videos treated as Shorts; image-only products skipped
- n8n credential slot **YouTube account** (`youTubeOAuth2Api`)
- `YOUTUBE_PRIVACY_STATUS=private`
- Upload path blocked while `DRY_RUN=true`

## Current step (do this now)

Open this page and sign in with the Google account that owns (or will own) the Shorts channel:

**https://console.cloud.google.com/apis/library/youtube.googleapis.com**

When that page is open, reply **ready**.

Next clicks (after you reply ready): Enable **YouTube Data API v3** → create OAuth client → paste Client ID/Secret only into n8n → **Credentials → YouTube account** (never into chat).

## Out of scope until later priority steps

- Pinterest OAuth
- Instagram / Facebook Meta tokens
- Setting `DRY_RUN=false`
- Any live Shorts upload
