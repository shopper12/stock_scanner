package com.shopper12.stockscanner.notify

import com.shopper12.stockscanner.BuildConfig
import com.shopper12.stockscanner.model.ScanResult
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

class TelegramNotifier {
    private val client = OkHttpClient()

    fun send(result: ScanResult): Boolean {
        val token = BuildConfig.TELEGRAM_BOT_TOKEN
        val chatIds = BuildConfig.TELEGRAM_CHAT_IDS
            .split(',', ';', '\n')
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .distinct()
            .ifEmpty { listOf(BuildConfig.TELEGRAM_CHAT_ID.trim()).filter { it.isNotBlank() } }

        if (token.isBlank() || chatIds.isEmpty()) return false

        val text = buildMessage(result)
        return chatIds.map { chatId -> sendMessage(token, chatId, text) }.all { it }
    }

    private fun sendMessage(token: String, chatId: String, text: String): Boolean {
        val json = JSONObject()
            .put("chat_id", chatId)
            .put("text", text)
            .put("parse_mode", "HTML")
            .put("disable_web_page_preview", true)
        val request = Request.Builder()
            .url("https://api.telegram.org/bot$token/sendMessage")
            .post(json.toString().toRequestBody("application/json".toMediaType()))
            .build()
        client.newCall(request).execute().use { response ->
            return response.isSuccessful
        }
    }

    private fun buildMessage(result: ScanResult): String {
        val lines = mutableListOf<String>()
        lines += "📌 <b>Stock Scanner App 요약</b>"
        lines += "기준시각: ${escape(result.createdAt)}"
        lines += ""
        lines += "💵 <b>환율</b>"
        lines += "USD/KRW ${result.fx.usdKrw} / 60일평균 ${result.fx.ma60} / 판단: ${escape(result.fx.action)}"
        lines += "권장 환전: ${result.fx.suggestedConversionKrw}원"
        lines += ""
        lines += "🇺🇸 <b>미국 장기 ETF</b>"
        result.usEtfs.take(3).forEach {
            lines += "${escape(it.ticker)} 점수 ${it.score} / 매수 ${it.buyPct}% / ${escape(it.condition)}"
        }
        lines += ""
        lines += "🏦 <b>퇴직연금</b>"
        lines += "위험자산 ${result.retirement.riskyPct}% / 상태: ${escape(result.retirement.status)} / 여력 ${result.retirement.riskyBuyRoomKrw}원"
        lines += ""
        lines += "🇰🇷 <b>한국 단기 후보</b>"
        result.krShortStocks.take(3).forEach {
            lines += "${escape(it.name)}(${escape(it.code)}) 진입 ${it.entry} / 손절 ${it.stopLoss} / 목표 ${it.target1}"
        }
        return lines.joinToString("\n")
    }

    private fun escape(value: String): String = value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
}
