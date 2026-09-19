param(
  [Parameter(Mandatory = $true)]
  [string]$BackupDir
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $BackupDir)) {
  throw "Backup folder not found: $BackupDir"
}
New-Item -ItemType Directory -Force -Path (Join-Path $root "data\db") | Out-Null
Copy-Item (Join-Path $BackupDir "tracking.sqlite") (Join-Path $root "data\db\tracking.sqlite") -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $BackupDir "previews")) {
  Copy-Item (Join-Path $BackupDir "previews\*") (Join-Path $root "data\previews") -Recurse -Force
}
Write-Host "Restored tracking database/previews from $BackupDir"
Write-Host "Restart with: docker compose up -d"
Write-Host "n8n credentials live in the n8n_data volume and are encrypted with N8N_ENCRYPTION_KEY from .env"
