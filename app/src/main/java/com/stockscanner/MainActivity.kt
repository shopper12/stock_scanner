package com.stockscanner

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

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                StockScannerScreen()
            }
        }
    }
}

@Composable
private fun StockScannerScreen() {
    var loading by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var snapshot by remember { mutableStateOf<StockSnapshot?>(null) }
    var rules by remember { mutableStateOf<KrShortRules?>(null) }
    var adminToken by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    suspend fun refresh() {
        loading = true
        error = null
        runCatching {
            snapshot = fetchSnapshot()
            rules = fetchRules()
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        loading = false
    }

    suspend fun saveRules() {
        val current = rules ?: return
        saving = true
        error = null
        message = null
        runCatching {
            rules = postRules(current, adminToken)
            val scanResult = runScan(adminToken)
            snapshot = fetchSnapshot()
            message = "조건 저장 및 재스캔 완료: KR 후보 ${scanResult.krShortCount}개"
        }.onFailure { error = it.message ?: it::class.java.simpleName }
        saving = false
    }

    LaunchedEffect(Unit) { refresh() }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text("Stock Scanner", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { scope.launch { refresh() } }, enabled = !loading && !saving) {
                    Text(if (loading) "Loading" else "Refresh")
                }
                Button(onClick = { scope.launch { saveRules() } }, enabled = rules != null && !loading && !saving) {
                    Text(if (saving) "Saving" else "조건 저장+스캔")
                }
            }
        }
        if (error != null) item { InfoCard("API error: $error") }
        if (message != null) item { InfoCard(message ?: "") }
        item {
            RulesEditor(
                rules = rules,
                adminToken = adminToken,
                onAdminTokenChange = { adminToken = it },
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

@Composable
private fun RulesEditor(
    rules: KrShortRules?,
    adminToken: String,
    onAdminTokenChange: (String) -> Unit,
    onRulesChange: (KrShortRules) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("한국 단기 종목 검색 조건", fontWeight = FontWeight.Bold)
            Text("아래 값은 서버의 KR 단기 스캐너 규칙입니다. 저장하려면 Render 환경변수 ADMIN_TOKEN과 같은 값을 입력해야 합니다.")
            OutlinedTextField(
                value = adminToken,
                onValueChange = onAdminTokenChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("관리자 토큰") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
            )
            if (rules == null) {
                Text("조건 로딩 중 또는 조건 API 미배포 상태")
                return@Column
            }
            RuleNumberField("최소 후보 점수", "score_threshold", rules.scoreThreshold, "이 점수보다 낮으면 후보 제외. 높이면 엄격, 낮추면 후보 증가.") {
                onRulesChange(rules.copy(scoreThreshold = it))
            }
            RuleNumberField("최소 손절폭 %", "min_risk_pct", rules.minRiskPct, "진입가 대비 최소 손절폭. 너무 낮으면 노이즈 손절 증가.") {
                onRulesChange(rules.copy(minRiskPct = it))
            }
            RuleNumberField("최대 손절폭 %", "max_risk_pct", rules.maxRiskPct, "진입가 대비 최대 허용 손절폭. 높이면 위험 큰 종목도 통과.") {
                onRulesChange(rules.copy(maxRiskPct = it))
            }
            RuleNumberField("최대 진입 괴리율 %", "max_entry_gap_pct", rules.maxEntryGapPct, "돌파 진입가가 현재가보다 이 이상 높으면 제외.") {
                onRulesChange(rules.copy(maxEntryGapPct = it))
            }
            RuleNumberField("MA20 과열 한도 %", "max_gap_ma20_pct", rules.maxGapMa20Pct, "현재가가 MA20보다 과도하게 높으면 점수 패널티.") {
                onRulesChange(rules.copy(maxGapMa20Pct = it))
            }
            RuleNumberField("급등 검증 기준 %", "surge_threshold_pct", rules.surgeThresholdPct, "백테스트에서 급등으로 볼 기준 수익률.") {
                onRulesChange(rules.copy(surgeThresholdPct = it))
            }
            RuleNumberField("기본 보유일", "hold_days", rules.holdDays.toDouble(), "단기 전략 검증 및 보유 기준 일수.") {
                onRulesChange(rules.copy(holdDays = it.toInt()))
            }
            Text("현재 버전: ${rules.version}")
        }
    }
}

@Composable
private fun RuleNumberField(labelKo: String, key: String, value: Double, help: String, onValue: (Double) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        OutlinedTextField(
            value = trimNumber(value),
            onValueChange = { text -> text.toDoubleOrNull()?.let(onValue) },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("$labelKo ($key)") },
            singleLine = true,
        )
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
    Card(modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(12.dp))
    }
}

private suspend fun fetchSnapshot(): StockSnapshot = withContext(Dispatchers.IO) {
    val body = httpJson("GET", LATEST_URL, null, null)
    parseSnapshot(JSONObject(body))
}

private suspend fun fetchRules(): KrShortRules = withContext(Dispatchers.IO) {
    val body = httpJson("GET", RULES_URL, null, null)
    parseRules(JSONObject(body).optJSONObject("rules") ?: JSONObject())
}

private suspend fun postRules(rules: KrShortRules, token: String): KrShortRules = withContext(Dispatchers.IO) {
    val body = httpJson("POST", RULES_URL, rules.toJson().toString(), token)
    parseRules(JSONObject(body).optJSONObject("rules") ?: JSONObject())
}

private suspend fun runScan(token: String): RunScanResult = withContext(Dispatchers.IO) {
    val body = httpJson("POST", RUN_SCAN_URL, "{}", token)
    val json = JSONObject(body)
    RunScanResult(json.optInt("kr_short_count", 0))
}

private fun httpJson(method: String, url: String, requestBody: String?, token: String?): String {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        requestMethod = method
        connectTimeout = 15000
        readTimeout = if (url == RUN_SCAN_URL) 60000 else 15000
        setRequestProperty("Accept", "application/json")
        setRequestProperty("User-Agent", "StockScanner-Android")
        if (method == "POST") {
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (!token.isNullOrBlank()) setRequestProperty("X-Admin-Token", token)
        }
    }
    try {
        if (requestBody != null) {
            connection.outputStream.use { it.write(requestBody.toByteArray(Charsets.UTF_8)) }
        }
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
        if (rows != null) {
            for (i in 0 until rows.length()) {
                val item = rows.optJSONObject(i) ?: continue
                add(
                    KrShortStock(
                        code = item.optString("code", ""),
                        name = item.optString("name", ""),
                        sector = item.optString("sector", "기타"),
                        strategyType = item.optString("strategy_type", ""),
                        currentPrice = item.optDouble("current_price", 0.0),
                        priceBasis = item.optString("price_basis", "unknown"),
                        priceTimestamp = item.optString("price_timestamp", "unknown"),
                        quoteSource = item.optString("quote_source", item.optString("data_source", "unknown")),
                        score = item.optDouble("score", 0.0),
                        entry = item.optDouble("entry", 0.0),
                        stopLoss = item.optDouble("stop_loss", 0.0),
                        target1 = item.optDouble("target1", 0.0),
                        target2 = item.optDouble("target2", 0.0),
                        riskPct = item.optDouble("risk_pct", 0.0),
                        reason = item.optString("reason", ""),
                        failureCondition = item.optString("failure_condition", ""),
                    )
                )
            }
        }
    }
    return StockSnapshot(
        createdAtKst = json.optString("created_at_kst", "-"),
        mode = json.optString("mode", "unknown"),
        quoteOkRate = quality.optDouble("kr_short_quote_ok_rate", 0.0),
        quoteOk = quality.optInt("kr_short_quote_ok", 0),
        total = quality.optInt("kr_short_total", stocks.size),
        stocks = stocks,
    )
}

private fun parseRules(json: JSONObject): KrShortRules = KrShortRules(
    version = json.optInt("version", 1),
    scoreThreshold = json.optDouble("score_threshold", 62.0),
    minRiskPct = json.optDouble("min_risk_pct", 1.5),
    maxRiskPct = json.optDouble("max_risk_pct", 12.0),
    maxEntryGapPct = json.optDouble("max_entry_gap_pct", 3.5),
    maxGapMa20Pct = json.optDouble("max_gap_ma20_pct", 12.0),
    surgeThresholdPct = json.optDouble("surge_threshold_pct", 15.0),
    holdDays = json.optInt("hold_days", 10),
)

private fun KrShortRules.toJson(): JSONObject = JSONObject().apply {
    put("rules", JSONObject().apply {
        put("score_threshold", scoreThreshold)
        put("min_risk_pct", minRiskPct)
        put("max_risk_pct", maxRiskPct)
        put("max_entry_gap_pct", maxEntryGapPct)
        put("max_gap_ma20_pct", maxGapMa20Pct)
        put("surge_threshold_pct", surgeThresholdPct)
        put("hold_days", holdDays)
    })
}

private data class StockSnapshot(
    val createdAtKst: String,
    val mode: String,
    val quoteOkRate: Double,
    val quoteOk: Int,
    val total: Int,
    val stocks: List<KrShortStock>,
)

private data class KrShortStock(
    val code: String,
    val name: String,
    val sector: String,
    val strategyType: String,
    val currentPrice: Double,
    val priceBasis: String,
    val priceTimestamp: String,
    val quoteSource: String,
    val score: Double,
    val entry: Double,
    val stopLoss: Double,
    val target1: Double,
    val target2: Double,
    val riskPct: Double,
    val reason: String,
    val failureCondition: String,
)

private data class KrShortRules(
    val version: Int,
    val scoreThreshold: Double,
    val minRiskPct: Double,
    val maxRiskPct: Double,
    val maxEntryGapPct: Double,
    val maxGapMa20Pct: Double,
    val surgeThresholdPct: Double,
    val holdDays: Int,
)

private data class RunScanResult(val krShortCount: Int)

private fun formatPrice(value: Double): String = String.format("%,.0f", value)
private fun formatNumber(value: Double): String = String.format("%.2f", value)
private fun formatPercent(value: Double): String = String.format("%.1f%%", value * 100)
private fun trimNumber(value: Double): String = if (value % 1.0 == 0.0) value.toInt().toString() else String.format("%.2f", value)
