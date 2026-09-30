#!/usr/bin/env bash
# Persist production state between GitHub Actions runs on the production-state branch.
#
#   restore        decrypt state/state.tar.gz.enc into data/db, data/previews and .secrets/
#   save [label]   snapshot the tracking DB (sqlite backup API), generated content and the n8n
#                  credentials (with any refreshed OAuth tokens), encrypt, force-push the branch
#
# The archive is AES-256 encrypted with the STATE_KEY secret. state/slots.json and state/queue.json
# are plaintext schedule bookkeeping (no secrets) so the lightweight gate job can read them.
set -euo pipefail

cmd=${1:?usage: production_state.sh restore|save [label]}
: "${STATE_KEY:?Missing secret STATE_KEY}"
ENC=(-aes-256-cbc -pbkdf2 -iter 200000 -md sha256)

case "$cmd" in
  restore)
    mkdir -p state data/db data/media data/previews data/logs data/backups .secrets
    git fetch --depth=1 origin production-state || { echo "::error::production-state branch missing; seed it first (docs/PRODUCTION.md)"; exit 1; }
    git show FETCH_HEAD:state/state.tar.gz.enc | openssl enc -d "${ENC[@]}" -pass env:STATE_KEY | tar -xzf -
    for f in slots queue; do git show "FETCH_HEAD:state/$f.json" > "state/$f.json" 2>/dev/null || rm -f "state/$f.json"; done
    test -s .secrets/n8n-credentials.json || { echo "::error::state has no n8n credentials"; exit 1; }
    echo "Restored production state: $(ls data/previews | wc -l) saved content files"
    ;;
  save)
    : "${GH_TOKEN:?GH_TOKEN required to push state}"
    snap=$(mktemp -d)
    mkdir -p "$snap/data/db" "$snap/.secrets"
    sudo python3 - "$snap/data/db/tracking.sqlite" <<'PY'
import sqlite3, sys
src = sqlite3.connect("data/db/tracking.sqlite")
dst = sqlite3.connect(sys.argv[1])
src.backup(dst)
dst.close()
src.close()
PY
    sudo cp -r data/previews "$snap/data/previews"
    if docker ps --format '{{.Names}}' | grep -qx n8n; then
      docker exec -u node n8n n8n export:credentials --all --decrypted --output=/tmp/creds.json >/dev/null
      docker cp n8n:/tmp/creds.json .secrets/n8n-credentials.json
      docker exec -u root n8n rm -f /tmp/creds.json
    fi
    cp .secrets/n8n-credentials.json "$snap/.secrets/"
    out=$(mktemp -d)
    mkdir -p "$out/state"
    sudo tar -C "$snap" -czf - data .secrets | openssl enc -e "${ENC[@]}" -salt -pass env:STATE_KEY -out "$out/state/state.tar.gz.enc"
    sudo rm -rf "$snap"
    for f in slots queue; do [ -f "state/$f.json" ] && cp "state/$f.json" "$out/state/"; done
    cat > "$out/README.md" <<'EOF'
Production state for `.github/workflows/production.yml` (force-pushed by every production run).

- `state/state.tar.gz.enc` — tracking DB, generated content and n8n credentials, AES-256 encrypted with the `STATE_KEY` secret.
- `state/slots.json`, `state/queue.json` — plaintext schedule bookkeeping read by the gate job (no secrets).
EOF
    cd "$out"
    git init -q -b production-state
    git add -A
    git -c user.name="zyra-production-bot" -c user.email="actions@users.noreply.github.com" commit -qm "state: ${2:-update} $(date -u +%FT%TZ)"
    for attempt in 1 2 3; do
      if git push -qf "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" production-state; then
        echo "Saved production state (${2:-update})"
        exit 0
      fi
      sleep $((attempt * 5))
    done
    echo "::error::could not push production state"
    exit 1
    ;;
  *)
    echo "usage: production_state.sh restore|save [label]" >&2
    exit 2
    ;;
esac
