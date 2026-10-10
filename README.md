Production state for `.github/workflows/production.yml` (force-pushed by every production run).

- `state/state.tar.gz.enc` — tracking DB, generated content and n8n credentials, AES-256 encrypted with the `STATE_KEY` secret.
- `state/slots.json`, `state/queue.json` — plaintext schedule bookkeeping read by the gate job (no secrets).
