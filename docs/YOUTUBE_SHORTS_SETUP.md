# YouTube Shorts setup (this project)

In this automation, **YouTube always means YouTube Shorts**.  
Do **not** configure or expect long-form YouTube uploads.

Keep `DRY_RUN=true`. Do not publish yet. Do not paste client secrets or tokens into chat.

## What Cursor prepared

- Gemini prompts generate **Shorts-only** metadata (short title, concise description, lowercase hashtags including `#shorts`, tags/keywords)
- Workflow **07 YouTube Shorts Publisher** (official YouTube Data API v3 upload path for Shorts)
- Uses existing Google Drive product media (`local_path` under `/data/media`); videos are treated as Shorts
- Image-only products are skipped
- n8n credential slot **YouTube account** (`youTubeOAuth2Api`)
- Privacy default remains `YOUTUBE_PRIVACY_STATUS=private`
- Instagram / Facebook / Pinterest left unchanged in this update
- `DRY_RUN=true` blocks upload — nothing is published yet

## Exact first page to open

Open Google Cloud Console for APIs:

**https://console.cloud.google.com/apis/library/youtube.googleapis.com**

Sign in with the Google account that owns (or will own) the YouTube channel you will use for Shorts.

When that page is open, reply **“ready”** and you will get the next click (Enable YouTube Data API v3).

## Later (not yet)

After the API is enabled you will create an OAuth client and paste Client ID/Secret only into n8n → **Credentials → YouTube account**. Credentials stay local — never in chat.
