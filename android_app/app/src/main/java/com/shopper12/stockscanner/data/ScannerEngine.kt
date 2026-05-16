package com.shopper12.stockscanner.data

import com.shopper12.stockscanner.model.*
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max

class ScannerEngine {
    fun runScan(): ScanResult {
        val fx = analyzeFx()
        val usEtfs = scanUsEtfs(fx)
        val retirement = analyzeRetirement()
        val krShort = scanKrShortStocks()
        val now = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA).format(Date())
        return ScanResult(now, fx, usEtfs, retirement, krShort)
    }

    private fun analyzeFx(): FxSignal {
        val usdKrw = 1364.2
        val ma60 = 1378.5
        val gap = usdKrw / ma60 - 1.0
        return when {
            gap <= -0.015 -> FxSignal(usdKrw, ma60, "선환전 검토", 600_000, "USD/KRW가 60일 평균보다 낮음")
            gap >= 0.02 -> FxSignal(usdKrw, ma60, "최소환전 / 선환전 금지", 200_000, "USD/KRW가 60일 평균보다 높음")
            else -> FxSignal(usdKrw, ma60, "3~4회 분할환전", 350_000, "환율이 60일 평균권")
        }
    }

    private fun scanUsEtfs(fx: FxSignal): List<UsEtfSignal> {
        val base = listOf(
            Triple("VOO", "Vanguard S&P 500 ETF", 84.5),
            Triple("QQQ", "Invesco Nasdaq 100 ETF", 81.2),
            Triple("SMH", "VanEck Semiconductor ETF", 78.6),
            Triple("SCHD", "Schwab US Dividend Equity ETF", 73.4),
            Triple("GLD", "SPDR Gold Shares", 69.1)
        )
        return base.map { (ticker, name, score) ->
            val buyPct = if (fx.action.contains("최소환전")) 40.0 else if (score >= 80) 60.0 else 40.0
            UsEtfSignal(
                ticker = ticker,
                name = name,
                score = score,
                buyPct = buyPct,
                buyKrw = (1_000_000 * buyPct / 100.0).toLong(),
                condition = if (buyPct >= 60) "월 기본매수 + 눌림 추가매수" else "월 기본매수 40%",
                risk = if (ticker in listOf("QQQ", "SMH")) "기술주/금리 민감" else "장기 분할매수 가능"
            )
        }.sortedByDescending { it.score }
    }

    private fun analyzeRetirement(): RetirementSignal {
        val risky = 5_000_000.0
        val safe = 4_000_000.0
        val total = risky + safe
        val riskyPct = risky / total * 100.0
        val capValue = total * 0.70
        val room = max(0.0, capValue - risky).toLong()
        return RetirementSignal(
            riskyPct = (riskyPct * 100).toLong() / 100.0,
            safePct = ((safe / total * 100.0) * 100).toLong() / 100.0,
            riskyBuyRoomKrw = room,
            status = if (riskyPct < 70.0) "위험자산 한도 여유" else "위험자산 추가매수 금지"
        )
    }

    private fun scanKrShortStocks(): List<KrShortSignal> {
        return listOf(
            KrShortSignal("042700", "한미반도체", 82.4, 128_000, 123_000, 137_000, "거래량 증가 + 전고점 근접"),
            KrShortSignal("267260", "HD현대일렉트릭", 79.1, 410_000, 392_000, 444_000, "추세 유지 + 수급 후보"),
            KrShortSignal("010120", "LS ELECTRIC", 75.8, 212_000, 203_000, 229_000, "전력기기 테마 + 눌림 후 재돌파 후보")
        )
    }
}
