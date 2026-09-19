$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = Join-Path $root "data\backups\$stamp"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

if (Test-Path (Join-Path $root "data\db\tracking.sqlite")) {
  Copy-Item (Join-Path $root "data\db\tracking.sqlite") $dest
  Copy-Item (Join-Path $root "data\db\tracking.sqlite*") $dest -ErrorAction SilentlyContinue
}
if (Test-Path (Join-Path $root "data\previews")) {
  Copy-Item (Join-Path $root "data\previews") $dest -Recurse
}
if (Test-Path (Join-Path $root "data\logs")) {
  Copy-Item (Join-Path $root "data\logs") $dest -Recurse
}

docker compose -f (Join-Path $root "docker-compose.yml") exec -T n8n n8n export:workflow --all --output=/data/backups/$stamp/n8n-workflows.json
Write-Host "Backup written to $dest"
Write-Host "n8n volume n8n_data is still the source of truth for credentials. Keep N8N_ENCRYPTION_KEY unchanged."
