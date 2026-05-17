package com.shopper12.stockscanner.model

data class ScanResult(
    val createdAt: String,
    val fx: FxSignal,
    val usEtfs: List<UsEtfSignal>,
    val retirement: RetirementSignal,
    val retirementAssets: List<RetirementAssetSignal>,
    val krShortStocks: List<KrShortSignal>,
    val strategies: List<StrategyInfo>,
    val validationLogs: List<StrategyValidationLog>,
    val revisionPolicy: StrategyRevisionPolicy
)

data class FxSignal(
    val usdKrw: Double,
    val ma60: Double,
    val action: String,
    val suggestedConversionKrw: Long,
    val reason: String
)

data class UsEtfSignal(
    val ticker: String,
    val name: String,
    val score: Double,
    val buyPct: Double,
    val buyKrw: Long,
    val condition: String,
    val risk: String,
    val chartPoints: List<ChartPoint> = emptyList()
)

data class RetirementSignal(
    val riskyPct: Double,
    val safePct: Double,
    val riskyBuyRoomKrw: Long,
    val status: String
)

data class RetirementAssetSignal(
    val ticker: String,
    val name: String,
    val assetClass: String,
    val accountType: String,
    val isLeveraged: Boolean,
    val isInverse: Boolean,
    val score: Double,
    val suggestedWeightPct: Double,
    val risk: String,
    val chartPoints: List<ChartPoint> = emptyList()
)

data class KrShortSignal(
    val code: String,
    val name: String,
    val score: Double,
    val entry: Long,
    val stopLoss: Long,
    val target1: Long,
    val reason: String,
    val chartPoints: List<ChartPoint> = emptyList()
)

data class StrategyInfo(
    val id: String,
    val name: String,
    val target: String,
    val horizon: String,
    val rules: List<String>,
    val riskRules: List<String>,
    val currentStatus: String
)

data class StrategyValidationLog(
    val time: String,
    val strategyId: String,
    val result: String,
    val finding: String,
    val action: String
)

data class StrategyRevisionPolicy(
    val validationFrequency: String,
    val revisionFrequency: String,
    val revisionThreshold: String,
    val freezeRule: String
)

data class ManualAnalysis(
    val symbol: String,
    val market: String,
    val score: Double,
    val opinion: String,
    val entry: String,
    val stop: String,
    val target: String,
    val reasons: List<String>,
    val chartPoints: List<ChartPoint>
)

data class ChartPoint(
    val label: String,
    val value: Double
)
