# GitHub Actions

Two workflows run on free GitHub-hosted runners:

| Workflow | When | What |
| --- | --- | --- |
| **Production publisher** (`production.yml`) | every 10 minutes (gate) + manual | Live publishing at the dashboard times, buffer refill, validation, dashboard on GitHub Pages. See [PRODUCTION.md](PRODUCTION.md). |
| **Dry-run verification** (`daily-dry-run.yml`) | every push that touches the stack + manual | Fresh stack with `DRY_RUN=true`: offline tests, workflow validation, one dry-run publish, dashboard/schedule/queue endpoints. Never publishes and never touches production state. |

## Secrets for the verification workflow

| Secret | Purpose |
| --- | --- |
| `N8N_ENCRYPTION_KEY` | Long random string (≥32 chars) for n8n |
| `N8N_OWNER_PASSWORD` | n8n owner password for headless import |
| `N8N_OWNER_EMAIL` | Optional (default `admin@localhost.local`) |
| `GOOGLE_DRIVE_FOLDER_ID` | Optional (defaults to the public folder in `config/settings.json`) |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | AI keys for the dry-run |
| `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET` | Optional — prefill the n8n credential shell |

Production uses the n8n credentials stored (encrypted) in its own state instead; see [PRODUCTION.md](PRODUCTION.md).
