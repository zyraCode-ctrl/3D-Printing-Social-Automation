# Integration priority (exact order)

Keep `DRY_RUN=true` until the owner explicitly approves real publishing (step 9).

| # | Integration | Status |
| --- | --- | --- |
| 1 | Google Drive | **Done** — public folder list/download working |
| 2 | Gemini | **Done** — free-tier vision via Actions secret `GEMINI_API_KEY` |
| 3 | Content generation | **Done** — platform copy + Shorts metadata + tracking previews |
| 4 | YouTube Shorts API / OAuth | **Done** — OAuth connected; DRY_RUN probe + publisher skip verified — [YOUTUBE_SHORTS_SETUP.md](YOUTUBE_SHORTS_SETUP.md) |
| 5 | **Pinterest API / OAuth** | **Active now** — official API v5 scaffolding ready; developer app click required — [PINTEREST_SETUP.md](PINTEREST_SETUP.md) |
| 6 | Instagram Meta API | After Meta developer access is available |
| 7 | Facebook Meta API | After Instagram |
| 8 | Final full-system DRY_RUN | After platforms above are credentialed (still no live posts) |
| 9 | Real publishing | **Only** after explicit owner approval (`DRY_RUN=false`) |

## Rules

- Do **not** skip ahead to Meta while Pinterest OAuth is unfinished.
- Do **not** set `DRY_RUN=false` without explicit approval.
- Do **not** paste App ID, App Secret, Client IDs, Client Secrets, or access tokens into chat — only into n8n Credentials or GitHub Secrets UI.
- In this project, **YouTube always means YouTube Shorts** (never long-form).
- Pinterest creates **image Pins only**; video products are skipped.
