package com.shopper12.stockscanner.data

import com.shopper12.stockscanner.model.*
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max

class ScannerEngine {
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
        val base = abs(symbol.hashCode() % 1000) / 1000.0
        val score = (55.0 + base * 35.0).round1()
        val entry = if (market == "KR") "전고점 돌파 확인 후 분할 진입" else "월 기본매수 40% + 60일선 조정 추가"
        val stop = if (market == "KR") "최근 5일 저점 또는 ATR 1.5배 이탈" else "장기 ETF는 손절보다 리밸런싱/비중 축소"
        val target = if (market == "KR") "1차 +8~12%, 2차 +18~25%" else "1년 이상 보유, 과열 시 신규매수 축소"
        val opinion = when {
            score >= 80 -> "관심 우선순위 높음"
            score >= 70 -> "조건부 관찰"
            score >= 60 -> "중립: 추가 확인 필요"
            else -> "보류"
        }
        return ManualAnalysis(
            symbol = symbol,
            market = market,
            score = score,
            opinion = opinion,
            entry = entry,
            stop = stop,
            target = target,
            reasons = listOf(
                "모멘텀 점수 ${score.round1()} 기준",
                "거래량/추세/환율/자산군 리스크를 분리 판단",
                "실데이터 연결 전까지는 mock 기반 예비 판단",
                "실전 적용 전 현재가·거래대금·뉴스 확인 필요"
            ),
            chartPoints = projectedChart(score)
        )
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
            Triple("GLD", "SPDR Gold Shares", 69.1),
            Triple("TLT", "iShares 20+ Year Treasury Bond ETF", 62.8),
            Triple("DBC", "Invesco DB Commodity Index", 61.5)
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
                risk = when (ticker) {
                    "QQQ", "SMH" -> "기술주/금리 민감"
                    "TLT" -> "금리 상승 시 가격 하락"
                    "DBC" -> "원자재 사이클/롤오버 리스크"
                    else -> "장기 분할매수 가능"
                },
                chartPoints = projectedChart(score)
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
        StrategyInfo(
            id = "US_LONG_ETF",
            name = "미국 장기 ETF 분할매수",
            target = "미국 상장 ETF: 지수, 성장, 배당, 반도체, 채권, 금, 원자재",
            horizon = "1년~10년",
            rules = listOf("월 기본매수 40%", "20/60/200일선 조정 시 추가매수", "환율 고평가 시 환전 분할 우선", "섹터 과열 시 신규매수 축소"),
            riskRules = listOf("개별주 단타 금지", "고환율·고평가 동시 구간 추격 금지", "ETF별 비중 상한 관리"),
            currentStatus = "장기 적립 유효, 기술주 과열 여부 감시"
        ),
        StrategyInfo(
            id = "KR_RETIREMENT_MULTI_ASSET",
            name = "퇴직연금/IRP 멀티에셋 ETF",
            target = "국내상장 ETF: 주식, 채권, 금, 원유, 원자재, 달러, 레버리지/인버스 포함 표시",
            horizon = "3개월~10년",
            rules = listOf("위험자산 70% 한도 점검", "주식·채권·원자재 분산", "레버리지/인버스는 별도 고위험 태그", "계좌별 실제 매수 가능 여부 최종 확인"),
            riskRules = listOf("레버리지·인버스 장기보유 경고", "선물형 원자재 롤오버 리스크 표시", "퇴직연금 규정 변경 시 필터 갱신"),
            currentStatus = "멀티에셋 후보 확장 필요"
        ),
        StrategyInfo(
            id = "KR_SHORT_STOCK",
            name = "한국 단기 일반계좌",
            target = "거래대금 상위 개별주",
            horizon = "당일~10일",
            rules = listOf("거래대금 급증", "전고점 돌파/돌파 직전", "진입·손절·목표 동시 산출", "실패 조건 명확할 때만 후보"),
            riskRules = listOf("퇴직연금과 분리", "손절가 이탈 시 재해석 금지", "장대음봉/거래량 급감 시 축소"),
            currentStatus = "mock 후보. 실시간 KRX/수급 연결 필요"
        )
    )

    private fun validationLogs(now: String): List<StrategyValidationLog> = listOf(
        StrategyValidationLog(now, "US_LONG_ETF", "정상", "환율 부담과 ETF 매수비중 분리 계산", "전략 유지"),
        StrategyValidationLog(now, "KR_RETIREMENT_MULTI_ASSET", "주의", "원자재·레버리지·인버스 후보는 위험 태그 필요", "후보군 확장 및 위험표시 강화"),
        StrategyValidationLog(now, "KR_SHORT_STOCK", "주의", "실데이터 미연결로 수급 검증 불가", "실데이터 API 연결 전 실전 판단 금지"),
        StrategyValidationLog(now, "REVISION_POLICY", "정상", "매시간 검증하되 전략 수정은 주 1회 또는 임계값 충족 시", "과잉 최적화 방지")
    )

    private fun revisionPolicy(): StrategyRevisionPolicy = StrategyRevisionPolicy(
        validationFrequency = "매시간 성능·신호 품질 검증",
        revisionFrequency = "기본 주 1회, 긴급 오류는 즉시 수정",
        revisionThreshold = "동일 전략 5회 연속 손절 또는 기대값 -2%p 이하 악화 시 수정 후보",
        freezeRule = "수정 후 최소 20거래일 관찰. 매시간 파라미터 변경 금지"
    )

    private fun projectedChart(score: Double): List<ChartPoint> {
        val drift = (score - 50.0) / 100.0
        return listOf(
            ChartPoint("현재", 100.0),
            ChartPoint("1M", (100.0 * (1 + drift * 0.25)).round1()),
            ChartPoint("3M", (100.0 * (1 + drift * 0.55)).round1()),
            ChartPoint("6M", (100.0 * (1 + drift * 0.95)).round1()),
            ChartPoint("12M", (100.0 * (1 + drift * 1.45)).round1())
        )
    }

    private fun Double.round1(): Double = kotlin.math.round(this * 10.0) / 10.0
}
