$ErrorActionPreference = 'Stop'

$candidates = @(
    "$env:ProgramFiles\Android\Android Studio\jbr",
    "$env:ProgramFiles\Android\Android Studio\jre",
    "$env:ProgramFiles\Java\jdk-21",
    "$env:ProgramFiles\Java\jdk-17",
    "$env:ProgramFiles\Eclipse Adoptium\jdk-21*",
    "$env:ProgramFiles\Eclipse Adoptium\jdk-17*",
    "$env:LOCALAPPDATA\Programs\Eclipse Adoptium\jdk-21*",
    "$env:LOCALAPPDATA\Programs\Eclipse Adoptium\jdk-17*"
)

$javaHome = $null
foreach ($candidate in $candidates) {
    $matches = Get-ChildItem -Path $candidate -Directory -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if (-not $matches -and (Test-Path $candidate)) {
        $matches = @(Get-Item $candidate)
    }
    foreach ($match in $matches) {
        $javaExe = Join-Path $match.FullName 'bin\java.exe'
        if (Test-Path $javaExe) {
            $javaHome = $match.FullName
            break
        }
    }
    if ($javaHome) { break }
}

if (-not $javaHome) {
    Write-Host 'JDK was not found automatically.' -ForegroundColor Red
    Write-Host 'Install Android Studio or Temurin JDK 17/21, then run this script again.'
    Write-Host 'Temurin: https://adoptium.net/temurin/releases/'
    exit 1
}

[Environment]::SetEnvironmentVariable('JAVA_HOME', $javaHome, 'User')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$javaBin = '%JAVA_HOME%\bin'
if ($userPath -notlike "*$javaBin*") {
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$javaBin", 'User')
}

$env:JAVA_HOME = $javaHome
$env:Path = "$javaHome\bin;$env:Path"

Write-Host "JAVA_HOME set to: $javaHome" -ForegroundColor Green
& "$javaHome\bin\java.exe" -version
Write-Host ''
Write-Host 'Close this PowerShell window, open a new one, then run:'
Write-Host 'cd C:\codetest\stock_scanner'
Write-Host '.\gradlew.bat :app:assembleDebug'
