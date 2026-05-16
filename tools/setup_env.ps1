$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.env.shared')) {
    throw '.env.shared not found. Run git pull first.'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.shared' '.env'
    Write-Host '[setup] Created .env from .env.shared'
} else {
    Write-Host '[setup] .env already exists. Keeping local secrets.'
}

Write-Host '[setup] Edit .env and fill TELEGRAM_BOT_TOKEN if needed:'
Write-Host '        notepad .env'
