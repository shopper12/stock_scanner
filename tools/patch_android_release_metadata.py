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
    _patch_main_activity()

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


def _patch_main_activity() -> None:
    path = Path('app/src/main/java/com/stockscanner/MainActivity.kt')
    if not path.exists():
        return
    text = path.read_text(encoding='utf-8')

    text = _add_import(text, 'import androidx.compose.material3.AlertDialog')
    text = _add_import(text, 'import androidx.compose.material3.TextButton')

    text = _replace_once(text,
        'private const val UPDATE_PAGE_URL = "https://github.com/shopper12/stock_scanner/releases/tag/app-latest"',
        'private const val UPDATE_PAGE_URL = "https://github.com/shopper12/stock_scanner/releases/tag/app-latest"\nprivate const val STOCK_CHART_URL = "$API_BASE_URL/api/kr-stock-chart"'
    )

    text = _replace_once(text,
        'var editKey by remember { mutableStateOf(readServerEditKey(context)) }\n    val scope = rememberCoroutineScope()',
        'var editKey by remember { mutableStateOf(readServerEditKey(context)) }\n    var updateInfo by remember { mutableStateOf<AppUpdateInfo?>(null) }\n    var showUpdateDialog by remember { mutableStateOf(false) }\n    val scope = rememberCoroutineScope()'
    )

    text = _replace_once(text,
        'fun openUpdatePage() {\n        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(UPDATE_PAGE_URL))) }\n            .onFailure { message = "브라우저를 열 수 없습니다: $UPDATE_PAGE_URL" }\n    }',
        'fun openUpdatePage() {\n        downloadAndInstallLatestApk(context) { status -> message = status }\n    }'
    )

    text = _replace_once(text,
        'val scanResult = runScan(key)\n            snapshot = fetchSnapshotOrNull()',
        'val scanResult = runScan(key)\n            snapshot = scanResult.snapshot ?: fetchSnapshotOrNull()'
    )
    text = _replace_once(text,
        'private suspend fun runScan(editKey: String): RunScanResult = withContext(Dispatchers.IO) { RunScanResult(JSONObject(httpJson("POST", RUN_SCAN_URL, "{}", editKey)).optInt("kr_short_count", 0)) }',
        '''private suspend fun runScan(editKey: String): RunScanResult = withContext(Dispatchers.IO) {
    val json = JSONObject(httpJson("POST", RUN_SCAN_URL, "{}", editKey))
    val snapshot = if (json.has("kr_short_stocks")) parseSnapshot(json) else null
    val count = json.optInt("kr_short_count", json.optJSONArray("kr_short_stocks")?.length() ?: 0)
    RunScanResult(count, snapshot)
}'''
    )
    text = _replace_once(text, 'private data class RunScanResult(val krShortCount: Int)', 'private data class RunScanResult(val krShortCount: Int, val snapshot: StockSnapshot?)')

    text = _replace_once(text,
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

    text = _replace_once(text,
        'item { InfoCard("Refresh는 서버의 최신 결과만 읽습니다. 종목 후보가 비어 있으면 \'조건 저장+스캔\'을 눌러 서버 재스캔을 실행하세요. 편집키가 없어도 스캔은 시도합니다.") }',
        '''item {
            MenuOverviewCard(
                onRefresh = { scope.launch { refresh() } },
                onScan = { scope.launch { saveRulesAndScan() } },
                onBacktest = { scope.launch { runBacktestNow() } },
                onSearch = { scope.launch { searchStockStrategy() } },
                onToggleHistory = { showHistory = !showHistory },
                onUpdate = { openUpdatePage() },
                busy = busy()
            )
        }
        item { InfoCard("첫 화면에서 전체 메뉴를 노출합니다: 새로고침, 스캔, 백테스트, 종목검색, 현재후보, 추천이력, 성과, 조건, 업데이트, 차트.") }'''
    )

    text = _replace_once(text,
        'Text("종목명 또는 6자리 코드를 입력하면 해당 종목만 별도 매매전략을 계산합니다.", style = MaterialTheme.typography.bodySmall)',
        'Text("한국 종목명/6자리 코드 또는 미국 티커·한글명·ETF명을 입력하면 별도 매매전략을 계산합니다. 예: 삼성전자, 005930, NVDA, 엔비디아, SOXL, 나스닥3배", style = MaterialTheme.typography.bodySmall)'
    )
    text = _replace_once(text, 'label = { Text("예: 삼성전자 / 005930") }', 'label = { Text("예: 삼성전자 / 005930 / NVDA / 엔비디아 / SOXL") }')

    text = _replace_once(text,
        'private fun StockStrategyCard(strategy: KrStockStrategy) {\n    val name = displayStockName(strategy.name, strategy.code)',
        'private fun StockStrategyCard(strategy: KrStockStrategy) {\n    val context = LocalContext.current\n    val name = displayStockName(strategy.name, strategy.code)'
    )
    text = _replace_once(text,
        'Text("무효화: ${strategy.failureCondition}")',
        'Text("무효화: ${strategy.failureCondition}")\n            Text("추천 제외 진단: ${strategy.scannerExclusionDiagnosis}", style = MaterialTheme.typography.bodySmall)\n            Button(onClick = { context.startActivity(Intent(context, ChartActivity::class.java).putExtra("code", strategy.code)) }) { Text("차트 보기") }'
    )
    text = _replace_once(text,
        'private fun StockCard(stock: KrShortStock) {\n    Card(',
        'private fun StockCard(stock: KrShortStock) {\n    val context = LocalContext.current\n    Card('
    )
    text = _replace_once(text,
        'Text("Invalidation: ${stock.failureCondition}")',
        'Text("Invalidation: ${stock.failureCondition}")\n            Button(onClick = { context.startActivity(Intent(context, ChartActivity::class.java).putExtra("code", stock.code)) }) { Text("차트 보기") }'
    )

    text = _replace_once(text,
        'metrics.optDouble("momentum_20d_pct", 0.0))',
        'metrics.optDouble("momentum_20d_pct", 0.0), json.optJSONObject("scanner_exclusion_diagnosis")?.optString("reason") ?: "-")'
    )
    text = _replace_once(text,
        'private data class KrStockStrategy(val code: String, val name: String, val sector: String, val action: String, val actionReason: String, val score: Double, val threshold: Double, val setup: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val positionSizeKrw: Double, val reason: String, val failureCondition: String, val rsi14: Double, val gapMa20Pct: Double, val momentum20dPct: Double)',
        'private data class KrStockStrategy(val code: String, val name: String, val sector: String, val action: String, val actionReason: String, val score: Double, val threshold: Double, val setup: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val positionSizeKrw: Double, val reason: String, val failureCondition: String, val rsi14: Double, val gapMa20Pct: Double, val momentum20dPct: Double, val scannerExclusionDiagnosis: String)'
    )

    if 'private fun MenuOverviewCard(' not in text:
        marker = '@Composable\nprivate fun PerformanceSummaryCard(performance: RecommendationPerformance?) {'
        menu = '''@Composable
private fun MenuOverviewCard(
    onRefresh: () -> Unit,
    onScan: () -> Unit,
    onBacktest: () -> Unit,
    onSearch: () -> Unit,
    onToggleHistory: () -> Unit,
    onUpdate: () -> Unit,
    busy: Boolean
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("전체 메뉴", fontWeight = FontWeight.Bold)
            Text("모든 주요 기능을 첫 화면에서 바로 실행합니다.", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onRefresh, enabled = !busy) { Text("새로고침") }
                Button(onClick = onScan, enabled = !busy) { Text("스캔") }
                Button(onClick = onBacktest, enabled = !busy) { Text("백테스트") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onSearch, enabled = !busy) { Text("종목검색") }
                Button(onClick = onToggleHistory) { Text("현재/이력") }
                Button(onClick = onUpdate) { Text("APK 업데이트") }
            }
            Text("화면 아래에서 조건, 성과, 섹터, 현재 후보, 추천 이력, 차트를 모두 확인할 수 있습니다.", style = MaterialTheme.typography.bodySmall)
        }
    }
}

'''
        if marker in text:
            text = text.replace(marker, menu + marker, 1)

    path.write_text(text, encoding='utf-8')
    print('Patched MainActivity: full first-screen menu, direct scan payload, update popup, chart buttons, US/KR search help, exclusion diagnosis')


def _replace_once(text: str, old: str, new: str) -> str:
    if old not in text or new in text:
        return text
    return text.replace(old, new, 1)


def _add_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    marker = 'import androidx.compose.material3.Button\n'
    if marker in text:
        return text.replace(marker, import_line + '\n' + marker)
    return text


if __name__ == '__main__':
    main()
