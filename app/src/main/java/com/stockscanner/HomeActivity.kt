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
        Text("Stock Scanner", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        InfoCard("메뉴를 선택하세요. 현재 후보는 기본 스캐너에서, 자동작업 브리핑 추천은 봇 추천 화면에서 확인합니다.")
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = { context.startActivity(Intent(context, MainActivity::class.java)) },
        ) { Text("현재 후보 / 종목 검색 / 백테스트") }
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = { context.startActivity(Intent(context, BotCardsActivity::class.java)) },
        ) { Text("봇 추천 / 자동작업 브리핑 종목") }
        Button(
            modifier = Modifier.fillMaxWidth(),
            onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(HOME_UPDATE_PAGE_URL))) },
        ) { Text("업데이트 / APK") }
    }
}

@Composable
private fun InfoCard(text: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(12.dp))
    }
}
