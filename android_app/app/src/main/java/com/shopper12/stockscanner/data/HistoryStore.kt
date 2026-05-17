package com.shopper12.stockscanner.data

import android.content.Context
import com.shopper12.stockscanner.model.ManualAnalysis
import com.shopper12.stockscanner.model.ScanResult
import org.json.JSONArray
import org.json.JSONObject

class HistoryStore(context: Context) {
    private val prefs = context.getSharedPreferences("stock_scanner_history", Context.MODE_PRIVATE)

    data class HistoryItem(
        val time: String,
        val type: String,
        val title: String,
        val decision: String,
        val price: String,
        val score: String,
        val source: String
    )

    fun saveScan(scan: ScanResult) {
        val topUs = scan.usEtfs.firstOrNull()
        val topKr = scan.krShortStocks.firstOrNull()
        val title = buildString {
            append("환율 ${scan.fx.action}")
            if (topUs != null) append(" / US ${topUs.ticker}")
            if (topKr != null) append(" / KR ${topKr.name}")
        }
        val decision = listOfNotNull(
            topUs?.strategyReview,
            topKr?.strategyReview
        ).joinToString(" | ").ifBlank { "전략검토 없음" }
        appendItem(
            HistoryItem(
                time = scan.createdAt,
                type = "SCAN",
                title = title,
                decision = decision,
                price = "USD/KRW ${scan.fx.usdKrw}",
                score = topUs?.score?.toString() ?: "-",
                source = "auto/manual scan"
            )
        )
    }

    fun saveManual(analysis: ManualAnalysis) {
        appendItem(
            HistoryItem(
                time = nowText(),
                type = "MANUAL",
                title = "${analysis.symbol} (${analysis.market})",
                decision = analysis.strategyReview.ifBlank { analysis.opinion },
                price = analysis.currentPrice,
                score = analysis.score.toString(),
                source = analysis.dataSource
            )
        )
    }

    fun load(limit: Int = 80): List<HistoryItem> {
        val raw = prefs.getString(KEY_ITEMS, "[]") ?: "[]"
        val arr = runCatching { JSONArray(raw) }.getOrElse { JSONArray() }
        val out = mutableListOf<HistoryItem>()
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            out += HistoryItem(
                time = obj.optString("time"),
                type = obj.optString("type"),
                title = obj.optString("title"),
                decision = obj.optString("decision"),
                price = obj.optString("price"),
                score = obj.optString("score"),
                source = obj.optString("source")
            )
        }
        return out.take(limit)
    }

    fun clear() {
        prefs.edit().remove(KEY_ITEMS).apply()
    }

    private fun appendItem(item: HistoryItem) {
        val current = load(MAX_ITEMS).toMutableList()
        current.add(0, item)
        val arr = JSONArray()
        current.take(MAX_ITEMS).forEach {
            arr.put(
                JSONObject()
                    .put("time", it.time)
                    .put("type", it.type)
                    .put("title", it.title)
                    .put("decision", it.decision)
                    .put("price", it.price)
                    .put("score", it.score)
                    .put("source", it.source)
            )
        }
        prefs.edit().putString(KEY_ITEMS, arr.toString()).apply()
    }

    private fun nowText(): String {
        val scan = ScannerEngine().runScan()
        return scan.createdAt
    }

    companion object {
        private const val KEY_ITEMS = "items"
        private const val MAX_ITEMS = 200
    }
}
