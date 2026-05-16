package com.shopper12.stockscanner.model

data class ScanResult(
    val createdAt: String,
    val fx: FxSignal,
    val usEtfs: List<UsEtfSignal>,
    val retirement: RetirementSignal,
    val krShortStocks: List<KrShortSignal>
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
    val risk: String
)

data class RetirementSignal(
    val riskyPct: Double,
    val safePct: Double,
    val riskyBuyRoomKrw: Long,
    val status: String
)

data class KrShortSignal(
    val code: String,
    val name: String,
    val score: Double,
    val entry: Long,
    val stopLoss: Long,
    val target1: Long,
    val reason: String
)
