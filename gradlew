#!/usr/bin/env sh
set -eu

GRADLE_VERSION="8.6"
DIST_URL="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
DIST_DIR="${HOME}/.gradle/wrapper/dists/gradle-${GRADLE_VERSION}-bin/manual"
GRADLE_HOME="${DIST_DIR}/gradle-${GRADLE_VERSION}"
GRADLE_BIN="${GRADLE_HOME}/bin/gradle"
GRADLE_ZIP="${DIST_DIR}/gradle-${GRADLE_VERSION}-bin.zip"

if [ ! -x "$GRADLE_BIN" ]; then
  echo "Gradle ${GRADLE_VERSION} was not found locally."
  echo "Downloading Gradle ${GRADLE_VERSION} from ${DIST_URL}"
  mkdir -p "$DIST_DIR"
  if [ ! -f "$GRADLE_ZIP" ]; then
    if command -v curl >/dev/null 2>&1; then
      curl -L "$DIST_URL" -o "$GRADLE_ZIP"
    elif command -v wget >/dev/null 2>&1; then
      wget "$DIST_URL" -O "$GRADLE_ZIP"
    else
      echo "Neither curl nor wget is installed." >&2
      exit 1
    fi
  fi
  unzip -o "$GRADLE_ZIP" -d "$DIST_DIR" >/dev/null
fi

exec "$GRADLE_BIN" "$@"
