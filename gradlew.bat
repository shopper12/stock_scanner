@ECHO OFF
SETLOCAL

SET GRADLE_VERSION=8.6
SET DIST_URL=https://services.gradle.org/distributions/gradle-%GRADLE_VERSION%-bin.zip
SET DIST_DIR=%USERPROFILE%\.gradle\wrapper\dists\gradle-%GRADLE_VERSION%-bin\manual
SET GRADLE_HOME=%DIST_DIR%\gradle-%GRADLE_VERSION%
SET GRADLE_BIN=%GRADLE_HOME%\bin\gradle.bat
SET GRADLE_ZIP=%DIST_DIR%\gradle-%GRADLE_VERSION%-bin.zip

IF NOT EXIST "%GRADLE_BIN%" (
  ECHO Gradle %GRADLE_VERSION% was not found locally.
  ECHO Downloading Gradle %GRADLE_VERSION% from %DIST_URL%
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $distDir='%DIST_DIR%'; $zip='%GRADLE_ZIP%'; New-Item -ItemType Directory -Force -Path $distDir | Out-Null; if (!(Test-Path $zip)) { Invoke-WebRequest -Uri '%DIST_URL%' -OutFile $zip }; Expand-Archive -Path $zip -DestinationPath $distDir -Force"
  IF %ERRORLEVEL% NEQ 0 (
    ECHO Failed to download or extract Gradle.
    ECHO Check internet/proxy access to https://services.gradle.org/distributions/gradle-%GRADLE_VERSION%-bin.zip
    EXIT /B %ERRORLEVEL%
  )
)

CALL "%GRADLE_BIN%" %*
