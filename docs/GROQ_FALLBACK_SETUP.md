# Groq AI fallback (after Gemini)

Gemini stays the primary AI. Groq is used **only** when every Gemini model
(primary + built-in Gemini fallbacks) fails, for example a 503 "service unavailable".

- Same system prompt, same platform prompts, same JSON schema as Gemini.
- **One** Groq call returns content for all 4 platforms (Instagram, Facebook, Pinterest, YouTube Shorts).
- Same image / video frame is sent (base64, max ~4 MB — `prepare-vision` already downsizes).
- Output is validated exactly like Gemini output; missing platform blocks still fail the run.
- `DRY_RUN`, duplicate protection, publishing and tracking are unchanged.
- The preview (`data/previews/<id>.json`) records `ai_provider_used` (`gemini` or `groq`),
  `ai_model_used`, and `ai_fallback_reason` (the Gemini error that triggered Groq).

## Settings (`.env`, not secret)

| Variable | Default | Meaning |
|---|---|---|
| `AI_FALLBACK_PROVIDER` | `groq` | `groq` enables the fallback, `none` disables it |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Groq vision model with JSON mode |

After changing them: `docker compose up -d tracking-api`.

## GROQ_API_KEY (secret)

Never paste the key into chat, docs, code, or commits.

1. Open <https://console.groq.com/keys> → **Create API Key** → name it `zyra-n8n` → copy it.
2. Choose **one** way to store it:

   **A. n8n UI (recommended locally)**
   1. <http://localhost:5678> → **Credentials** → **Groq account** (type *Header Auth*;
      created by `python scripts/import_workflows.py`).
   2. **Name:** `Authorization`
   3. **Value:** `Bearer ` followed by your key (one space after `Bearer`).
   4. **Save**.

   **B. Environment variable (local `.env` or CI)**
   - Local: add `GROQ_API_KEY=<key>` to `.env` (git-ignored), then run
     `python scripts/import_workflows.py`. The script fills the Groq account credential
     and never prints the key.
   - GitHub Actions: repo → **Settings → Secrets and variables → Actions → New repository secret**
     → name `GROQ_API_KEY`. The daily dry-run workflow passes it to the import step.

3. Keep `DRY_RUN=true`. Nothing is published by adding the key.

## Verify (DRY_RUN only)

- Normal run: preview shows `"ai_provider_used": "gemini"`.
- When Gemini is down: preview shows `"ai_provider_used": "groq"` and an `ai_fallback_reason`.
- If both fail, the run stops with `Gemini failed (...) and Groq fallback failed: ...` —
  no copy is invented and nothing is published.
