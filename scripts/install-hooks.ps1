$ErrorActionPreference = "Stop"

git config core.hooksPath .githooks
Write-Host "Git hooks path configured: .githooks"
