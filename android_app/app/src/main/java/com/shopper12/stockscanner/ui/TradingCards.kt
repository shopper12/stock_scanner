package com.shopper12.stockscanner.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.shopper12.stockscanner.model.*
import java.text.NumberFormat
import java.util.Locale

@Composable
fun UsEtfReviewCard(etf: UsEtfSignal) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text("${etf.ticker} - ${etf.name}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("현재가 ${etf.currentPrice ?: "N/A"} / ${etf.dataSource}")
                    Text("점수 ${etf.score} / 이번달 매수 ${etf.buyPct}% / 금액 ${krw(etf.buyKrw)}")
                }
                AssistChip(onClick = {}, label = { Text("${etf.score}") })
            }
            LinearProgressIndicator(
                progress = { (etf.score / 100.0).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth()
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                SmallBox("MA20", etf.ma20?.toString() ?: "-")
                SmallBox("MA60", etf.ma60?.toString() ?: "-")
                SmallBox("MA200", etf.ma200?.toString() ?: "-")
            }
            ProjectionBars(etf.chartPoints)
            Text("전략검토: ${etf.strategyReview}")
            Text("진입: ${etf.entryPlan}")
            Text("손절/축소: ${etf.stopPlan}")
            Text("목표: ${etf.targetPlan}")
            Text("리스크: ${etf.risk}")
        }
    }
}

@Composable
fun KrShortReviewCard(stock: KrShortSignal) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text("${stock.name} (${stock.code})", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("현재가 ${stock.currentPrice ?: "N/A"} / ${stock.dataSource}")
                    Text("점수 ${stock.score} / ${stock.reason}")
                }
                AssistChip(onClick = {}, label = { Text("${stock.score}") })
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                PriceBox("진입", krw(stock.entry), Modifier.weight(1f))
                PriceBox("손절", krw(stock.stopLoss), Modifier.weight(1f))
                PriceBox("목표1", krw(stock.target1), Modifier.weight(1f))
            }
            stock.target2?.let { Text("목표2: ${krw(it)}") }
            ProjectionBars(stock.chartPoints)
            Text("전략검토: ${stock.strategyReview}")
            Text("실패 조건: 진입 실패 후 손절가 이탈")
        }
    }
}

@Composable
fun ManualReviewCard(analysis: ManualAnalysis) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text("${analysis.symbol} (${analysis.market})", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("현재가 ${analysis.currentPrice} / ${analysis.dataSource}")
                    Text(analysis.opinion)
                }
                AssistChip(onClick = {}, label = { Text("점수 ${analysis.score}") })
            }
            Text("전략검토: ${analysis.strategyReview}")
            Text("진입: ${analysis.entry}")
            Text("손절/축소: ${analysis.stop}")
            Text("목표/관리: ${analysis.target}")
            analysis.reasons.forEach { Text("• $it") }
            ProjectionBars(analysis.chartPoints)
        }
    }
}

@Composable
fun RetirementReviewCard(asset: RetirementAssetSignal) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(asset.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("${asset.assetClass} / ${asset.accountType}")
                }
                AssistChip(onClick = {}, label = { Text("${asset.score}") })
            }
            Text("추천비중: ${asset.suggestedWeightPct}%")
            Text("전략검토: ${asset.strategyReview}")
            Text("레버리지: ${if (asset.isLeveraged) "예" else "아니오"} / 인버스: ${if (asset.isInverse) "예" else "아니오"}")
            Text("리스크: ${asset.risk}")
            ProjectionBars(asset.chartPoints)
        }
    }
}

@Composable
fun InfoBox(title: String, lines: List<String>) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            lines.forEach { Text("• $it") }
        }
    }
}

@Composable
fun HeaderBox(title: String, subtitle: String, body: String) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(subtitle)
            Text(body)
        }
    }
}

@Composable
fun MetricBox(title: String, value: String, label: String, modifier: Modifier = Modifier) {
    ElevatedCard(modifier, shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.labelLarge)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun SmallBox(label: String, value: String) {
    Card(Modifier.weight(1f), shape = RoundedCornerShape(12.dp)) {
        Column(Modifier.padding(8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, style = MaterialTheme.typography.labelSmall)
            Text(value, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun PriceBox(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier, shape = RoundedCornerShape(12.dp)) {
        Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, style = MaterialTheme.typography.labelMedium)
            Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
fun ProjectionBars(points: List<ChartPoint>) {
    if (points.isEmpty()) return
    val maxValue = points.maxOf { it.value }.coerceAtLeast(1.0)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("예상/가격 경로", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
        points.forEach { point ->
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text(point.label, modifier = Modifier.width(42.dp), style = MaterialTheme.typography.bodySmall)
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(12.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(8.dp))
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth((point.value / maxValue).toFloat().coerceIn(0.05f, 1f))
                            .height(12.dp)
                            .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(8.dp))
                    )
                }
                Text(" ${point.value}", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

fun krw(value: Long): String = NumberFormat.getNumberInstance(Locale.KOREA).format(value) + "원"
