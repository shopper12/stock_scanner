package com.stockscanner

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.weight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val BOT_CARDS_URL = "https://stock-scanner-api-5sk6.onrender.com/api/recommendations"
private const val NOTIFICATION_PERMISSION_REQUEST_CODE = 9305

class BotCardsActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationPermissionIfNeeded()
        RecommendationAlertScheduler.ensureScheduled(this)
        setContent { MaterialTheme { BotCardsScreen() } }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFICATION_PERMISSION_REQUEST_CODE)
    }
}

@Composable
private fun BotCardsScreen() {
    val scope = rememberCoroutineScope()
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var payload by remember { mutableStateOf(BotCardsPayload()) }

    suspend fun refresh() {
        loading = true
        error = null
        runCatching { payload = fetchBotCards() }
            .onFailure { error = it.message ?: it::class.java.simpleName }
        loading = false
    }

    LaunchedEffect(Unit) { refresh() }

    val ranked = payload.items.sortedByDescending { it.score.toDoubleOrNull() ?: 0.0 }
    val first = ranked.firstOrNull()

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column(modifier = Modifier.padding(top = 18.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("오늘 추천 4개", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("복잡한 분석보다 진입·손절·기다릴지부터 봅니다.")
                Text("업데이트 ${friendlyTime(payload.updatedAt)}", style = MaterialTheme.typography.bodySmall)
            }
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("지금 할 일", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    if (first == null) {
                        Text(if (loading) "최신 추천을 불러오는 중입니다." else "현재 저장된 추천이 없습니다.")
                    } else {
                        Text("${first.name.ifBlank { first.ticker }} (${first.ticker.ifBlank { "-" }})", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                        Text("${directionKorean(first.direction)} · ${statusKorean(first.status)} · ${first.score.ifBlank { "-" }}점")
                        Text(actionText(first.status), fontWeight = FontWeight.Bold)
                        Text("진입 ${first.entry.ifBlank { "조건 확인" }} · 손절 ${first.stop.ifBlank { "-" }}")
                    }
                    Button(onClick = { scope.launch { refresh() } }, enabled = !loading, modifier = Modifier.fillMaxWidth()) {
                        Text(if (loading) "불러오는 중" else "최신 추천 새로고침")
                    }
                }
            }
        }

        item {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("읽는 법", fontWeight = FontWeight.Bold)
                    Text("조건 대기 = 지금 사지 말기")
                    Text("실행 가능 = 손절까지 감당될 때만 분할")
                    Text("관찰만 = 매수 금지, 조건 변화만 보기")
                }
            }
        }

        error?.let { item { InfoCard("불러오기 오류: $it") } }

        if (ranked.isEmpty() && !loading) {
            item { InfoCard("브리핑 JSON이 서버에 올라오면 여기에 바로 표시됩니다.") }
        } else {
            items(ranked.take(4)) { card -> BotCard(card) }
        }
    }
}

@Composable
private fun BotCard(card: BotCardItem) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("${card.name.ifBlank { card.ticker }} (${card.ticker.ifBlank { "-" }})", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium)
                    Text("${directionKorean(card.direction)} · ${statusKorean(card.status)}")
                }
                Text("${card.score.ifBlank { "-" }}점", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleLarge)
            }
            Text(actionText(card.status), fontWeight = FontWeight.Bold)
            Text("현재/기준  ${card.basisPrice.ifBlank { "-" }} ${card.currency}")
            Text("진입  ${card.entry.ifBlank { "조건 확인" }}")
            Text("손절  ${card.stop.ifBlank { "-" }}")
            Text("목표  ${card.target1.ifBlank { "-" }} → ${card.target2.ifBlank { "-" }}")
            if (card.reason.isNotBlank()) Text("왜? ${card.reason}", style = MaterialTheme.typography.bodySmall)
            if (card.risk.isNotBlank()) Text("주의: ${card.risk}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            if (card.invalidation.isNotBlank()) Text("폐기 조건: ${card.invalidation}", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun InfoCard(text: String) {
    Card(modifier = Modifier.fillMaxWidth()) { Text(text, modifier = Modifier.padding(12.dp)) }
}

private suspend fun fetchBotCards(): BotCardsPayload = withContext(Dispatchers.IO) {
    val json = JSONObject(httpGet(BOT_CARDS_URL))
    val rows = json.optJSONArray("recommendations")
        ?: json.optJSONArray("items")
        ?: json.optJSONArray("chatgpt_recommendations")
        ?: JSONArray()
    val items = buildList {
        for (i in 0 until rows.length()) rows.optJSONObject(i)?.let { obj ->
            add(
                BotCardItem(
                    name = obj.anyString("asset_name", "name"),
                    ticker = obj.anyString("ticker", "code", "symbol"),
                    market = obj.anyString("market", "sector"),
                    direction = obj.anyString("direction", "action"),
                    status = obj.anyString("status", "signal_status"),
                    score = obj.anyString("score", "confidence_score"),
                    confidence = obj.anyString("confidence_numeric", "confidence"),
                    basisPrice = obj.anyString("current_price", "basis_price", "reference_price", "latest_price"),
                    currency = obj.anyString("currency", "basis_price_currency"),
                    basisTimestamp = obj.anyString("price_timestamp_kst", "basis_timestamp_kst", "recommended_at_kst", "updated_at_kst"),
                    entry = obj.rangeString("entry_low", "entry_high", "entry", "entry_price"),
                    stop = obj.anyString("stop_loss", "stop", "stop_price"),
                    target1 = obj.anyString("target_1", "target1"),
                    target2 = obj.anyString("target_2", "target2"),
                    invalidation = obj.anyString("invalidation", "failure_condition"),
                    reason = obj.anyString("reason", "rationale"),
                    risk = obj.anyString("risk", "risk_note"),
                )
            )
        }
    }
    BotCardsPayload(
        updatedAt = json.anyString("briefing_datetime_kst", "updated_at_kst", "generated_at", "generatedAtKst"),
        items = items,
    )
}

private fun httpGet(url: String): String {
    val connection = (URL(url).openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"
        connectTimeout = 15000
        readTimeout = 15000
        setRequestProperty("Accept", "application/json")
        setRequestProperty("User-Agent", "StockScanner-Android")
    }
    try {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        if (code !in 200..299) error("HTTP $code: ${body.take(200)}")
        if (body.trimStart().startsWith("<")) error("서버가 JSON 대신 HTML을 반환했습니다.")
        return body
    } finally {
        connection.disconnect()
    }
}

private fun JSONObject.anyString(vararg keys: String): String {
    for (key in keys) if (has(key) && !isNull(key)) return opt(key).toString()
    return ""
}

private fun JSONObject.rangeString(lowKey: String, highKey: String, vararg fallbacks: String): String {
    val low = anyString(lowKey)
    val high = anyString(highKey)
    if (low.isNotBlank() || high.isNotBlank()) return listOf(low, high).filter { it.isNotBlank() }.joinToString(" ~ ")
    return anyString(*fallbacks)
}

private fun directionKorean(value: String): String = when (value.uppercase()) {
    "LONG" -> "상승 전략"
    "SHORT" -> "하락 전략"
    "INVERSE" -> "인버스"
    "DEFENSIVE" -> "방어"
    else -> value.ifBlank { "방향 미확인" }
}

private fun statusKorean(value: String): String = when (value.uppercase()) {
    "IMMEDIATE", "ACTIVE_SIGNAL" -> "실행 가능"
    "CONDITIONAL", "UNTRIGGERED" -> "조건 대기"
    "WATCH", "SOURCE_REVIEW_REQUIRED" -> "관찰만"
    else -> value.ifBlank { "상태 미확인" }
}

private fun actionText(status: String): String = when (status.uppercase()) {
    "IMMEDIATE", "ACTIVE_SIGNAL" -> "지금 행동: 손절까지 확인한 뒤 분할로만 접근"
    "CONDITIONAL", "UNTRIGGERED" -> "지금 행동: 기다리기. 진입구간 전에는 사지 않기"
    "WATCH", "SOURCE_REVIEW_REQUIRED" -> "지금 행동: 매수 금지. 조건 변화만 보기"
    else -> "지금 행동: 조건 확인 전에는 아무것도 하지 않기"
}

private fun friendlyTime(value: String): String = value
    .replace("T", " ")
    .replace("+09:00", "")
    .take(16)
    .ifBlank { "미확인" }

private data class BotCardsPayload(val updatedAt: String = "", val items: List<BotCardItem> = emptyList())
private data class BotCardItem(
    val name: String,
    val ticker: String,
    val market: String,
    val direction: String,
    val status: String,
    val score: String,
    val confidence: String,
    val basisPrice: String,
    val currency: String,
    val basisTimestamp: String,
    val entry: String,
    val stop: String,
    val target1: String,
    val target2: String,
    val invalidation: String,
    val reason: String,
    val risk: String,
)
