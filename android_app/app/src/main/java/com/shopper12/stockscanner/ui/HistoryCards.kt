package com.shopper12.stockscanner.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.shopper12.stockscanner.data.HistoryStore

@Composable
fun HistoryScreen(
    items: List<HistoryStore.HistoryItem>,
    onClear: () -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            HeaderBox(
                title = "전략 기록",
                subtitle = "최근 ${items.size}개",
                body = "수동 스캔, 자동 스캔, 직접 종목 판단 기록을 저장한다."
            )
        }
        item {
            OutlinedButton(onClick = onClear, modifier = Modifier.fillMaxWidth()) {
                Text("기록 삭제")
            }
        }
        if (items.isEmpty()) {
            item { InfoBox("기록 없음", listOf("수동 스캔 또는 직접 판단을 실행하면 기록이 쌓인다.")) }
        } else {
            items(items) { item -> HistoryCard(item) }
        }
    }
}

@Composable
fun HistoryCard(item: HistoryStore.HistoryItem) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(item.type, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                Text(item.time, style = MaterialTheme.typography.bodySmall)
            }
            Text(item.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("판단: ${item.decision}")
            Text("가격: ${item.price}")
            Text("점수: ${item.score} / 출처: ${item.source}")
        }
    }
}
