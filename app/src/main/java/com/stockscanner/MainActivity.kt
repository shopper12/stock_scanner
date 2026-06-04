package com.stockscanner

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val API_BASE_URL = "https://stock-scanner-api-5sk6.onrender.com"
private const val LATEST_URL = "$API_BASE_URL/api/latest"
private const val RULES_URL = "$API_BASE_URL/api/kr-short-rules"
private const val RUN_SCAN_URL = "$API_BASE_URL/api/run-scan"
private const val HISTORY_URL = "$API_BASE_URL/api/recommendation-history"
private const val PERFORMANCE_URL = "$API_BASE_URL/api/recommendation-performance"
private const val BACKTEST_URL = "$API_BASE_URL/api/kr-backtest"
private const val RUN_BACKTEST_URL = "$API_BASE_URL/api/run-backtest"
private const val STOCK_STRATEGY_URL = "$API_BASE_URL/api/kr-stock-strategy"
private const val UPDATE_PAGE_URL = "https://github.com/shopper12/stock_scanner/releases/tag/app-latest"

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { StockScannerScreen() } }
    }
}

@Composable
private fun StockScannerScreen() {
    val context = LocalContext.current
    var loading by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var backtesting by remember { mutableStateOf(false) }
    var searching by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var snapshot by remember { mutableStateOf<StockSnapshot?>(null) }
    var rules by remember { mutableStateOf<KrShortRules?>(null) }
    var history by remember { mutableStateOf<RecommendationHistory?>(null) }
    var performance by remember { mutableStateOf<RecommendationPerformance?>(null) }
    var backtest by remember { mutableStateOf<KrBacktestReport?>(null) }
    var stockQuery by remember { mutableStateOf("") }
    var stockStrategy by remember { mutableStateOf<KrStockStrategy?>(null) }
    var showHistory by remember { mutableStateOf(false) }
    var editKey by remember { mutableStateOf(readServerEditKey(context)) }
    val scope = rememberCoroutineScope()

    fun busy(): Boolean = loading || saving || backtesting || searching

    fun persistEditKey(value: String) {
        saveServerEditKey(context, value)
        editKey = readServerEditKey(context)
        message = if (editKey.isBlank()) "서버 편집키가 비어 있습니다. 그래도 스캔은 실행할 수 있습니다." else "서버 편집키를 이 기기에 저장했습니다."
    }

    fun clearEditKey() {
        clearServerEditKey(context)
        editKey = ""
        message = "서버 편집키를 삭제했습니다. 그래도 스캔은 실행할 수 있습니다."
    }

    fun openUpdatePage() {
        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(UPDATE_PAGE_URL))) }
            .onFailure { message = "브라우저를 열 수 없습니다: $UPDATE_PAGE_URL" }
    }

    suspend fun refresh() {
        loading = true
        error = null
        message = null
        runCatching {
            snapshot = fetchSnapshotOrNull()
            rules = fetchRulesOrNull() ?: rules ?: defaultRules()
            history = fetchHistoryOrEmpty()
            performance = fetchPerformanceOrNull()
            backtest = fetchBacktestOrNull()
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        loading = false
    }

    suspend fun saveRulesAndScan() {
        saving = true
        error = null
        message = null
        runCatching {
            val key = editKey.trim()
            val current = rules
            if (current != null && key.isNotBlank()) {
                runCatching { rules = postRules(current, key) }
                    .onFailure { message = "조건 저장 실패. 기존 조건으로 스캔합니다: ${compactError(it)}" }
            }
            val scanResult = runScan(key)
            snapshot = fetchSnapshotOrNull()
            rules = fetchRulesOrNull() ?: rules ?: defaultRules()
            history = fetchHistoryOrEmpty()
            performance = fetchPerformanceOrNull()
            message = "재스캔 완료: KR 후보 ${scanResult.krShortCount}개"
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        saving = false
    }

    suspend fun runBacktestNow() {
        val key = editKey.trim()
        if (key.isBlank()) {
            error = "서버 편집키를 저장해야 백테스트를 실행할 수 있습니다."
            return
        }
        backtesting = true
        error = null
        message = null
        runCatching {
            backtest = runBacktest(key)
            message = "백테스트 완료: ${backtest?.bestSummary?.trades ?: 0}건 / 채택=${backtest?.accepted}"
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        backtesting = false
    }

    suspend fun searchStockStrategy() {
        val query = stockQuery.trim()
        if (query.isBlank()) {
            error = "종목명 또는 종목코드를 입력하세요. 예: 삼성전자 또는 005930"
            return
        }
        searching = true
        error = null
        message = null
        runCatching {
            stockStrategy = fetchStockStrategy(query, editKey.trim())
            val s = stockStrategy
            message = if (s == null) "종목 분석 결과가 없습니다." else "종목 분석 완료: ${displayStockName(s.name, s.code)}(${s.code}) ${s.action}"
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        searching = false
    }

    LaunchedEffect(Unit) { refresh() }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        item { Text("Stock Scanner", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { scope.launch { refresh() } }, enabled = !busy()) { Text(if (loading) "Loading" else "Refresh") }
                    Button(onClick = { scope.launch { saveRulesAndScan() } }, enabled = !busy()) { Text(if (saving) "Scanning" else "조건 저장+스캔") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { scope.launch { runBacktestNow() } }, enabled = !busy()) { Text(if (backtesting) "검증 중" else "백테스트") }
                    Button(onClick = { showHistory = !showHistory }) { Text(if (showHistory) "현재 후보" else "추천 이력") }
                    Button(onClick = { openUpdatePage() }) { Text("업데이트/APK") }
                }
            }
        }
        item { InfoCard("Refresh는 서버의 최신 결과만 읽습니다. 종목 후보가 비어 있으면 '조건 저장+스캔'을 눌러 서버 재스캔을 실행하세요. 편집키가 없어도 스캔은 시도합니다.") }
        if (error != null) item { InfoCard("API error: ${error ?: ""}") }
        if (message != null) item { InfoCard(message ?: "") }
        if (showHistory) {
            item { PerformanceSummaryCard(performance) }
            item { HistorySummary(history) }
            val items = history?.items.orEmpty()
            if (items.isEmpty()) {
                item { InfoCard("저장된 추천 이력이 없습니다. 조건 저장+스캔 실행 후 누적됩니다.") }
            } else {
                items(items) { item -> HistoryCard(item) }
            }
        } else {
            item {
                RulesEditor(
                    rules = rules,
                    editKey = editKey,
                    onEditKeyChange = { editKey = it },
                    onPersistEditKey = { persistEditKey(editKey) },
                    onClearEditKey = { clearEditKey() },
                    onRulesChange = { rules = it }
                )
            }
            item { StockLookupCard(stockQuery, searching, { stockQuery = it }, { scope.launch { searchStockStrategy() } }) }
            if (stockStrategy != null) item { StockStrategyCard(stockStrategy!!) }
            item { BacktestSummaryCard(backtest) }
            val data = snapshot
            item {
                if (data == null) {
                    InfoCard(if (loading) "Loading latest scan." else "No scan data loaded. 조건 저장+스캔을 눌러 새 후보를 생성하세요.")
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Scan: ${data.createdAtKst} / mode=${data.mode}")
                        Text("Quote: ${data.quoteOk}/${data.total} (${formatPercent(data.quoteOkRate)})")
                    }
                }
            }
            if (data != null) item { SectorSummaryCard(data.sectors) }
            if (data != null && data.stocks.isEmpty()) {
                item { InfoCard("No KR short candidates. 조건이 너무 엄격하거나 서버 스캔 결과가 비어 있습니다.") }
            } else if (data != null) {
                items(data.stocks) { stock -> StockCard(stock) }
            }
        }
    }
}

@Composable
private fun PerformanceSummaryCard(performance: RecommendationPerformance?) {
    val summary = performance?.summary
    if (summary == null) {
        InfoCard("추천 성과: 아직 생성된 성과 리포트가 없습니다.")
        return
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("추천 성과 요약", fontWeight = FontWeight.Bold)
            Text("생성: ${performance.createdAtKst}")
            Text("누적 ${summary.totalRecommendations}개 / 계산 가능 ${summary.measurableCount}개")
            Text("평균 ${formatSignedPercent(summary.avgPnlPct)} / 중앙값 ${formatSignedPercent(summary.medianPnlPct)} / 승률 ${formatPercent(summary.winRate)}")
            Text("손절 ${formatPercent(summary.hitStopRate)} / 목표1 ${formatPercent(summary.hitTarget1Rate)} / 목표2 ${formatPercent(summary.hitTarget2Rate)}")
            if (summary.bestSetup.isNotBlank() || summary.worstSetup.isNotBlank()) Text("setup 최고 ${summary.bestSetup.ifBlank { "-" }} / 최악 ${summary.worstSetup.ifBlank { "-" }}")
        }
    }
}

@Composable
private fun StockLookupCard(query: String, searching: Boolean, onQuery: (String) -> Unit, onSearch: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("종목 직접 검색", fontWeight = FontWeight.Bold)
            Text("종목명 또는 6자리 코드를 입력하면 해당 종목만 별도 매매전략을 계산합니다.", style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(
                value = query,
                onValueChange = onQuery,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("예: 삼성전자 / 005930") },
                singleLine = true
            )
            Button(onClick = onSearch, enabled = !searching) { Text(if (searching) "분석 중" else "종목 분석") }
        }
    }
}

@Composable
private fun StockStrategyCard(strategy: KrStockStrategy) {
    val name = displayStockName(strategy.name, strategy.code)
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("$name(${strategy.code}) | ${strategy.sector}/${strategy.setup}", fontWeight = FontWeight.Bold)
            Text("판단: ${strategy.action} / 점수 ${formatNumber(strategy.score)} 기준 ${formatNumber(strategy.threshold)}")
            Text("이유: ${strategy.actionReason}")
            Text("현재가 ${formatPrice(strategy.currentPrice)} (${strategy.priceBasis}) / ${strategy.priceTimestamp}")
            Text("진입 ${formatPrice(strategy.entry)} / 손절 ${formatPrice(strategy.stopLoss)} / 위험 ${formatNumber(strategy.riskPct)}%")
            Text("목표 ${formatPrice(strategy.target1)} → ${formatPrice(strategy.target2)} / 포지션 ${formatPrice(strategy.positionSizeKrw)}원")
            Text("지표: RSI ${formatNumber(strategy.rsi14)} / MA20 괴리 ${formatSignedPercent(strategy.gapMa20Pct)} / 20일 모멘텀 ${formatSignedPercent(strategy.momentum20dPct)}")
            Text("근거: ${strategy.reason}")
            Text("무효화: ${strategy.failureCondition}")
        }
    }
}

@Composable
private fun BacktestSummaryCard(report: KrBacktestReport?) {
    if (report == null) {
        InfoCard("백테스트: 아직 실행된 리포트가 없습니다. 백테스트 버튼으로 최근 수개월 전략 성과를 생성하세요.")
        return
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("백테스트 성과", fontWeight = FontWeight.Bold)
            Text("생성: ${report.createdAtKst} / 룰채택: ${if (report.accepted) "예" else "아니오"} / 개선점수 ${formatNumber(report.improvement)}")
            Text("기준: 거래 ${report.baseSummary.trades}건 / 평균 ${formatSignedPercent(report.baseSummary.avgReturnPct)} / 승률 ${formatPercent(report.baseSummary.winRate)} / PF ${formatNumber(report.baseSummary.profitFactor)}")
            Text("최선: 거래 ${report.bestSummary.trades}건 / 평균 ${formatSignedPercent(report.bestSummary.avgReturnPct)} / 승률 ${formatPercent(report.bestSummary.winRate)} / PF ${formatNumber(report.bestSummary.profitFactor)}")
            Text("손절률 ${formatPercent(report.bestSummary.stopRate)} / 목표도달 ${formatPercent(report.bestSummary.targetRate)}", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun SectorSummaryCard(sectors: List<KrSectorSnapshot>) {
    if (sectors.isEmpty()) {
        InfoCard("선정 섹터 요약: 스캔 후 표시됩니다.")
        return
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("선정 섹터 요약", fontWeight = FontWeight.Bold)
            Text("섹터는 참고용입니다. 현재 추천 정렬은 순수 score 기준입니다.", style = MaterialTheme.typography.bodySmall)
            sectors.take(5).forEach { s ->
                val rankText = s.sectorRank?.takeIf { it > 0 }?.let { "${it}위 " } ?: ""
                val strengthText = if (s.sectorStrengthScore > 0.0) " / 강도 ${formatNumber(s.sectorStrengthScore)}" else ""
                val rotationText = if (s.marketRotationScore > 0.0) " / 회전 ${formatNumber(s.marketRotationScore)}" else ""
                Text("$rankText${s.sector}: ${s.selectedCount}개 / 대표 ${s.topStock}(${s.topStockCode}) / 최고점수 ${formatNumber(s.topScore)}$strengthText$rotationText")
            }
        }
    }
}

@Composable
private fun HistorySummary(history: RecommendationHistory?) {
    val items = history?.items.orEmpty()
    val valid = items.filter { it.pnlPct != null }
    val avg = valid.mapNotNull { it.pnlPct }.average().takeIf { !it.isNaN() }
    val win = valid.count { (it.pnlPct ?: 0.0) > 0.0 }
    InfoCard(
        "추천 이력/손익\n" +
            "업데이트: ${history?.updatedAtKst ?: "-"}\n" +
            "저장 종목: ${items.size}개 / 손익 계산 가능: ${valid.size}개\n" +
            "평균 수익률: ${avg?.let { formatSignedPercent(it) } ?: "-"} / 승률: ${if (valid.isNotEmpty()) formatPercent(win.toDouble() / valid.size) else "-"}"
    )
}

@Composable
private fun HistoryCard(item: RecommendationItem) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val name = displayStockName(item.name, item.code)
            Text("$name(${item.code}) | ${item.sector}/${item.strategyType}", fontWeight = FontWeight.Bold)
            Text("추천일 ${item.scanDate} / 보유 ${item.holdingDays}일 / 상태 ${statusLabel(item.status)}")
            Text("점수 ${formatNumber(item.scoreAtRecommendation)} / 추천가 ${formatPrice(item.entry)} / 현재가 ${formatPrice(item.latestPrice)}")
            Text("손익 ${formatSignedPrice(item.pnlKrwPerShare)} / ${item.pnlPct?.let { formatSignedPercent(it) } ?: "-"}")
            Text("목표 ${formatPrice(item.target1)} → ${formatPrice(item.target2)} / 손절 ${formatPrice(item.stopLoss)}")
            if (item.status == "hit_stop") Text("경고: 손절가 도달")
            if (item.status == "hit_target1" || item.status == "hit_target2") Text("목표 도달: ${statusLabel(item.status)}")
            if (item.statusDetail.isNotBlank()) Text("상태근거: ${item.statusDetail}", style = MaterialTheme.typography.bodySmall)
            Text("근거: ${item.reason}")
        }
    }
}

@Composable
private fun RulesEditor(
    rules: KrShortRules?,
    editKey: String,
    onEditKeyChange: (String) -> Unit,
    onPersistEditKey: () -> Unit,
    onClearEditKey: () -> Unit,
    onRulesChange: (KrShortRules) -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("한국 단기 종목 검색 조건", fontWeight = FontWeight.Bold)
            Text("편집키는 조건 저장용입니다. 스캔 자체는 편집키가 없어도 실행됩니다.")
            OutlinedTextField(
                value = editKey,
                onValueChange = onEditKeyChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("서버 편집키 선택 입력") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPersistEditKey) { Text("편집키 저장") }
                Button(onClick = onClearEditKey) { Text("편집키 삭제") }
            }
            Text(if (editKey.isBlank()) "편집키 없음: 조건 저장은 건너뛰고 스캔만 실행합니다." else "편집키 저장됨: 조건 저장+스캔 가능")
            val current = rules
            if (current == null) {
                Text("조건 API 미로딩 상태입니다. 그래도 조건 저장+스캔 버튼으로 서버 스캔은 실행됩니다.")
                return@Column
            }
            RuleNumberField("최소 후보 점수", "score_threshold", current.scoreThreshold, "이 점수보다 낮으면 후보 제외. 높이면 엄격, 낮추면 후보 증가.") { onRulesChange(current.copy(scoreThreshold = it)) }
            RuleNumberField("최소 손절폭 %", "min_risk_pct", current.minRiskPct, "진입가 대비 최소 손절폭. 너무 낮으면 노이즈 손절 증가.") { onRulesChange(current.copy(minRiskPct = it)) }
            RuleNumberField("최대 손절폭 %", "max_risk_pct", current.maxRiskPct, "진입가 대비 최대 허용 손절폭. 높이면 위험 큰 종목도 통과.") { onRulesChange(current.copy(maxRiskPct = it)) }
            RuleNumberField("최대 진입 괴리율 %", "max_entry_gap_pct", current.maxEntryGapPct, "돌파 진입가가 현재가보다 이 이상 높으면 제외.") { onRulesChange(current.copy(maxEntryGapPct = it)) }
            RuleNumberField("MA20 과열 한도 %", "max_gap_ma20_pct", current.maxGapMa20Pct, "현재가가 MA20보다 과도하게 높으면 점수 패널티.") { onRulesChange(current.copy(maxGapMa20Pct = it)) }
            RuleNumberField("급등 검증 기준 %", "surge_threshold_pct", current.surgeThresholdPct, "백테스트에서 급등으로 볼 기준 수익률.") { onRulesChange(current.copy(surgeThresholdPct = it)) }
            RuleNumberField("기본 보유일", "hold_days", current.holdDays.toDouble(), "단기 전략 검증 및 보유 기준 일수.") { onRulesChange(current.copy(holdDays = it.toInt())) }
            Text("현재 버전: ${current.version}")
        }
    }
}

@Composable
private fun RuleNumberField(labelKo: String, key: String, value: Double, help: String, onValue: (Double) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        OutlinedTextField(value = trimNumber(value), onValueChange = { text -> text.toDoubleOrNull()?.let(onValue) }, modifier = Modifier.fillMaxWidth(), label = { Text("$labelKo ($key)") }, singleLine = true)
        Text(help, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun StockCard(stock: KrShortStock) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val name = displayStockName(stock.name, stock.code)
            Text("$name(${stock.code}) | ${stock.sector}/${stock.strategyType}", fontWeight = FontWeight.Bold)
            Text("Score ${formatNumber(stock.score)} / Risk ${formatNumber(stock.riskPct)}%")
            Text("Now ${formatPrice(stock.currentPrice)} (${stock.priceBasis}, ${stock.quoteSource})")
            Text("Time ${stock.priceTimestamp}")
            Text("Entry ${formatPrice(stock.entry)} / Stop ${formatPrice(stock.stopLoss)}")
            Text("Target ${formatPrice(stock.target1)} → ${formatPrice(stock.target2)}")
            Text("Reason: ${stock.reason}")
            Text("Invalidation: ${stock.failureCondition}")
        }
    }
}

@Composable
private fun InfoCard(text: String) {
    Card(modifier = Modifier.fillMaxWidth()) { Text(text, modifier = Modifier.padding(12.dp)) }
}

private suspend fun fetchSnapshotOrNull(): StockSnapshot? = withContext(Dispatchers.IO) { runCatching { parseSnapshot(JSONObject(httpJson("GET", LATEST_URL, null, null))) }.getOrNull() }
private suspend fun fetchRulesOrNull(): KrShortRules? = withContext(Dispatchers.IO) { runCatching { parseRules(JSONObject(httpJson("GET", RULES_URL, null, null)).optJSONObject("rules") ?: JSONObject()) }.getOrNull() }
private suspend fun fetchHistoryOrEmpty(): RecommendationHistory = withContext(Dispatchers.IO) { runCatching { parseHistory(JSONObject(httpJson("GET", HISTORY_URL, null, null))) }.getOrElse { RecommendationHistory("-", emptyList()) } }
private suspend fun fetchPerformanceOrNull(): RecommendationPerformance? = withContext(Dispatchers.IO) { runCatching { parsePerformance(JSONObject(httpJson("GET", PERFORMANCE_URL, null, null))) }.getOrNull() }
private suspend fun fetchBacktestOrNull(): KrBacktestReport? = withContext(Dispatchers.IO) { runCatching { parseBacktest(JSONObject(httpJson("GET", BACKTEST_URL, null, null))) }.getOrNull() }
private suspend fun postRules(rules: KrShortRules, editKey: String): KrShortRules = withContext(Dispatchers.IO) { parseRules(JSONObject(httpJson("POST", RULES_URL, rules.toJson().toString(), editKey)).optJSONObject("rules") ?: JSONObject()) }
private suspend fun runScan(editKey: String): RunScanResult = withContext(Dispatchers.IO) { RunScanResult(JSONObject(httpJson("POST", RUN_SCAN_URL, "{}", editKey)).optInt("kr_short_count", 0)) }
private suspend fun runBacktest(editKey: String): KrBacktestReport = withContext(Dispatchers.IO) { parseBacktest(JSONObject(httpJson("POST", RUN_BACKTEST_URL, "{\"max_symbols\":30,\"write\":false}", editKey))) }
private suspend fun fetchStockStrategy(query: String, editKey: String): KrStockStrategy = withContext(Dispatchers.IO) { parseStockStrategy(JSONObject(httpJson("POST", STOCK_STRATEGY_URL, JSONObject().put("query", query).toString(), editKey))) }

private fun httpJson(method: String, url: String, requestBody: String?, editKey: String?): String {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        requestMethod = method
        connectTimeout = 15000
        readTimeout = if (url == RUN_SCAN_URL || url == RUN_BACKTEST_URL || url == STOCK_STRATEGY_URL) 120000 else 15000
        setRequestProperty("Accept", "application/json")
        setRequestProperty("User-Agent", "StockScanner-Android")
        if (method == "POST") {
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (editKey?.isNotBlank() == true) setRequestProperty("X-Admin-Token", editKey)
        }
    }
    try {
        if (requestBody != null) connection.outputStream.use { it.write(requestBody.toByteArray(Charsets.UTF_8)) }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        if (code !in 200..299) error(compactHttpError(code, body))
        if (body.trimStart().startsWith("<")) error("서버가 JSON 대신 HTML을 반환했습니다. Render 배포/재시작 상태를 확인하세요.")
        return body
    } finally {
        connection.disconnect()
    }
}

private fun compactHttpError(code: Int, body: String): String {
    val trimmed = body.trim()
    if (trimmed.startsWith("<")) return "HTTP $code: Render 서버 오류 또는 배포 중입니다. 잠시 후 다시 시도하세요."
    return "HTTP $code: ${trimmed.take(300)}"
}

private fun compactError(error: Throwable): String = (error.message ?: error::class.java.simpleName).take(120)

private fun parseSnapshot(json: JSONObject): StockSnapshot {
    val quality = json.optJSONObject("data_quality") ?: JSONObject()
    val rows = json.optJSONArray("kr_short_stocks")
    val stocks = buildList {
        if (rows != null) for (i in 0 until rows.length()) rows.optJSONObject(i)?.let { item ->
            add(KrShortStock(item.optString("code", ""), item.optString("name", ""), item.optString("sector", "기타"), item.optString("strategy_type", ""), item.optDouble("current_price", 0.0), item.optString("price_basis", "unknown"), item.optString("price_timestamp", "unknown"), item.optString("quote_source", item.optString("data_source", "unknown")), item.optDouble("score", 0.0), item.optDouble("entry", 0.0), item.optDouble("stop_loss", 0.0), item.optDouble("target1", 0.0), item.optDouble("target2", 0.0), item.optDouble("risk_pct", 0.0), item.optString("reason", ""), item.optString("failure_condition", "")))
        }
    }
    return StockSnapshot(json.optString("created_at_kst", "-"), json.optString("mode", "unknown"), quality.optDouble("kr_short_quote_ok_rate", 0.0), quality.optInt("kr_short_quote_ok", 0), quality.optInt("kr_short_total", stocks.size), stocks, parseSectorSnapshot(json))
}

private fun parsePerformance(json: JSONObject): RecommendationPerformance {
    val summary = json.optJSONObject("summary") ?: JSONObject()
    val bySetup = summary.optJSONObject("by_strategy_type") ?: JSONObject()
    return RecommendationPerformance(
        json.optString("created_at_kst", "-"),
        RecommendationPerformanceSummary(
            summary.optInt("total_recommendations", 0),
            summary.optInt("measurable_count", 0),
            summary.optDouble("avg_pnl_pct", 0.0),
            summary.optDouble("median_pnl_pct", 0.0),
            summary.optDouble("win_rate", 0.0),
            summary.optDouble("hit_stop_rate", 0.0),
            summary.optDouble("hit_target1_rate", 0.0),
            summary.optDouble("hit_target2_rate", 0.0),
            bestSetupText(bySetup, true),
            bestSetupText(bySetup, false)
        )
    )
}

private fun bestSetupText(obj: JSONObject, best: Boolean): String {
    val names = obj.keys().asSequence().toList()
    if (names.isEmpty()) return ""
    val picked = names.map { name -> name to (obj.optJSONObject(name)?.optDouble("avg_pnl_pct", 0.0) ?: 0.0) }.let { rows -> if (best) rows.maxByOrNull { it.second } else rows.minByOrNull { it.second } }
    return picked?.let { "${it.first} ${formatSignedPercent(it.second)}" } ?: ""
}

private fun parseStockStrategy(json: JSONObject): KrStockStrategy {
    val metrics = json.optJSONObject("metrics") ?: JSONObject()
    return KrStockStrategy(json.optString("code", ""), json.optString("name", ""), json.optString("sector", "기타"), json.optString("action", "관망"), json.optString("action_reason", ""), json.optDouble("score", 0.0), json.optDouble("threshold", 0.0), json.optString("setup", ""), json.optDouble("current_price", 0.0), json.optString("price_basis", "unknown"), json.optString("price_timestamp", "unknown"), json.optDouble("entry", 0.0), json.optDouble("stop_loss", 0.0), json.optDouble("target1", 0.0), json.optDouble("target2", 0.0), json.optDouble("risk_pct", 0.0), json.optDouble("position_size_krw", 0.0), json.optString("reason", ""), json.optString("failure_condition", ""), metrics.optDouble("rsi14", 0.0), metrics.optDouble("gap_ma20_pct", 0.0), metrics.optDouble("momentum_20d_pct", 0.0))
}

private fun parseBacktest(json: JSONObject): KrBacktestReport = KrBacktestReport(json.optString("created_at_kst", "-"), json.optBoolean("accepted", false), json.optDouble("improvement", 0.0), parseBacktestSummary(json.optJSONObject("base_summary") ?: JSONObject()), parseBacktestSummary(json.optJSONObject("best_summary") ?: JSONObject()))
private fun parseBacktestSummary(json: JSONObject): KrBacktestSummary = KrBacktestSummary(json.optInt("trades", 0), json.optDouble("avg_return_pct", 0.0), json.optDouble("win_rate", 0.0), json.optDouble("profit_factor", 0.0), json.optDouble("stop_rate", 0.0), json.optDouble("target_rate", 0.0))

private fun parseSectorSnapshot(json: JSONObject): List<KrSectorSnapshot> {
    val rows = json.optJSONArray("kr_sector_snapshot")
    return buildList {
        if (rows != null) for (i in 0 until rows.length()) rows.optJSONObject(i)?.let { item ->
            add(KrSectorSnapshot(item.optString("sector", "기타"), if (item.has("sector_rank") && !item.isNull("sector_rank")) item.optInt("sector_rank") else null, item.optDouble("sector_strength_score", 0.0), item.optDouble("market_rotation_score", 0.0), item.optInt("selected_count", 0), item.optString("top_stock", ""), item.optString("top_stock_code", ""), item.optDouble("top_score", 0.0)))
        }
    }
}

private fun parseHistory(json: JSONObject): RecommendationHistory {
    val rows = json.optJSONArray("items")
    val items = buildList {
        if (rows != null) for (i in 0 until rows.length()) rows.optJSONObject(i)?.let { item ->
            add(RecommendationItem(item.optString("scan_date", ""), item.optString("recommended_at_kst", ""), item.optString("code", ""), item.optString("name", ""), item.optString("sector", "기타"), item.optString("strategy_type", ""), item.optDouble("entry", 0.0), item.optDouble("stop_loss", 0.0), item.optDouble("target1", 0.0), item.optDouble("target2", 0.0), item.optDouble("score_at_recommendation", 0.0), item.optDouble("latest_price", 0.0), item.optNullableDouble("pnl_pct"), item.optNullableDouble("pnl_krw_per_share"), item.optString("status", "open"), item.optString("status_detail", ""), item.optInt("holding_days", 0), item.optString("reason", "")))
        }
    }
    return RecommendationHistory(json.optString("updated_at_kst", "-"), items)
}

private fun JSONObject.optNullableDouble(key: String): Double? = if (has(key) && !isNull(key)) optDouble(key) else null

private fun parseRules(json: JSONObject): KrShortRules = KrShortRules(json.optInt("version", 1), json.optDouble("score_threshold", 55.0), json.optDouble("min_risk_pct", 1.5), json.optDouble("max_risk_pct", 12.0), json.optDouble("max_entry_gap_pct", 3.5), json.optDouble("max_gap_ma20_pct", 12.0), json.optDouble("surge_threshold_pct", 12.0), json.optInt("hold_days", 10))
private fun KrShortRules.toJson(): JSONObject = JSONObject().apply { put("rules", JSONObject().apply { put("score_threshold", scoreThreshold); put("min_risk_pct", minRiskPct); put("max_risk_pct", maxRiskPct); put("max_entry_gap_pct", maxEntryGapPct); put("max_gap_ma20_pct", maxGapMa20Pct); put("surge_threshold_pct", surgeThresholdPct); put("hold_days", holdDays) }) }
private fun defaultRules(): KrShortRules = KrShortRules(1, 55.0, 1.5, 12.0, 3.5, 12.0, 12.0, 10)

private data class StockSnapshot(val createdAtKst: String, val mode: String, val quoteOkRate: Double, val quoteOk: Int, val total: Int, val stocks: List<KrShortStock>, val sectors: List<KrSectorSnapshot>)
private data class KrSectorSnapshot(val sector: String, val sectorRank: Int?, val sectorStrengthScore: Double, val marketRotationScore: Double, val selectedCount: Int, val topStock: String, val topStockCode: String, val topScore: Double)
private data class KrStockStrategy(val code: String, val name: String, val sector: String, val action: String, val actionReason: String, val score: Double, val threshold: Double, val setup: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val positionSizeKrw: Double, val reason: String, val failureCondition: String, val rsi14: Double, val gapMa20Pct: Double, val momentum20dPct: Double)
private data class KrBacktestReport(val createdAtKst: String, val accepted: Boolean, val improvement: Double, val baseSummary: KrBacktestSummary, val bestSummary: KrBacktestSummary)
private data class KrBacktestSummary(val trades: Int, val avgReturnPct: Double, val winRate: Double, val profitFactor: Double, val stopRate: Double, val targetRate: Double)
private data class RecommendationPerformance(val createdAtKst: String, val summary: RecommendationPerformanceSummary)
private data class RecommendationPerformanceSummary(val totalRecommendations: Int, val measurableCount: Int, val avgPnlPct: Double, val medianPnlPct: Double, val winRate: Double, val hitStopRate: Double, val hitTarget1Rate: Double, val hitTarget2Rate: Double, val bestSetup: String, val worstSetup: String)
private data class KrShortStock(val code: String, val name: String, val sector: String, val strategyType: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val quoteSource: String, val score: Double, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val reason: String, val failureCondition: String)
private data class KrShortRules(val version: Int, val scoreThreshold: Double, val minRiskPct: Double, val maxRiskPct: Double, val maxEntryGapPct: Double, val maxGapMa20Pct: Double, val surgeThresholdPct: Double, val holdDays: Int)
private data class RunScanResult(val krShortCount: Int)
private data class RecommendationHistory(val updatedAtKst: String, val items: List<RecommendationItem>)
private data class RecommendationItem(val scanDate: String, val recommendedAtKst: String, val code: String, val name: String, val sector: String, val strategyType: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val scoreAtRecommendation: Double, val latestPrice: Double, val pnlPct: Double?, val pnlKrwPerShare: Double?, val status: String, val statusDetail: String, val holdingDays: Int, val reason: String)

private fun statusLabel(status: String): String = when (status) { "hit_stop" -> "손절도달"; "hit_target1" -> "목표1도달"; "hit_target2" -> "목표2도달"; "time_exit_candidate" -> "시간청산검토"; else -> "진행중" }
private fun formatPrice(value: Double): String = String.format("%,.0f", value)
private fun formatNumber(value: Double): String = String.format("%.2f", value)
private fun formatPercent(value: Double): String = String.format("%.1f%%", value * 100)
private fun formatSignedPercent(value: Double): String = String.format("%+.2f%%", value)
private fun formatSignedPrice(value: Double?): String = value?.let { String.format("%+,.0f원/주", it) } ?: "-"
private fun trimNumber(value: Double): String = if (value % 1.0 == 0.0) value.toInt().toString() else String.format("%.2f", value)
private fun displayStockName(name: String, code: String): String = name.trim().takeIf { it.isNotBlank() && it != code && it != code.trimStart('0') } ?: codeToName(code) ?: code
private fun codeToName(code: String): String? = when (code.zfill6()) {
    "005930" -> "삼성전자"
    "005935" -> "삼성전자우"
    "000660" -> "SK하이닉스"
    "005380" -> "현대차"
    "000270" -> "기아"
    "003550" -> "LG"
    "066570" -> "LG전자"
    "051910" -> "LG화학"
    "373220" -> "LG에너지솔루션"
    "035420" -> "NAVER"
    "035720" -> "카카오"
    "005490" -> "POSCO홀딩스"
    "207940" -> "삼성바이오로직스"
    "068270" -> "셀트리온"
    "012450" -> "한화에어로스페이스"
    "034020" -> "두산에너빌리티"
    "329180" -> "HD현대중공업"
    "042660" -> "한화오션"
    "010140" -> "삼성중공업"
    "096770" -> "SK이노베이션"
    "402340" -> "SK스퀘어"
    "017670" -> "SK텔레콤"
    "030200" -> "KT"
    "105560" -> "KB금융"
    "055550" -> "신한지주"
    "086790" -> "하나금융지주"
    "316140" -> "우리금융지주"
    "006400" -> "삼성SDI"
    "247540" -> "에코프로비엠"
    "086520" -> "에코프로"
    "196170" -> "알테오젠"
    "141080" -> "리가켐바이오"
    "042700" -> "한미반도체"
    else -> null
}
private fun String.zfill6(): String = trim().padStart(6, '0')
