package com.shopper12.stockscanner.data

import com.shopper12.stockscanner.model.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

class ScannerEngine {
    private val http = OkHttpClient()

    private data class PriceSeries(
        val symbol: String,
        val latest: Double,
        val ma20: Double,
        val ma60: Double,
        val ma200: Double,
        val high52w: Double,
        val momentum12m: Double,
        val drawdown52w: Double,
        val chartPoints: List<ChartPoint>
    )

    fun runScan(): ScanResult {
        val fx = analyzeFx()
        val usEtfs = scanUsEtfs(fx)
        val retirement = analyzeRetirement()
        val retirementAssets = scanRetirementAssets()
        val krShort = scanKrShortStocks()
        val now = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.KOREA).format(Date())
        return ScanResult(
            createdAt = now,
            fx = fx,
            usEtfs = usEtfs,
            retirement = retirement,
            retirementAssets = retirementAssets,
            krShortStocks = krShort,
            strategies = strategyInfos(),
            validationLogs = validationLogs(now),
            revisionPolicy = revisionPolicy()
        )
    }

    fun analyzeManualSymbol(rawSymbol: String): ManualAnalysis {
        val symbol = rawSymbol.trim().uppercase(Locale.ROOT).ifBlank { "UNKNOWN" }
        val market = when {
            symbol.all { it.isDigit() } -> "KR"
            symbol.endsWith(".KS") || symbol.endsWith(".KQ") -> "KR"
            else -> "US/ETF"
        }
        val live = if (market == "US/ETF") fetchYahooSeries(symbol, "1y") else null
        val baseScore = live?.let { scoreFromSeries(it) } ?: (55.0 + abs(symbol.hashCode() % 1000) / 1000.0 * 35.0)
        val score = baseScore.round1()
        val entry = if (market == "KR") {
            "전고점 돌파 확인 후 분할 진입"
        } else if (live != null) {
            "현재 ${live.latest}, 20일선 ${live.ma20}, 60일선 ${live.ma60}. 60일선 부근이면 추가매수"
        } else {
            "월 기본매수 40% + 60일선 조정 추가"
        }
        val stop = if (market == "KR") "최근 5일 저점 또는 ATR 1.5배 이탈" else "장기 ETF는 손절보다 리밸런싱/비중 축소"
        val target = if (market == "KR") "1차 +8~12%, 2차 +18~25%" else "1년 이상 보유, 과열 시 신규매수 축소"
        val opinion = when {
            score >= 80 -> "관심 우선순위 높음"
            score >= 70 -> "조건부 관찰"
            score >= 60 -> "중립: 추가 확인 필요"
            else -> "보류"
        }
        val reasons = if (live != null) {
            listOf(
                "실데이터 기준 현재가 ${live.latest}",
                "12개월 모멘텀 ${(live.momentum12m * 100.0).round1()}%",
                "52주 고점 대비 ${(live.drawdown52w * 100.0).round1()}%",
                "MA20 ${live.ma20}, MA60 ${live.ma60}, MA200 ${live.ma200}"
            )
        } else {
            listOf(
                "모멘텀 점수 ${score.round1()} 기준",
                "거래량/추세/환율/자산군 리스크를 분리 판단",
                "실데이터 수신 실패 또는 한국 종목: mock 기반 예비 판단",
                "실전 적용 전 현재가·거래대금·뉴스 확인 필요"
            )
        }
        return ManualAnalysis(
            symbol = symbol,
            market = market,
            score = score,
            opinion = opinion,
            entry = entry,
            stop = stop,
            target = target,
            reasons = reasons,
            chartPoints = live?.chartPoints ?: projectedChart(score)
        )
    }

    private fun analyzeFx(): FxSignal {
        val live = fetchYahooSeries("KRW=X", "6mo")
        if (live != null) {
            val usdKrw = live.latest
            val ma60 = live.ma60
            val gap = usdKrw / ma60 - 1.0
            return when {
                gap <= -0.015 -> FxSignal(usdKrw, ma60, "선환전 검토", 600_000, "실데이터: USD/KRW가 60일 평균보다 낮음")
                gap >= 0.02 -> FxSignal(usdKrw, ma60, "최소환전 / 선환전 금지", 200_000, "실데이터: USD/KRW가 60일 평균보다 높음")
                else -> FxSignal(usdKrw, ma60, "3~4회 분할환전", 350_000, "실데이터: 환율이 60일 평균권")
            }
        }
        val usdKrw = 1364.2
        val ma60 = 1378.5
        val gap = usdKrw / ma60 - 1.0
        return when {
            gap <= -0.015 -> FxSignal(usdKrw, ma60, "선환전 검토", 600_000, "fallback: USD/KRW가 60일 평균보다 낮음")
            gap >= 0.02 -> FxSignal(usdKrw, ma60, "최소환전 / 선환전 금지", 200_000, "fallback: USD/KRW가 60일 평균보다 높음")
            else -> FxSignal(usdKrw, ma60, "3~4회 분할환전", 350_000, "fallback: 환율이 60일 평균권")
        }
    }

    private fun scanUsEtfs(fx: FxSignal): List<UsEtfSignal> {
        val base = listOf(
            Triple("VOO", "Vanguard S&P 500 ETF", 84.5),
            Triple("QQQ", "Invesco Nasdaq 100 ETF", 81.2),
            Triple("SMH", "VanEck Semiconductor ETF", 78.6),
            Triple("SCHD", "Schwab US Dividend Equity ETF", 73.4),
            Triple("GLD", "SPDR Gold Shares", 69.1),
            Triple("TLT", "iShares 20+ Year Treasury Bond ETF", 62.8),
            Triple("DBC", "Invesco DB Commodity Index", 61.5)
        )
        return base.map { (ticker, name, fallbackScore) ->
            val live = fetchYahooSeries(ticker, "1y")
            val score = (live?.let { scoreFromSeries(it) } ?: fallbackScore).round1()
            val buyPct = if (fx.action.contains("최소환전")) 40.0 else if (score >= 80) 60.0 else 40.0
            val condition = live?.let {
                "현재 ${it.latest} / MA20 ${it.ma20} / MA60 ${it.ma60} / DD52W ${(it.drawdown52w * 100.0).round1()}%"
            } ?: if (buyPct >= 60) "월 기본매수 + 눌림 추가매수" else "월 기본매수 40%"
            UsEtfSignal(
                ticker = ticker,
                name = name,
                score = score,
                buyPct = buyPct,
                buyKrw = (1_000_000 * buyPct / 100.0).toLong(),
                condition = condition,
                risk = when (ticker) {
                    "QQQ", "SMH" -> "기술주/금리 민감"
                    "TLT" -> "금리 상승 시 가격 하락"
                    "DBC" -> "원자재 사이클/롤오버 리스크"
                    else -> "장기 분할매수 가능"
                },
                chartPoints = live?.chartPoints ?: projectedChart(score)
            )
        }.sortedByDescending { it.score }
    }

    private fun scoreFromSeries(series: PriceSeries): Double {
        var score = 50.0
        if (series.latest > series.ma200) score += 15.0 else score -= 8.0
        if (series.latest > series.ma60) score += 8.0 else score -= 4.0
        score += (series.momentum12m * 45.0).coerceIn(-15.0, 25.0)
        score += (series.drawdown52w * 40.0).coerceIn(-18.0, 0.0)
        return score.coerceIn(0.0, 100.0)
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

    private fun scanRetirementAssets(): List<RetirementAssetSignal> {
        return listOf(
            RetirementAssetSignal("TIGER 미국S&P500", "TIGER 미국S&P500", "미국주식", "IRP/퇴직연금", false, false, 84.0, 25.0, "환노출/미국주식 변동성", projectedChart(84.0)),
            RetirementAssetSignal("KODEX 미국나스닥100TR", "KODEX 미국나스닥100TR", "미국성장", "IRP/퇴직연금", false, false, 80.0, 18.0, "금리·기술주 밸류에이션 민감", projectedChart(80.0)),
            RetirementAssetSignal("ACE 미국30년국채액티브", "ACE 미국30년국채액티브", "채권", "IRP/퇴직연금", false, false, 66.0, 15.0, "금리 상승 시 손실", projectedChart(66.0)),
            RetirementAssetSignal("KODEX 골드선물(H)", "KODEX 골드선물(H)", "원자재/금", "IRP/퇴직연금", false, false, 70.0, 8.0, "선물형·환헤지 구조 확인 필요", projectedChart(70.0)),
            RetirementAssetSignal("TIGER 원유선물Enhanced(H)", "TIGER 원유선물Enhanced(H)", "원자재/원유", "IRP/퇴직연금", false, false, 58.0, 3.0, "원유 선물 롤오버·변동성 큼", projectedChart(58.0)),
            RetirementAssetSignal("KODEX 레버리지", "KODEX 레버리지", "국내 레버리지", "일반/일부 계좌", true, false, 52.0, 0.0, "퇴직연금 가능 여부는 계좌별 확인. 변동성 과다", projectedChart(52.0)),
            RetirementAssetSignal("KODEX 인버스", "KODEX 인버스", "국내 인버스", "일반/일부 계좌", false, true, 48.0, 0.0, "장기보유 부적합. 헤지 목적만", projectedChart(48.0))
        ).sortedByDescending { it.score }
    }

    private fun scanKrShortStocks(): List<KrShortSignal> {
        return listOf(
            KrShortSignal("042700", "한미반도체", 82.4, 128_000, 123_000, 137_000, "거래량 증가 + 전고점 근접", projectedChart(82.4)),
            KrShortSignal("267260", "HD현대일렉트릭", 79.1, 410_000, 392_000, 444_000, "추세 유지 + 수급 후보", projectedChart(79.1)),
            KrShortSignal("010120", "LS ELECTRIC", 75.8, 212_000, 203_000, 229_000, "전력기기 테마 + 눌림 후 재돌파 후보", projectedChart(75.8))
        )
    }

    private fun strategyInfos(): List<StrategyInfo> = listOf(
        StrategyInfo("US_LONG_ETF", "미국 장기 ETF 분할매수", "미국 상장 ETF: 지수, 성장, 배당, 반도체, 채권, 금, 원자재", "1년~10년", listOf("월 기본매수 40%", "20/60/200일선 조정 시 추가매수", "환율 고평가 시 환전 분할 우선", "섹터 과열 시 신규매수 축소"), listOf("개별주 단타 금지", "고환율·고평가 동시 구간 추격 금지", "ETF별 비중 상한 관리"), "미국 ETF/환율 실데이터 1차 연결"),
        StrategyInfo("KR_RETIREMENT_MULTI_ASSET", "퇴직연금/IRP 멀티에셋 ETF", "국내상장 ETF: 주식, 채권, 금, 원유, 원자재, 달러, 레버리지/인버스 포함 표시", "3개월~10년", listOf("위험자산 70% 한도 점검", "주식·채권·원자재 분산", "레버리지/인버스는 별도 고위험 태그", "계좌별 실제 매수 가능 여부 최종 확인"), listOf("레버리지·인버스 장기보유 경고", "선물형 원자재 롤오버 리스크 표시", "퇴직연금 규정 변경 시 필터 갱신"), "멀티에셋 후보 확장. 국내 실데이터 연결 대기"),
        StrategyInfo("KR_SHORT_STOCK", "한국 단기 일반계좌", "거래대금 상위 개별주", "당일~10일", listOf("거래대금 급증", "전고점 돌파/돌파 직전", "진입·손절·목표 동시 산출", "실패 조건 명확할 때만 후보"), listOf("퇴직연금과 분리", "손절가 이탈 시 재해석 금지", "장대음봉/거래량 급감 시 축소"), "mock 후보. KRX/수급 연결 필요")
    )

    private fun validationLogs(now: String): List<StrategyValidationLog> = listOf(
        StrategyValidationLog(now, "US_LONG_ETF", "개선", "미국 ETF와 USD/KRW 실데이터 1차 연결. 실패 시 fallback", "다음: 거래량·AUM·비용 반영"),
        StrategyValidationLog(now, "KR_RETIREMENT_MULTI_ASSET", "주의", "원자재·레버리지·인버스 후보는 위험 태그 필요", "국내 ETF 실데이터 연결"),
        StrategyValidationLog(now, "KR_SHORT_STOCK", "주의", "실데이터 미연결로 수급 검증 불가", "KRX/KIS 또는 대체 데이터 연결"),
        StrategyValidationLog(now, "REVISION_POLICY", "정상", "매시간 검증하되 전략 수정은 주 1회 또는 임계값 충족 시", "과잉 최적화 방지")
    )

    private fun revisionPolicy(): StrategyRevisionPolicy = StrategyRevisionPolicy(
        validationFrequency = "매시간 성능·신호 품질 검증",
        revisionFrequency = "기본 주 1회, 긴급 오류는 즉시 수정",
        revisionThreshold = "동일 전략 5회 연속 손절 또는 기대값 -2%p 이하 악화 시 수정 후보",
        freezeRule = "수정 후 최소 20거래일 관찰. 매시간 파라미터 변경 금지"
    )

    private fun fetchYahooSeries(symbol: String, range: String): PriceSeries? {
        return try {
            val encoded = URLEncoder.encode(symbol, "UTF-8")
            val url = "https://query1.finance.yahoo.com/v8/finance/chart/$encoded?range=$range&interval=1d"
            val request = Request.Builder().url(url).header("User-Agent", "Mozilla/5.0").build()
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return null
                val body = response.body?.string() ?: return null
                parseYahoo(symbol, body)
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun parseYahoo(symbol: String, body: String): PriceSeries? {
        val root = JSONObject(body)
        val resultArray = root.getJSONObject("chart").optJSONArray("result") ?: return null
        if (resultArray.length() == 0) return null
        val result = resultArray.getJSONObject(0)
        val quote = result.getJSONObject("indicators").getJSONArray("quote").getJSONObject(0)
        val closes = quote.getJSONArray("close").toDoubleList().filter { it > 0.0 }
        if (closes.size < 30) return null
        val latest = closes.last()
        val ma20 = closes.takeLast(20).average()
        val ma60 = closes.takeLast(min(60, closes.size)).average()
        val ma200 = closes.takeLast(min(200, closes.size)).average()
        val high52w = closes.maxOrNull() ?: latest
        val first = closes.first()
        val momentum12m = if (first > 0) latest / first - 1.0 else 0.0
        val drawdown52w = if (high52w > 0) latest / high52w - 1.0 else 0.0
        return PriceSeries(symbol, latest.round2(), ma20.round2(), ma60.round2(), ma200.round2(), high52w.round2(), momentum12m, drawdown52w, compressChart(closes))
    }

    private fun JSONArray.toDoubleList(): List<Double> {
        val out = mutableListOf<Double>()
        for (i in 0 until length()) {
            if (!isNull(i)) out += optDouble(i, 0.0)
        }
        return out
    }

    private fun compressChart(values: List<Double>): List<ChartPoint> {
        if (values.isEmpty()) return emptyList()
        val labels = listOf("-12M", "-9M", "-6M", "-3M", "현재")
        val last = values.lastIndex
        val indexes = listOf(0, (last * 0.25).toInt(), (last * 0.5).toInt(), (last * 0.75).toInt(), last)
        val base = max(0.0001, values[indexes.first()])
        return indexes.mapIndexed { idx, index -> ChartPoint(labels[idx], (values[index] / base * 100.0).round1()) }
    }

    private fun projectedChart(score: Double): List<ChartPoint> {
        val drift = (score - 50.0) / 100.0
        return listOf(ChartPoint("현재", 100.0), ChartPoint("1M", (100.0 * (1 + drift * 0.25)).round1()), ChartPoint("3M", (100.0 * (1 + drift * 0.55)).round1()), ChartPoint("6M", (100.0 * (1 + drift * 0.95)).round1()), ChartPoint("12M", (100.0 * (1 + drift * 1.45)).round1()))
    }

    private fun Double.round1(): Double = kotlin.math.round(this * 10.0) / 10.0
    private fun Double.round2(): Double = kotlin.math.round(this * 100.0) / 100.0
}
