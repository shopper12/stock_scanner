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

    _patch_main_activity()

    print(f'Patched Android release metadata: versionCode={version_code}, versionName={version_name}')


def _patch_main_activity() -> None:
    path = Path('app/src/main/java/com/stockscanner/MainActivity.kt')
    text = path.read_text(encoding='utf-8')

    text = text.replace(
        'val scanResult = runScan(key)\n            snapshot = fetchSnapshotOrNull()',
        'val scanResult = runScan(key)\n            snapshot = scanResult.snapshot ?: fetchSnapshotOrNull()'
    )
    text = text.replace(
        'private suspend fun runScan(editKey: String): RunScanResult = withContext(Dispatchers.IO) { RunScanResult(JSONObject(httpJson("POST", RUN_SCAN_URL, "{}", editKey)).optInt("kr_short_count", 0)) }',
        '''private suspend fun runScan(editKey: String): RunScanResult = withContext(Dispatchers.IO) {
    val json = JSONObject(httpJson("POST", RUN_SCAN_URL, "{}", editKey))
    val snapshot = if (json.has("kr_short_stocks")) parseSnapshot(json) else null
    val count = json.optInt("kr_short_count", json.optJSONArray("kr_short_stocks")?.length() ?: 0)
    RunScanResult(count, snapshot)
}'''
    )
    text = text.replace(
        'private data class RunScanResult(val krShortCount: Int)',
        'private data class RunScanResult(val krShortCount: Int, val snapshot: StockSnapshot?)'
    )
    path.write_text(text, encoding='utf-8')
    print('Patched Android MainActivity: run-scan payload is displayed directly')


if __name__ == '__main__':
    main()
