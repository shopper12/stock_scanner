from __future__ import annotations

import os
import re
from pathlib import Path


def main() -> None:
    run_number = int(os.environ.get('GITHUB_RUN_NUMBER', '1'))
    version_code = 1000 + run_number
    version_name = f'1.0.{run_number}'

    _patch_gradle_version(version_code, version_name)
    _patch_manifest_permissions()

    print(f'Patched Android release metadata: versionCode={version_code}, versionName={version_name}')


def _patch_gradle_version(version_code: int, version_name: str) -> None:
    gradle = Path('app/build.gradle.kts')
    text = gradle.read_text(encoding='utf-8')
    text = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {version_code}', text)
    text = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{version_name}"', text)
    gradle.write_text(text, encoding='utf-8')


def _patch_manifest_permissions() -> None:
    path = Path('app/src/main/AndroidManifest.xml')
    if not path.exists():
        return
    text = path.read_text(encoding='utf-8')
    if 'android.permission.POST_NOTIFICATIONS' not in text:
        marker = '<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />'
        if marker in text:
            text = text.replace(marker, marker + '\n    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />')
        else:
            text = text.replace('<manifest xmlns:android="http://schemas.android.com/apk/res/android">', '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />')
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
