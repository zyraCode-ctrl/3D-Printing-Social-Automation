# YouTube Shorts setup (active phase)

In this automation, **YouTube always means YouTube Shorts**. Never long-form uploads.

Keep `DRY_RUN=true`. Do **not** publish or upload. Do **not** paste Client ID, Client Secret, or tokens into chat.

## Project side (already configured)

| Piece | Detail |
| --- | --- |
| Publisher | `07 YouTube Shorts Publisher` — upload path blocked by DRY_RUN |
| Auth probe | `10 YouTube Shorts Auth Probe` — `channels.list?mine=true` only (no upload) |
| Readiness API | `GET /youtube/readiness` on tracking-api |
| Credential slot | n8n **YouTube account** (`youTubeOAuth2Api`) |
| Format | `youtube_format=shorts` |
| Privacy default | `YOUTUBE_PRIVACY_STATUS=private` |
| Redirect URI | `http://localhost:5678/rest/oauth2-credential/callback` |
| Env / Actions secret names | `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET` (optional prefills only) |
| Required scopes | `https://www.googleapis.com/auth/youtube.upload` · `https://www.googleapis.com/auth/youtube.readonly` |

Import can prefill Client ID/Secret into the n8n credential when those env vars are set. **Sign in with Google** still requires your browser in n8n.

## Exact browser actions (you must do these)

### Stop here first — do this one click now

1. Open: **https://console.cloud.google.com/apis/library/youtube.googleapis.com**
2. Sign in with the Google account that owns (or will own) the Shorts channel.
3. If the page shows **Enable**, click **Enable**.
4. Reply **ready** in chat when Enable is done (or if it already says **Manage** / API enabled).

Do not create OAuth clients yet — wait for the next single instruction after you reply.

### Later (Cursor will tell you one step at a time)

- OAuth consent screen
- Create **Web application** OAuth client
- Add redirect URI `http://localhost:5678/rest/oauth2-credential/callback`
- Paste Client ID/Secret **only** into n8n → Credentials → **YouTube account**
- Click **Sign in with Google**
- Run **10 YouTube Shorts Auth Probe** (read-only)

## What will not happen yet

- No Shorts upload
- No `DRY_RUN=false`
- No Pinterest / Meta setup in this phase
