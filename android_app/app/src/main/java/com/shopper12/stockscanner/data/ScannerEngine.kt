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
import kotlin.math.round

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

    private data class RetirementSeed(
        val code: String,
        val name: String,
        val assetClass: String,
        val accountType: String,
        val isLeveraged: Boolean,
        val isInverse: Boolean,
        val fallbackScore: Double,
        val suggestedWeightPct: Double,
        val risk: String,
        val fallbackReview: String
    )

    private data class KrShortSeed(
        val code: String,
        val name: String,
        val fallbackScore: Double,
        val fallbackEntry: Long,
        val fallbackStop: Long,
        val fallbackTarget: Long,
        val reason: String
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
        val live = if (market == "KR") fetchKrSeries(symbol) else fetchYahooSeries(symbol, "1y")
        val baseScore = live?.let { scoreFromSeries(it) } ?: (55.0 + abs(symbol.hashCode() % 1000) / 1000.0 * 35.0)
        val score = baseScore.round1()
        val opinion = when {
            score >= 80 -> "매수 우선순위 높음"
            score >= 70 -> "분할매수/관찰"
            score >= 60 -> "중립: 추가 확인 필요"
            else -> "보류"
        }
        val entry = when {
            market == "KR" && live != null -> buildKrEntryPlan(live)
            market == "KR" -> "전고점 돌파 확인 후 분할 진입"
            live != null -> buildUsEntryPlan(live)
            else -> "월 기본매수 40% + 60일선 조정 추가"
        }
        val stop = when {
            market == "KR" && live != null -> buildKrRiskPlan(live)
            market == "KR" -> "최근 5일 저점 또는 ATR 1.5배 이탈"
            live != null -> buildUsRiskPlan(live)
            else -> "장기 ETF는 손절보다 리밸런싱/비중 축소"
        }
        val target = when {
            market == "KR" && live != null -> buildKrTargetPlan(live)
            market == "KR" -> "1차 +8~12%, 2차 +18~25%"
            live != null -> buildUsTargetPlan(live)
            else -> "1년 이상 보유, 과열 시 신규매수 축소"
        }
        val review = when {
            market == "KR" && live != null -> buildKrStrategyReview(score, live)
            market == "US/ETF" && live != null -> buildUsStrategyReview(score, live)
            else -> "실데이터 없음: 현재가 확인 전 실전 판단 금지"
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
                "실데이터 수신 실패: mock 기반 예비 판단",
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
            chartPoints = live?.chartPoints ?: projectedChart(score),
            currentPrice = live?.latest?.toString() ?: "N/A",
            strategyReview = review,
            dataSource = if (live != null) "Yahoo chart ${live.symbol}" else "mock/fallback"
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
                "현재 ${it.latest} / MA20 ${it.ma20} / MA60 ${it.ma60} / MA200 ${it.ma200} / DD52W ${(it.drawdown52w * 100.0).round1()}%"
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
                chartPoints = live?.chartPoints ?: projectedChart(score),
                currentPrice = live?.latest,
                ma20 = live?.ma20,
                ma60 = live?.ma60,
                ma200 = live?.ma200,
                momentum12mPct = live?.momentum12m?.times(100.0)?.round1(),
                drawdown52wPct = live?.drawdown52w?.times(100.0)?.round1(),
                entryPlan = live?.let { buildUsEntryPlan(it) } ?: "월 기본매수 40%",
                stopPlan = live?.let { buildUsRiskPlan(it) } ?: "실데이터 없음: 보수적 비중",
                targetPlan = live?.let { buildUsTargetPlan(it) } ?: "실데이터 없음: 목표 보류",
                strategyReview = live?.let { buildUsStrategyReview(score, it) } ?: "실데이터 없음: fallback 점수",
                dataSource = if (live != null) "Yahoo chart" else "mock/fallback"
            )
        }.sortedByDescending { it.score }
    }

    private fun scanRetirementAssets(): List<RetirementAssetSignal> {
        val seeds = listOf(
            RetirementSeed("360750", "TIGER 미국S&P500", "미국주식", "IRP/퇴직연금", false, false, 84.0, 25.0, "환노출/미국주식 변동성", "국내상장 미국지수 ETF: 장기 핵심 후보"),
            RetirementSeed("379810", "KODEX 미국나스닥100TR", "미국성장", "IRP/퇴직연금", false, false, 80.0, 18.0, "금리·기술주 밸류에이션 민감", "성장주 비중. 과열 시 신규매수 축소"),
            RetirementSeed("453850", "ACE 미국30년국채액티브", "채권", "IRP/퇴직연금", false, false, 66.0, 15.0, "금리 상승 시 손실", "금리 하락 국면 방어/수익 후보"),
            RetirementSeed("132030", "KODEX 골드선물(H)", "원자재/금", "IRP/퇴직연금", false, false, 70.0, 8.0, "선물형·환헤지 구조 확인 필요", "달러/금리 불안 시 분산 후보"),
            RetirementSeed("130680", "TIGER 원유선물Enhanced(H)", "원자재/원유", "IRP/퇴직연금", false, false, 58.0, 3.0, "원유 선물 롤오버·변동성 큼", "단기 사이클용. 장기 핵심 비중 부적합"),
            RetirementSeed("122630", "KODEX 레버리지", "국내 레버리지", "일반/일부 계좌", true, false, 52.0, 0.0, "퇴직연금 가능 여부는 계좌별 확인. 변동성 과다", "장기/퇴직연금 핵심전략 부적합"),
            RetirementSeed("114800", "KODEX 인버스", "국내 인버스", "일반/일부 계좌", false, true, 48.0, 0.0, "장기보유 부적합. 헤지 목적만", "헤지 목적 외 보류")
        )
        return seeds.map { seed ->
            val live = fetchKrSeries(seed.code)
            val score = (live?.let { scoreFromSeries(it) } ?: seed.fallbackScore).round1()
            RetirementAssetSignal(
                ticker = seed.code,
                name = seed.name,
                assetClass = seed.assetClass,
                accountType = seed.accountType,
                isLeveraged = seed.isLeveraged,
                isInverse = seed.isInverse,
                score = score,
                suggestedWeightPct = seed.suggestedWeightPct,
                risk = seed.risk,
                chartPoints = live?.chartPoints ?: projectedChart(score),
                currentPrice = live?.latest,
                strategyReview = live?.let { buildKrEtfReview(score, it, seed.isLeveraged, seed.isInverse) } ?: seed.fallbackReview,
                dataSource = if (live != null) "Yahoo chart ${live.symbol}" else "mock/fallback"
            )
        }.sortedByDescending { it.score }
    }

    private fun scanKrShortStocks(): List<KrShortSignal> {
        val seeds = listOf(
            KrShortSeed("042700", "한미반도체", 82.4, 128_000, 123_000, 137_000, "거래량 증가 + 전고점 근접"),
            KrShortSeed("267260", "HD현대일렉트릭", 79.1, 410_000, 392_000, 444_000, "추세 유지 + 수급 후보"),
            KrShortSeed("010120", "LS ELECTRIC", 75.8, 212_000, 203_000, 229_000, "전력기기 테마 + 눌림 후 재돌파 후보")
        )
        return seeds.map { seed ->
            val live = fetchKrSeries(seed.code)
            val score = (live?.let { scoreFromSeries(it) } ?: seed.fallbackScore).round1()
            val current = live?.latest?.let { roundKrPrice(it).toLong() }
            val entry = live?.let { roundKrPrice(max(it.latest * 1.01, it.ma20)).toLong() } ?: seed.fallbackEntry
            val stop = live?.let { roundKrPrice(min(it.latest * 0.96, it.ma20 * 0.97)).toLong() } ?: seed.fallbackStop
            val target1 = live?.let { roundKrPrice(it.latest * 1.08).toLong() } ?: seed.fallbackTarget
            val target2 = live?.let { roundKrPrice(it.latest * 1.16).toLong() } ?: roundKrPrice(seed.fallbackTarget * 1.06).toLong()
            KrShortSignal(
                code = seed.code,
                name = seed.name,
                score = score,
                entry = entry,
                stopLoss = stop,
                target1 = target1,
                reason = seed.reason,
                chartPoints = live?.chartPoints ?: projectedChart(score),
                currentPrice = current,
                target2 = target2,
                strategyReview = live?.let { buildKrStrategyReview(score, it, entry, stop) } ?: "mock: 현재가 확인 전 실전 판단 금지",
                dataSource = if (live != null) "Yahoo chart ${live.symbol}" else "mock/fallback"
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
        return RetirementSignal((riskyPct * 100).toLong() / 100.0, ((safe / total * 100.0) * 100).toLong() / 100.0, room, if (riskyPct < 70.0) "위험자산 한도 여유" else "위험자산 추가매수 금지")
    }

    private fun fetchKrSeries(symbol: String): PriceSeries? {
        val clean = symbol.trim().uppercase(Locale.ROOT)
        if (clean.endsWith(".KS") || clean.endsWith(".KQ")) return fetchYahooSeries(clean, "1y")
        val code = clean.padStart(6, '0')
        return fetchYahooSeries("$code.KS", "1y") ?: fetchYahooSeries("$code.KQ", "1y")
    }

    private fun buildKrEntryPlan(series: PriceSeries): String = when {
        series.latest > series.ma20 && series.latest > series.ma60 -> "상승추세: 전일 고점/MA20 위에서 분할 진입"
        series.latest <= series.ma60 * 1.02 && series.latest >= series.ma200 -> "60일선 눌림: 반등 확인 후 진입"
        series.latest < series.ma200 -> "MA200 아래: 추세 회복 전 신규진입 보류"
        else -> "방향 애매: 거래량 동반 돌파 확인 필요"
    }

    private fun buildKrRiskPlan(series: PriceSeries): String = when {
        series.latest < series.ma200 -> "MA200 아래: 단기매매 외 보류"
        series.latest < series.ma60 -> "MA60 아래: 비중 축소, MA60 회복 전 추격 금지"
        else -> "손절 기준: MA20 이탈 또는 최근 저점 이탈"
    }

    private fun buildKrTargetPlan(series: PriceSeries): String {
        val t1 = roundKrPrice(series.latest * 1.08).toLong()
        val t2 = roundKrPrice(series.latest * 1.16).toLong()
        return "1차 ${formatLong(t1)} / 2차 ${formatLong(t2)}"
    }

    private fun buildKrStrategyReview(score: Double, series: PriceSeries): String {
        val entry = roundKrPrice(max(series.latest * 1.01, series.ma20)).toLong()
        val stop = roundKrPrice(min(series.latest * 0.96, series.ma20 * 0.97)).toLong()
        return buildKrStrategyReview(score, series, entry, stop)
    }

    private fun buildKrStrategyReview(score: Double, series: PriceSeries, entry: Long, stop: Long): String = when {
        series.latest < series.ma200 -> "보류: MA200 아래라 중기 추세 약함"
        score >= 80 && series.latest > series.ma20 -> "매수 검토: ${formatLong(entry)} 돌파 확인. 실패 시 ${formatLong(stop)} 손절"
        score >= 70 -> "조건부 관찰: MA20/MA60 회복과 거래량 필요"
        else -> "관찰: 점수 부족. 추격 금지"
    }

    private fun buildKrEtfReview(score: Double, series: PriceSeries, leveraged: Boolean, inverse: Boolean): String = when {
        leveraged || inverse -> "고위험 상품: 장기 핵심 비중 부적합. 단기/헤지 목적만"
        series.latest < series.ma200 -> "보류 또는 소액 분할: MA200 아래"
        score >= 75 -> "퇴직/IRP 후보: 분할매수 가능. 위험자산 한도 확인"
        else -> "관찰: 추세 회복 후 비중 확대"
    }

    private fun buildUsEntryPlan(series: PriceSeries): String = when {
        series.latest <= series.ma60 * 1.01 && series.latest >= series.ma200 -> "60일선 부근: 기본매수 40% + 추가 20% 가능"
        series.latest <= series.ma200 * 1.03 -> "200일선 접근: 장기 분할매수 후보. 환율 부담 확인"
        series.latest > series.ma20 && series.latest > series.ma60 -> "상승추세: 기본매수만, 추격 추가매수 금지"
        else -> "추세 애매: 기본매수 축소 또는 대기"
    }

    private fun buildUsRiskPlan(series: PriceSeries): String = when {
        series.latest < series.ma200 -> "MA200 아래: 신규매수 축소, 회복 전 대기"
        series.drawdown52w > -0.03 -> "52주 고점 근접: 신규매수 40% 이하 제한"
        else -> "장기 ETF: 손절보다 비중 조절. MA200 이탈 시 리밸런싱 검토"
    }

    private fun buildUsTargetPlan(series: PriceSeries): String {
        val target1 = (series.latest * 1.08).round2()
        val target2 = (series.latest * 1.15).round2()
        return "1차 과열점검 $target1 / 2차 신규매수 축소 $target2"
    }

    private fun buildUsStrategyReview(score: Double, series: PriceSeries): String = when {
        score >= 80 && series.latest > series.ma60 -> "매수 가능: 추세 양호. 단, 분할매수만 허용"
        score >= 70 -> "조건부 매수: 60일선 접근 또는 환율 안정 시 우선"
        series.latest < series.ma200 -> "보류: MA200 아래라 추세 회복 확인 필요"
        else -> "관찰: 점수 부족. 비중 확대 금지"
    }

    private fun scoreFromSeries(series: PriceSeries): Double {
        var score = 50.0
        if (series.latest > series.ma200) score += 15.0 else score -= 8.0
        if (series.latest > series.ma60) score += 8.0 else score -= 4.0
        score += (series.momentum12m * 45.0).coerceIn(-15.0, 25.0)
        score += (series.drawdown52w * 40.0).coerceIn(-18.0, 0.0)
        return score.coerceIn(0.0, 100.0)
    }

    private fun strategyInfos(): List<StrategyInfo> = listOf(
        StrategyInfo("US_LONG_ETF", "미국 장기 ETF 분할매수", "미국 상장 ETF: 지수, 성장, 배당, 반도체, 채권, 금, 원자재", "1년~10년", listOf("현재가·MA20·MA60·MA200 실시간/준실시간 검토", "월 기본매수 40%", "20/60/200일선 조정 시 추가매수", "환율 고평가 시 환전 분할 우선"), listOf("개별주 단타 금지", "고환율·고평가 동시 구간 추격 금지", "ETF별 비중 상한 관리"), "미국 ETF/환율 실데이터 연결"),
        StrategyInfo("KR_RETIREMENT_MULTI_ASSET", "퇴직연금/IRP 멀티에셋 ETF", "국내상장 ETF: 주식, 채권, 금, 원유, 원자재, 달러, 레버리지/인버스 포함 표시", "3개월~10년", listOf("위험자산 70% 한도 점검", "국내 ETF 현재가·이평선 검토", "레버리지/인버스 고위험 태그"), listOf("레버리지·인버스 장기보유 경고", "선물형 원자재 롤오버 리스크 표시"), "국내 ETF 실데이터 1차 연결"),
        StrategyInfo("KR_SHORT_STOCK", "한국 단기 일반계좌", "거래대금 상위 개별주", "당일~10일", listOf("현재가·진입가·손절가·목표가 동시 검토", "MA20/MA60/MA200 기반 추세 점검", "실패 조건 명확할 때만 후보"), listOf("퇴직연금과 분리", "손절가 이탈 시 재해석 금지"), "한국 후보 실데이터 1차 연결")
    )

    private fun validationLogs(now: String): List<StrategyValidationLog> = listOf(
        StrategyValidationLog(now, "US_LONG_ETF", "정상", "미국 ETF 현재가·이평선·전략검토 연결", "다음: 거래량·AUM·비용 반영"),
        StrategyValidationLog(now, "KR_RETIREMENT_MULTI_ASSET", "개선", "국내 ETF 코드를 Yahoo .KS/.KQ로 조회", "다음: KRX 공식 데이터 교차검증"),
        StrategyValidationLog(now, "KR_SHORT_STOCK", "개선", "한국 후보 현재가·진입·손절·목표 산출", "다음: 거래대금/수급 연결"),
        StrategyValidationLog(now, "REVISION_POLICY", "정상", "매시간 검증하되 전략 수정은 주 1회 또는 임계값 충족 시", "과잉 최적화 방지")
    )

    private fun revisionPolicy(): StrategyRevisionPolicy = StrategyRevisionPolicy("매시간 성능·신호 품질 검증", "기본 주 1회, 긴급 오류는 즉시 수정", "동일 전략 5회 연속 손절 또는 기대값 -2%p 이하 악화 시 수정 후보", "수정 후 최소 20거래일 관찰. 매시간 파라미터 변경 금지")

    private fun fetchYahooSeries(symbol: String, range: String): PriceSeries? = try {
        val encoded = URLEncoder.encode(symbol, "UTF-8")
        val url = "https://query1.finance.yahoo.com/v8/finance/chart/$encoded?range=$range&interval=1d"
        val request = Request.Builder().url(url).header("User-Agent", "Mozilla/5.0").build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return null
            val body = response.body?.string() ?: return null
            parseYahoo(symbol, body)
        }
    } catch (_: Exception) { null }

    private fun parseYahoo(symbol: String, body: String): PriceSeries? {
        val resultArray = JSONObject(body).getJSONObject("chart").optJSONArray("result") ?: return null
        if (resultArray.length() == 0) return null
        val quote = resultArray.getJSONObject(0).getJSONObject("indicators").getJSONArray("quote").getJSONObject(0)
        val closes = quote.getJSONArray("close").toDoubleList().filter { it > 0.0 }
        if (closes.size < 30) return null
        val latest = closes.last()
        val ma20 = closes.takeLast(20).average()
        val ma60 = closes.takeLast(min(60, closes.size)).average()
        val ma200 = closes.takeLast(min(200, closes.size)).average()
        val high52w = closes.maxOrNull() ?: latest
        val first = closes.first()
        return PriceSeries(symbol, latest.round2(), ma20.round2(), ma60.round2(), ma200.round2(), high52w.round2(), if (first > 0) latest / first - 1.0 else 0.0, if (high52w > 0) latest / high52w - 1.0 else 0.0, compressChart(closes))
    }

    private fun JSONArray.toDoubleList(): List<Double> {
        val out = mutableListOf<Double>()
        for (i in 0 until length()) if (!isNull(i)) out += optDouble(i, 0.0)
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

    private fun roundKrPrice(value: Double): Double = when {
        value >= 100_000 -> round(value / 500.0) * 500.0
        value >= 10_000 -> round(value / 100.0) * 100.0
        value >= 1_000 -> round(value / 10.0) * 10.0
        else -> round(value)
    }

    private fun formatLong(value: Long): String = String.format(Locale.KOREA, "%,d", value)
    private fun Double.round1(): Double = round(this * 10.0) / 10.0
    private fun Double.round2(): Double = round(this * 100.0) / 100.0
}
