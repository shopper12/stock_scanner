package com.stockscanner

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
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

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        item { Text("봇 추천", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold) }
        item { Button(onClick = { scope.launch { refresh() } }, enabled = !loading) { Text(if (loading) "Loading" else "새로고침") } }
        error?.let { item { InfoCard("API error: $it") } }
        item { InfoCard("업데이트: ${payload.updatedAt.ifBlank { "-" }} / ${payload.items.size}개") }
        if (payload.items.isEmpty()) {
            item { InfoCard("저장된 봇 추천이 없습니다. 브리핑 JSON이 서버에 올라오면 여기에 표시됩니다.") }
        } else {
            items(payload.items) { card -> BotCard(card) }
        }
    }
}

@Composable
private fun BotCard(card: BotCardItem) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("${card.name.ifBlank { card.ticker }}(${card.ticker.ifBlank { "-" }}) | ${card.market}/${card.direction}", fontWeight = FontWeight.Bold)
            Text("기준가 ${card.basisPrice.ifBlank { "-" }} ${card.currency} / ${card.basisTimestamp.ifBlank { "-" }}")
            Text("진입 ${card.entry.ifBlank { "-" }} / 손절 ${card.stop.ifBlank { "-" }}")
            Text("목표 ${card.target1.ifBlank { "-" }} → ${card.target2.ifBlank { "-" }}")
            if (card.invalidation.isNotBlank()) Text("무효화: ${card.invalidation}")
            if (card.reason.isNotBlank()) Text("근거: ${card.reason}")
            if (card.risk.isNotBlank()) Text("리스크: ${card.risk}")
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
                    basisPrice = obj.anyString("basis_price", "current_price", "latest_price"),
                    currency = obj.anyString("basis_price_currency", "currency"),
                    basisTimestamp = obj.anyString("basis_timestamp_kst", "recommended_at_kst", "updated_at_kst"),
                    entry = obj.anyString("entry", "entry_price"),
                    stop = obj.anyString("stop", "stop_loss"),
                    target1 = obj.anyString("target1", "target_1"),
                    target2 = obj.anyString("target2", "target_2"),
                    invalidation = obj.anyString("invalidation", "failure_condition"),
                    reason = obj.anyString("reason", "rationale"),
                    risk = obj.anyString("risk", "risk_note"),
                )
            )
        }
    }
    BotCardsPayload(
        updatedAt = json.anyString("briefing_datetime_kst", "updated_at_kst", "generated_at"),
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

private data class BotCardsPayload(val updatedAt: String = "", val items: List<BotCardItem> = emptyList())
private data class BotCardItem(
    val name: String,
    val ticker: String,
    val market: String,
    val direction: String,
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
