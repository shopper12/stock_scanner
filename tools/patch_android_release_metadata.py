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

    _patch_manifest()
    _patch_main_activity()

    print(f'Patched Android release metadata: versionCode={version_code}, versionName={version_name}')


def _patch_manifest() -> None:
    path = Path('app/src/main/AndroidManifest.xml')
    text = path.read_text(encoding='utf-8')
    if 'android.permission.POST_NOTIFICATIONS' not in text:
        text = text.replace(
            '<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />',
            '<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />\n    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />'
        )
    path.write_text(text, encoding='utf-8')


def _patch_main_activity() -> None:
    path = Path('app/src/main/java/com/stockscanner/MainActivity.kt')
    text = path.read_text(encoding='utf-8')

    if 'import androidx.compose.material3.AlertDialog' not in text:
        text = text.replace('import androidx.compose.material3.Button\n', 'import androidx.compose.material3.AlertDialog\nimport androidx.compose.material3.Button\n')
    if 'import androidx.compose.material3.TextButton' not in text:
        text = text.replace('import androidx.compose.material3.Text\n', 'import androidx.compose.material3.Text\nimport androidx.compose.material3.TextButton\n')

    if 'STOCK_CHART_URL' not in text:
        text = text.replace(
            'private const val STOCK_STRATEGY_URL = "$API_BASE_URL/api/kr-stock-strategy"',
            'private const val STOCK_STRATEGY_URL = "$API_BASE_URL/api/kr-stock-strategy"\nprivate const val STOCK_CHART_URL = "$API_BASE_URL/api/kr-stock-chart"'
        )

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

    if 'scannerExclusionDiagnosis' not in text:
        text = text.replace(
            'Text("무효화: ${strategy.failureCondition}")',
            'Text("무효화: ${strategy.failureCondition}")\n            Text("추천 제외 진단: ${strategy.scannerExclusionDiagnosis}", style = MaterialTheme.typography.bodySmall)'
        )
        text = text.replace(
            'metrics.optDouble("momentum_20d_pct", 0.0))',
            'metrics.optDouble("momentum_20d_pct", 0.0), json.optJSONObject("scanner_exclusion_diagnosis")?.optString("reason") ?: "-")'
        )
        text = text.replace(
            'private data class KrStockStrategy(val code: String, val name: String, val sector: String, val action: String, val actionReason: String, val score: Double, val threshold: Double, val setup: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val positionSizeKrw: Double, val reason: String, val failureCondition: String, val rsi14: Double, val gapMa20Pct: Double, val momentum20dPct: Double)',
            'private data class KrStockStrategy(val code: String, val name: String, val sector: String, val action: String, val actionReason: String, val score: Double, val threshold: Double, val setup: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val positionSizeKrw: Double, val reason: String, val failureCondition: String, val rsi14: Double, val gapMa20Pct: Double, val momentum20dPct: Double, val scannerExclusionDiagnosis: String)'
        )

    if 'ChartActivity::class.java' not in text:
        text = text.replace(
            'private fun StockCard(stock: KrShortStock) {\n    Card(',
            'private fun StockCard(stock: KrShortStock) {\n    val context = LocalContext.current\n    Card('
        )
        text = text.replace(
            'Text("Invalidation: ${stock.failureCondition}")',
            'Text("Invalidation: ${stock.failureCondition}")\n            Button(onClick = { context.startActivity(Intent(context, ChartActivity::class.java).putExtra("code", stock.code)) }) { Text("차트 보기") }'
        )

    text = text.replace(
        'fun openUpdatePage() {\n        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(UPDATE_PAGE_URL))) }\n            .onFailure { message = "브라우저를 열 수 없습니다: $UPDATE_PAGE_URL" }\n    }',
        'fun openUpdatePage() {\n        downloadAndInstallLatestApk(context) { status -> message = status }\n    }'
    )
    text = text.replace(
        'Button(onClick = { openUpdatePage() }) { Text("업데이트/APK") }',
        'Button(onClick = { openUpdatePage() }) { Text("APK 바로 업데이트") }'
    )

    if 'var updateInfo by remember' not in text:
        text = text.replace(
            'var editKey by remember { mutableStateOf(readServerEditKey(context)) }\n    val scope = rememberCoroutineScope()',
            'var editKey by remember { mutableStateOf(readServerEditKey(context)) }\n    var updateInfo by remember { mutableStateOf<AppUpdateInfo?>(null) }\n    var showUpdateDialog by remember { mutableStateOf(false) }\n    val scope = rememberCoroutineScope()'
        )
        text = text.replace(
            'LaunchedEffect(Unit) { refresh() }',
            '''LaunchedEffect(Unit) {
        refresh()
        runCatching { checkForAppUpdate(context) }
            .onSuccess { info ->
                updateInfo = info
                if (info.updateAvailable) {
                    showUpdateDialog = true
                    notifyAppUpdateAvailable(context, info)
                }
            }
            .onFailure { message = "업데이트 확인 실패: ${it.message ?: it::class.java.simpleName}" }
    }
    if (showUpdateDialog && updateInfo?.updateAvailable == true) {
        AlertDialog(
            onDismissRequest = { showUpdateDialog = false },
            title = { Text("새 APK 업데이트 있음") },
            text = { Text(updateInfo?.message ?: "새 버전이 있습니다.") },
            confirmButton = { TextButton(onClick = { showUpdateDialog = false; openUpdatePage() }) { Text("다운로드") } },
            dismissButton = { TextButton(onClick = { showUpdateDialog = false }) { Text("나중에") } }
        )
    }'''
        )
    }

    path.write_text(text, encoding='utf-8')
    print('Patched Android MainActivity: update popup/notification, run-scan payload, chart button, and diagnosis display')


if __name__ == '__main__':
    main()
