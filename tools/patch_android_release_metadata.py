from __future__ import annotations

import os
import re
from pathlib import Path


def main() -> None:
    run_number = int(os.environ.get('GITHUB_RUN_NUMBER', '1'))
    version_code = 1000 + run_number
    version_name = f'1.0.{run_number}'

    gradle = Path('app/build.gradle.kts')
    text = gradle.read_text(encoding='utf-8')
    text = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {version_code}', text)
    text = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{version_name}"', text)
    gradle.write_text(text, encoding='utf-8')

    print(f'Patched Android release metadata: versionCode={version_code}, versionName={version_name}')


if __name__ == '__main__':
    main()
