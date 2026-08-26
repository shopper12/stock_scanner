package com.stockscanner

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

private const val HOME_UPDATE_PAGE_URL = "https://github.com/shopper12/stock_scanner/releases/tag/app-latest"

class HomeActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { HomeScreen() } }
    }
}

@Composable
private fun HomeScreen() {
    val context = LocalContext.current
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("오늘 돈 보기", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Text("분석부터 하지 말고, 오늘의 결론부터 확인하세요.", style = MaterialTheme.typography.bodyLarge)

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("1. 오늘 추천 4개", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text("자동작업 금융 브리핑의 최신 추천, 진입·손절·목표를 가장 먼저 봅니다.")
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = { context.startActivity(Intent(context, BotCardsActivity::class.java)) },
                ) { Text("오늘 추천부터 보기") }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text("오늘 원칙", fontWeight = FontWeight.Bold)
                Text("• 진입구간 밖 추격 금지")
                Text("• 손절 없는 매수 금지")
                Text("• 새 종목 찾기 전에 기존 4개부터 확인")
            }
        }

        Text("필요할 때만", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { context.startActivity(Intent(context, MainActivity::class.java)) },
        ) { Text("상세 스캐너 · 종목 검색 · 백테스트") }
        OutlinedButton(
            modifier = Modifier.fillMaxWidth(),
            onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(HOME_UPDATE_PAGE_URL))) },
        ) { Text("앱 업데이트") }
    }
}
