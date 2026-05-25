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
private const val UPDATE_PAGE_URL = "https://github.com/shopper12/stock_scanner/actions/workflows/android-build.yml"

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
    var error by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var snapshot by remember { mutableStateOf<StockSnapshot?>(null) }
    var rules by remember { mutableStateOf<KrShortRules?>(null) }
    var history by remember { mutableStateOf<RecommendationHistory?>(null) }
    var showHistory by remember { mutableStateOf(false) }
    var editKey by remember { mutableStateOf(readServerEditKey(context)) }
    val scope = rememberCoroutineScope()

    fun persistEditKey(value: String) {
        saveServerEditKey(context, value)
        editKey = readServerEditKey(context)
        message = if (editKey.isBlank()) "서버 편집키가 비어 있습니다." else "서버 편집키를 이 기기에 저장했습니다."
    }

    fun clearEditKey() {
        clearServerEditKey(context)
        editKey = ""
        message = "서버 편집키를 삭제했습니다."
    }

    fun openUpdatePage() {
        runCatching {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(UPDATE_PAGE_URL)))
        }.onFailure {
            message = "브라우저를 열 수 없습니다: $UPDATE_PAGE_URL"
        }
    }

    suspend fun refresh() {
        loading = true
        error = null
        runCatching {
            snapshot = fetchSnapshot()
            rules = fetchRules()
            history = fetchHistory()
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        loading = false
    }

    suspend fun saveRules() {
        val current = rules ?: return
        val key = editKey.trim()
        if (key.isBlank()) {
            error = "서버 편집키를 한 번 입력하고 저장해야 조건 저장+스캔을 실행할 수 있습니다."
            return
        }
        saving = true
        error = null
        message = null
        runCatching {
            rules = postRules(current, key)
            val scanResult = runScan(key)
            snapshot = fetchSnapshot()
            history = fetchHistory()
            message = "조건 저장 및 재스캔 완료: KR 후보 ${scanResult.krShortCount}개"
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        saving = false
    }

    LaunchedEffect(Unit) { refresh() }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { Text("Stock Scanner", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { scope.launch { refresh() } }, enabled = !loading && !saving) { Text(if (loading) "Loading" else "Refresh") }
                    Button(onClick = { scope.launch { saveRules() } }, enabled = rules != null && !loading && !saving) { Text(if (saving) "Saving" else "조건 저장+스캔") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { showHistory = !showHistory }) { Text(if (showHistory) "현재 후보" else "추천 이력") }
                    Button(onClick = { openUpdatePage() }) { Text("업데이트/APK") }
                }
            }
        }
        item { InfoCard("업데이트 방식: GitHub 수정 후 Android Build가 자동 실행됩니다. '업데이트/APK' 버튼을 누르고 최신 성공 빌드의 stock-scanner-debug-apk를 내려받아 설치하세요.") }
        if (error != null) item { InfoCard("API error: $error") }
        if (message != null) item { InfoCard(message ?: "") }
        if (showHistory) {
            item { HistorySummary(history) }
            val items = history?.items.orEmpty()
            if (items.isEmpty()) {
                item { InfoCard("저장된 추천 이력이 없습니다. 조건 저장+스캔 또는 Smoke Scan 실행 후 누적됩니다.") }
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
                    onRulesChange = { rules = it },
                )
            }
            val data = snapshot
            item {
                if (data == null) {
                    InfoCard(if (loading) "Loading latest scan." else "No scan data loaded.")
                } else {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Scan: ${data.createdAtKst} / mode=${data.mode}")
                        Text("Quote: ${data.quoteOk}/${data.total} (${formatPercent(data.quoteOkRate)})")
                    }
                }
            }
            if (data != null && data.stocks.isEmpty()) {
                item { InfoCard("No KR short candidates.") }
            } else if (data != null) {
                items(data.stocks) { stock -> StockCard(stock) }
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
            Text("${item.name}(${item.code}) | ${item.sector}/${item.strategyType}", fontWeight = FontWeight.Bold)
            Text("추천일 ${item.scanDate} / 점수 ${formatNumber(item.scoreAtRecommendation)}")
            Text("추천가 ${formatPrice(item.entry)} / 현재가 ${formatPrice(item.latestPrice)}")
            Text("손익 ${formatSignedPrice(item.pnlKrwPerShare)} / ${item.pnlPct?.let { formatSignedPercent(it) } ?: "-"}")
            Text("목표 ${formatPrice(item.target1)} → ${formatPrice(item.target2)} / 손절 ${formatPrice(item.stopLoss)}")
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
    onRulesChange: (KrShortRules) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("한국 단기 종목 검색 조건", fontWeight = FontWeight.Bold)
            Text("서버 편집키는 한 번만 저장하면 됩니다. 이후에는 조건 저장+스캔 버튼만 누르면 됩니다.")
            OutlinedTextField(
                value = editKey,
                onValueChange = onEditKeyChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("서버 편집키 1회 입력") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPersistEditKey) { Text("편집키 저장") }
                Button(onClick = onClearEditKey) { Text("편집키 삭제") }
            }
            Text(if (editKey.isBlank()) "편집키 미저장: 조건 저장은 실패합니다." else "편집키 저장됨: 조건 저장+스캔 가능")
            if (rules == null) {
                Text("조건 로딩 중 또는 조건 API 미배포 상태")
                return@Column
            }
            RuleNumberField("최소 후보 점수", "score_threshold", rules.scoreThreshold, "이 점수보다 낮으면 후보 제외. 높이면 엄격, 낮추면 후보 증가.") { onRulesChange(rules.copy(scoreThreshold = it)) }
            RuleNumberField("최소 손절폭 %", "min_risk_pct", rules.minRiskPct, "진입가 대비 최소 손절폭. 너무 낮으면 노이즈 손절 증가.") { onRulesChange(rules.copy(minRiskPct = it)) }
            RuleNumberField("최대 손절폭 %", "max_risk_pct", rules.maxRiskPct, "진입가 대비 최대 허용 손절폭. 높이면 위험 큰 종목도 통과.") { onRulesChange(rules.copy(maxRiskPct = it)) }
            RuleNumberField("최대 진입 괴리율 %", "max_entry_gap_pct", rules.maxEntryGapPct, "돌파 진입가가 현재가보다 이 이상 높으면 제외.") { onRulesChange(rules.copy(maxEntryGapPct = it)) }
            RuleNumberField("MA20 과열 한도 %", "max_gap_ma20_pct", rules.maxGapMa20Pct, "현재가가 MA20보다 과도하게 높으면 점수 패널티.") { onRulesChange(rules.copy(maxGapMa20Pct = it)) }
            RuleNumberField("급등 검증 기준 %", "surge_threshold_pct", rules.surgeThresholdPct, "백테스트에서 급등으로 볼 기준 수익률.") { onRulesChange(rules.copy(surgeThresholdPct = it)) }
            RuleNumberField("기본 보유일", "hold_days", rules.holdDays.toDouble(), "단기 전략 검증 및 보유 기준 일수.") { onRulesChange(rules.copy(holdDays = it.toInt())) }
            Text("현재 버전: ${rules.version}")
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
            Text("${stock.name}(${stock.code}) | ${stock.sector}/${stock.strategyType}", fontWeight = FontWeight.Bold)
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

private suspend fun fetchSnapshot(): StockSnapshot = withContext(Dispatchers.IO) { parseSnapshot(JSONObject(httpJson("GET", LATEST_URL, null, null))) }
private suspend fun fetchRules(): KrShortRules = withContext(Dispatchers.IO) { parseRules(JSONObject(httpJson("GET", RULES_URL, null, null)).optJSONObject("rules") ?: JSONObject()) }
private suspend fun fetchHistory(): RecommendationHistory = withContext(Dispatchers.IO) { parseHistory(JSONObject(httpJson("GET", HISTORY_URL, null, null))) }
private suspend fun postRules(rules: KrShortRules, editKey: String): KrShortRules = withContext(Dispatchers.IO) { parseRules(JSONObject(httpJson("POST", RULES_URL, rules.toJson().toString(), editKey)).optJSONObject("rules") ?: JSONObject()) }
private suspend fun runScan(editKey: String): RunScanResult = withContext(Dispatchers.IO) { RunScanResult(JSONObject(httpJson("POST", RUN_SCAN_URL, "{}", editKey)).optInt("kr_short_count", 0)) }

private fun httpJson(method: String, url: String, requestBody: String?, editKey: String?): String {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        requestMethod = method
        connectTimeout = 15000
        readTimeout = if (url == RUN_SCAN_URL) 60000 else 15000
        setRequestProperty("Accept", "application/json")
        setRequestProperty("User-Agent", "StockScanner-Android")
        if (method == "POST") {
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (!editKey.isNullOrBlank()) setRequestProperty("X-Admin-Token", editKey)
        }
    }
    try {
        if (requestBody != null) connection.outputStream.use { it.write(requestBody.toByteArray(Charsets.UTF_8)) }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        if (code !in 200..299) error("HTTP $code: $body")
        return body
    } finally {
        connection.disconnect()
    }
}

private fun parseSnapshot(json: JSONObject): StockSnapshot {
    val quality = json.optJSONObject("data_quality") ?: JSONObject()
    val rows = json.optJSONArray("kr_short_stocks")
    val stocks = buildList {
        if (rows != null) for (i in 0 until rows.length()) rows.optJSONObject(i)?.let { item ->
            add(KrShortStock(item.optString("code", ""), item.optString("name", ""), item.optString("sector", "기타"), item.optString("strategy_type", ""), item.optDouble("current_price", 0.0), item.optString("price_basis", "unknown"), item.optString("price_timestamp", "unknown"), item.optString("quote_source", item.optString("data_source", "unknown")), item.optDouble("score", 0.0), item.optDouble("entry", 0.0), item.optDouble("stop_loss", 0.0), item.optDouble("target1", 0.0), item.optDouble("target2", 0.0), item.optDouble("risk_pct", 0.0), item.optString("reason", ""), item.optString("failure_condition", "")))
        }
    }
    return StockSnapshot(json.optString("created_at_kst", "-"), json.optString("mode", "unknown"), quality.optDouble("kr_short_quote_ok_rate", 0.0), quality.optInt("kr_short_quote_ok", 0), quality.optInt("kr_short_total", stocks.size), stocks)
}

private fun parseHistory(json: JSONObject): RecommendationHistory {
    val rows = json.optJSONArray("items")
    val items = buildList {
        if (rows != null) for (i in 0 until rows.length()) rows.optJSONObject(i)?.let { item ->
            add(RecommendationItem(item.optString("scan_date", ""), item.optString("recommended_at_kst", ""), item.optString("code", ""), item.optString("name", ""), item.optString("sector", "기타"), item.optString("strategy_type", ""), item.optDouble("entry", 0.0), item.optDouble("stop_loss", 0.0), item.optDouble("target1", 0.0), item.optDouble("target2", 0.0), item.optDouble("score_at_recommendation", 0.0), item.optDouble("latest_price", 0.0), item.optNullableDouble("pnl_pct"), item.optNullableDouble("pnl_krw_per_share"), item.optString("reason", "")))
        }
    }
    return RecommendationHistory(json.optString("updated_at_kst", "-"), items)
}

private fun JSONObject.optNullableDouble(key: String): Double? = if (has(key) && !isNull(key)) optDouble(key) else null

private fun parseRules(json: JSONObject): KrShortRules = KrShortRules(json.optInt("version", 1), json.optDouble("score_threshold", 62.0), json.optDouble("min_risk_pct", 1.5), json.optDouble("max_risk_pct", 12.0), json.optDouble("max_entry_gap_pct", 3.5), json.optDouble("max_gap_ma20_pct", 12.0), json.optDouble("surge_threshold_pct", 15.0), json.optInt("hold_days", 10))
private fun KrShortRules.toJson(): JSONObject = JSONObject().apply { put("rules", JSONObject().apply { put("score_threshold", scoreThreshold); put("min_risk_pct", minRiskPct); put("max_risk_pct", maxRiskPct); put("max_entry_gap_pct", maxEntryGapPct); put("max_gap_ma20_pct", maxGapMa20Pct); put("surge_threshold_pct", surgeThresholdPct); put("hold_days", holdDays) }) }

private data class StockSnapshot(val createdAtKst: String, val mode: String, val quoteOkRate: Double, val quoteOk: Int, val total: Int, val stocks: List<KrShortStock>)
private data class KrShortStock(val code: String, val name: String, val sector: String, val strategyType: String, val currentPrice: Double, val priceBasis: String, val priceTimestamp: String, val quoteSource: String, val score: Double, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val riskPct: Double, val reason: String, val failureCondition: String)
private data class KrShortRules(val version: Int, val scoreThreshold: Double, val minRiskPct: Double, val maxRiskPct: Double, val maxEntryGapPct: Double, val maxGapMa20Pct: Double, val surgeThresholdPct: Double, val holdDays: Int)
private data class RunScanResult(val krShortCount: Int)
private data class RecommendationHistory(val updatedAtKst: String, val items: List<RecommendationItem>)
private data class RecommendationItem(val scanDate: String, val recommendedAtKst: String, val code: String, val name: String, val sector: String, val strategyType: String, val entry: Double, val stopLoss: Double, val target1: Double, val target2: Double, val scoreAtRecommendation: Double, val latestPrice: Double, val pnlPct: Double?, val pnlKrwPerShare: Double?, val reason: String)

private fun formatPrice(value: Double): String = String.format("%,.0f", value)
private fun formatNumber(value: Double): String = String.format("%.2f", value)
private fun formatPercent(value: Double): String = String.format("%.1f%%", value * 100)
private fun formatSignedPercent(value: Double): String = String.format("%+.2f%%", value)
private fun formatSignedPrice(value: Double?): String = value?.let { String.format("%+,.0f원/주", it) } ?: "-"
private fun trimNumber(value: Double): String = if (value % 1.0 == 0.0) value.toInt().toString() else String.format("%.2f", value)
