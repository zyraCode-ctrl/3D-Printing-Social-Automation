# Pinterest setup (active phase)

Official **Pinterest API v5** only. Image Pins only — video products are skipped on purpose.

Keep `DRY_RUN=true`. Do **not** create Pins or publish. Do **not** paste App ID, App Secret, or tokens into chat.

## Project side (already configured)

| Piece | Detail |
| --- | --- |
| Publisher | `06 Pinterest Publisher` — Pin create path blocked by DRY_RUN |
| Auth probe | `11 Pinterest Auth Probe` — `user_account` + `boards` list only (no Pin create) |
| Readiness API | `GET /pinterest/readiness` on tracking-api |
| Credential slot | n8n **Pinterest account** (`oAuth2Api`) |
| Redirect URI | `http://localhost:5678/rest/oauth2-credential/callback` |
| Board id env | `PINTEREST_BOARD_ID` (set after OAuth lists your boards) |
| Optional env prefills | `PINTEREST_OAUTH_CLIENT_ID`, `PINTEREST_OAUTH_CLIENT_SECRET` |
| Required scopes | `user_accounts:read` · `boards:read` · `boards:write` · `pins:read` · `pins:write` |

Import can create the empty **Pinterest account** OAuth2 credential and attach it to the publisher + probe. **Connect my account** still requires your browser in n8n.

## Exact browser actions (you must do these)

### Stop here first — do this one click now

1. Open: **https://developers.pinterest.com/apps/**
2. Sign in with a **Pinterest business** account (personal accounts cannot register apps).
3. Accept **Developer Terms** if prompted.
4. If you see **Connect app**, click **Connect app** and submit the trial-access form.
5. Privacy Policy URL (after the website page is live): **https://zyrastudio3d.com/privacy-policy**
   - Page source is ready in `website-dropins/privacy-policy/` — deploy to the Vercel Next.js site first (see that folder’s `DEPLOY.md`). Do not paste this URL into Pinterest until the page returns HTTP 200.
6. Reply **ready** in chat when Connect app is submitted (or if an app already appears under My apps).

Do not add redirect URIs or paste secrets into n8n yet — wait for the next single instruction after you reply.

### Now — paste Anikaza App ID/Secret into n8n (browser only)

1. Open n8n → **Credentials** → **Pinterest account** (OAuth2 already set for Pinterest v5).
2. Confirm OAuth Redirect URL is `http://localhost:5678/rest/oauth2-credential/callback`.
3. Paste Anikaza **App ID** into **Client ID** and **App secret** into **Client Secret** (never into chat).
4. Click **Save**, then **Connect** and approve Pinterest OAuth.
5. Reply **ready** when Connect succeeds.

Keep `DRY_RUN=true`. Do not create Pins.

## What will not happen yet

- No Pin create
- No `DRY_RUN=false`
- No Meta / Instagram / Facebook setup in this phase
