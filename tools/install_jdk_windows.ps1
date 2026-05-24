$ErrorActionPreference = 'Stop'

Write-Host 'Checking Java...' -ForegroundColor Cyan
$java = Get-Command java -ErrorAction SilentlyContinue
if ($java) {
    Write-Host "java already exists: $($java.Source)" -ForegroundColor Green
    java -version
    Write-Host ''
    Write-Host 'Now run:'
    Write-Host 'powershell -ExecutionPolicy Bypass -File .\tools\setup_java_home.ps1'
    exit 0
}

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Write-Host 'winget was not found.' -ForegroundColor Red
    Write-Host 'Install JDK 17 manually, then run tools/setup_java_home.ps1.'
    Write-Host 'Recommended package: Eclipse Temurin JDK 17'
    exit 1
}

Write-Host 'Installing Eclipse Temurin JDK 17 with winget...' -ForegroundColor Cyan
winget install --exact --id EclipseAdoptium.Temurin.17.JDK --accept-package-agreements --accept-source-agreements

Write-Host ''
Write-Host 'JDK install command finished.' -ForegroundColor Green
Write-Host 'Run this next:'
Write-Host 'powershell -ExecutionPolicy Bypass -File .\tools\setup_java_home.ps1'
Write-Host ''
Write-Host 'Then close PowerShell, open a new PowerShell window, and run:'
Write-Host 'cd C:\codetest\stock_scanner'
Write-Host '.\gradlew.bat :app:assembleDebug'
