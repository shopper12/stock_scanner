package com.stockscanner

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val CHART_API_BASE = "https://stock-scanner-api-5sk6.onrender.com/api/kr-stock-chart"

class ChartActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val code = intent?.data?.getQueryParameter("code") ?: intent?.getStringExtra("code") ?: "005930"
        setContent { MaterialTheme { ChartScreen(code = code, onBack = { finish() }) } }
    }
}

@Composable
private fun ChartScreen(code: String, onBack: () -> Unit) {
    var days by remember { mutableStateOf(120) }
    var chart by remember { mutableStateOf<StockChartPayload?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(code, days) {
        runCatching { fetchChart(code, days) }
            .onSuccess { chart = it; error = null }
            .onFailure { error = it.message ?: it::class.java.simpleName }
    }
    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onBack) { Text("뒤로") }
            Button(onClick = { days = 60 }) { Text("60일") }
            Button(onClick = { days = 120 }) { Text("120일") }
            Button(onClick = { days = 252 }) { Text("252일") }
        }
        if (error != null) Text("차트 오류: $error")
        val c = chart
        if (c == null && error == null) Text("차트 로딩 중")
        if (c != null) {
            Text("${c.name}(${c.code})", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            c.strategy?.let { StrategyCard(it) }
            TradeSummaryCard(c.trades)
            CandleStrategyChart(c.candles, c.ma20, c.ma60, c.ma200, c.strategy, c.trades)
            Text("캔들 + MA20/60/200 + 진입/손절/목표가 + 백테스트 진입·청산 마커", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun StrategyCard(s: ChartStrategy) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("전략: ${s.setup ?: "-"} / score=${s.score ?: 0.0}", fontWeight = FontWeight.Bold)
            Text("진입 ${fmt(s.entry)} / 손절 ${fmt(s.stopLoss)} / 목표 ${fmt(s.target1)} → ${fmt(s.target2)}")
            Text("근거: ${s.reason ?: "-"}")
            Text("스캔: ${s.scanTime ?: "-"}")
        }
    }
}

@Composable
private fun TradeSummaryCard(trades: List<TradeMarker>) {
    if (trades.isEmpty()) {
        Text("백테스트 마커 없음: 백테스트 실행 후 표시됩니다.")
        return
    }
    val closed = trades.filter { it.exitReason.isNotBlank() }
    val avg = closed.map { it.returnPct }.average().takeIf { !it.isNaN() }
    val winRate = if (closed.isNotEmpty()) closed.count { it.returnPct > 0 }.toDouble() / closed.size else 0.0
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("백테스트 결과 마커 ${trades.size}건", fontWeight = FontWeight.Bold)
            Text("평균 ${avg?.let { String.format("%+.2f%%", it) } ?: "-"} / 승률 ${String.format("%.1f%%", winRate * 100)}")
            trades.takeLast(3).reversed().forEach { t ->
                Text("${t.entryDate} → ${t.exitDate.ifBlank { "-" }} | ${t.exitReason.ifBlank { "-" }} | ${String.format("%+.2f%%", t.returnPct)}")
            }
        }
    }
}

@Composable
private fun CandleStrategyChart(
    candles: List<Candle>,
    ma20: List<Double?>,
    ma60: List<Double?>,
    ma200: List<Double?>,
    strategy: ChartStrategy?,
    trades: List<TradeMarker>,
) {
    if (candles.isEmpty()) { Text("차트 데이터 없음"); return }
    Canvas(modifier = Modifier.fillMaxWidth().height(360.dp).padding(8.dp)) {
        val strategyPrices = listOfNotNull(strategy?.entry, strategy?.stopLoss, strategy?.target1, strategy?.target2).filter { it > 0 }
        val tradePrices = trades.flatMap { listOf(it.entry, it.exitPrice) }.filter { it > 0 }
        val prices = candles.flatMap { listOf(it.open, it.high, it.low, it.close) } + strategyPrices + tradePrices
        val minP = prices.minOrNull() ?: 0.0
        val maxP = prices.maxOrNull() ?: 1.0
        val range = (maxP - minP).takeIf { it > 0 } ?: 1.0
        val dateIndex = candles.mapIndexed { index, candle -> candle.date to index }.toMap()
        fun y(p: Double): Float = (size.height - ((p - minP) / range * size.height)).toFloat()
        fun x(i: Int): Float = if (candles.size <= 1) 0f else i.toFloat() / (candles.size - 1).toFloat() * size.width
        val step = if (candles.size <= 1) size.width else size.width / (candles.size - 1).toFloat()
        candles.forEachIndexed { i, c ->
            val px = x(i)
            val color = if (c.close >= c.open) Color(0xFFE53935) else Color(0xFF1E88E5)
            drawLine(color, Offset(px, y(c.high)), Offset(px, y(c.low)), strokeWidth = 1.4f)
            drawLine(color, Offset(px - step * 0.25f, y(c.open)), Offset(px, y(c.open)), strokeWidth = 2.4f)
            drawLine(color, Offset(px, y(c.close)), Offset(px + step * 0.25f, y(c.close)), strokeWidth = 2.4f)
        }
        drawMa(ma20, Color(0xFFFFC107), candles.size, ::x, ::y)
        drawMa(ma60, Color(0xFF4CAF50), candles.size, ::x, ::y)
        drawMa(ma200, Color(0xFF7E57C2), candles.size, ::x, ::y)
        listOf(strategy?.entry to Color(0xFFFF9800), strategy?.stopLoss to Color(0xFFE53935), strategy?.target1 to Color(0xFF43A047), strategy?.target2 to Color(0xFF1B5E20)).forEach { pair ->
            val price = pair.first
            if (price != null && price > 0) drawLine(pair.second, Offset(0f, y(price)), Offset(size.width, y(price)), strokeWidth = 2.2f)
        }
        trades.forEach { t ->
            val entryIdx = dateIndex[t.entryDate]
            if (entryIdx != null && t.entry > 0) {
                val p = Offset(x(entryIdx), y(t.entry))
                drawCircle(Color(0xFFFF9800), radius = 6f, center = p)
            }
            val exitIdx = dateIndex[t.exitDate]
            if (exitIdx != null && t.exitPrice > 0) {
                val color = if (t.returnPct >= 0) Color(0xFF43A047) else Color(0xFFE53935)
                val p = Offset(x(exitIdx), y(t.exitPrice))
                drawCircle(color, radius = 7f, center = p)
            }
        }
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawMa(values: List<Double?>, color: Color, sizeN: Int, x: (Int) -> Float, y: (Double) -> Float) {
    var last: Offset? = null
    for (i in 0 until minOf(values.size, sizeN)) {
        val v = values[i] ?: continue
        val now = Offset(x(i), y(v))
        val prev = last
        if (prev != null) drawLine(color, prev, now, strokeWidth = 2f)
        last = now
    }
}

private suspend fun fetchChart(code: String, days: Int): StockChartPayload = withContext(Dispatchers.IO) {
    val url = "$CHART_API_BASE?code=$code&days=$days"
    val conn = (URL(url).openConnection() as HttpURLConnection).apply { connectTimeout = 15000; readTimeout = 120000; requestMethod = "GET" }
    val body = conn.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
    parseChart(JSONObject(body))
}

private fun parseChart(json: JSONObject): StockChartPayload {
    val candles = json.optJSONArray("candles")
    val indicators = json.optJSONObject("indicators") ?: JSONObject()
    val trades = json.optJSONArray("backtest_trades")
    return StockChartPayload(
        code = json.optString("code"),
        name = json.optString("name"),
        candles = buildList { if (candles != null) for (i in 0 until candles.length()) candles.optJSONObject(i)?.let { add(Candle(it.optString("date"), it.optDouble("open"), it.optDouble("high"), it.optDouble("low"), it.optDouble("close"))) } },
        ma20 = indicators.optDoubleList("ma20"),
        ma60 = indicators.optDoubleList("ma60"),
        ma200 = indicators.optDoubleList("ma200"),
        strategy = json.optJSONObject("strategy")?.let { ChartStrategy(it.optDoubleOrNull("score"), it.optString("setup"), it.optDoubleOrNull("entry"), it.optDoubleOrNull("stop_loss"), it.optDoubleOrNull("target1"), it.optDoubleOrNull("target2"), it.optString("reason"), it.optString("scan_time")) },
        trades = buildList { if (trades != null) for (i in 0 until trades.length()) trades.optJSONObject(i)?.let { add(TradeMarker(it.optString("entry_date", it.optString("date")), it.optString("exit_date"), it.optDouble("entry", 0.0), it.optDouble("exit_price", 0.0), it.optDouble("trade_return_pct", 0.0), it.optString("exit_reason"))) } }
    )
}

private fun JSONObject.optDoubleList(key: String): List<Double?> {
    val arr = optJSONArray(key) ?: return emptyList()
    return List(arr.length()) { i -> if (arr.isNull(i)) null else arr.optDouble(i) }
}
private fun JSONObject.optDoubleOrNull(key: String): Double? = if (has(key) && !isNull(key)) optDouble(key) else null
private fun fmt(v: Double?): String = v?.let { String.format("%,.0f", it) } ?: "-"

private data class StockChartPayload(val code: String, val name: String, val candles: List<Candle>, val ma20: List<Double?>, val ma60: List<Double?>, val ma200: List<Double?>, val strategy: ChartStrategy?, val trades: List<TradeMarker>)
private data class Candle(val date: String, val open: Double, val high: Double, val low: Double, val close: Double)
private data class ChartStrategy(val score: Double?, val setup: String?, val entry: Double?, val stopLoss: Double?, val target1: Double?, val target2: Double?, val reason: String?, val scanTime: String?)
private data class TradeMarker(val entryDate: String, val exitDate: String, val entry: Double, val exitPrice: Double, val returnPct: Double, val exitReason: String)
