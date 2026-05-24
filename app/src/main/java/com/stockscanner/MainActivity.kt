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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val API_URL = "https://stock-scanner-api-5sk6.onrender.com/api/latest"

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
    var error by remember { mutableStateOf<String?>(null) }
    var snapshot by remember { mutableStateOf<StockSnapshot?>(null) }
    val scope = rememberCoroutineScope()

    suspend fun refresh() {
        loading = true
        error = null
        runCatching { fetchSnapshot() }
            .onSuccess { snapshot = it }
            .onFailure { error = it.message ?: it::class.java.simpleName }
        loading = false
    }

    LaunchedEffect(Unit) { refresh() }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Stock Scanner", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { scope.launch { refresh() } }, enabled = !loading) {
                Text(if (loading) "Loading" else "Refresh")
            }
        }
        if (error != null) {
            InfoCard("API error: $error")
        }
        val data = snapshot
        if (data == null) {
            InfoCard(if (loading) "Loading latest scan." else "No scan data loaded.")
        } else {
            Text("Scan: ${data.createdAtKst} / mode=${data.mode}")
            Text("Quote: ${data.quoteOk}/${data.total} (${formatPercent(data.quoteOkRate)})")
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (data.stocks.isEmpty()) {
                    item { InfoCard("No KR short candidates.") }
                } else {
                    items(data.stocks) { stock -> StockCard(stock) }
                }
            }
        }
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
    val connection = (URL(API_URL).openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"
        connectTimeout = 12000
        readTimeout = 12000
        setRequestProperty("Accept", "application/json")
        setRequestProperty("User-Agent", "StockScanner-Android")
    }
    try {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        if (code !in 200..299) error("HTTP $code: $body")
        parseSnapshot(JSONObject(body))
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

private fun formatPrice(value: Double): String = String.format("%,.0f", value)
private fun formatNumber(value: Double): String = String.format("%.2f", value)
private fun formatPercent(value: Double): String = String.format("%.1f%%", value * 100)
