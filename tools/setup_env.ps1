$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.env.example')) {
    throw '.env.example not found. Run git pull first.'
}

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host '[setup] Created .env from .env.example'
} else {
    Write-Host '[setup] .env already exists. Keeping local secrets.'
}

Write-Host '[setup] Edit .env and fill private API keys if needed:'
Write-Host '        notepad .env'
