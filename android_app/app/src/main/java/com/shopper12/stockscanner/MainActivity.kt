package com.shopper12.stockscanner

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.shopper12.stockscanner.data.ScannerEngine
import com.shopper12.stockscanner.model.ScanResult
import com.shopper12.stockscanner.notify.TelegramNotifier
import com.shopper12.stockscanner.work.WorkScheduler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { StockScannerScreen(this) }
    }
}

@Composable
fun StockScannerScreen(activity: ComponentActivity) {
    var result by remember { mutableStateOf<ScanResult?>(ScannerEngine().runScan()) }
    var status by remember { mutableStateOf("대기") }

    MaterialTheme {
        Scaffold(
            topBar = { TopBar() }
        ) { padding ->
            LazyColumn(
                modifier = Modifier
                    .padding(padding)
                    .padding(16.dp)
                    .fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            activity.lifecycleScope.launch {
                                status = "스캔 중"
                                result = withContext(Dispatchers.Default) { ScannerEngine().runScan() }
                                status = "스캔 완료"
                            }
                        }) { Text("수동 스캔") }
                        Button(onClick = {
                            activity.lifecycleScope.launch {
                                val scan = result ?: ScannerEngine().runScan()
                                val sent = withContext(Dispatchers.IO) { TelegramNotifier().send(scan) }
                                status = if (sent) "텔레그램 전송 완료" else "텔레그램 전송 실패"
                            }
                        }) { Text("텔레그램 전송") }
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = {
                            WorkScheduler.schedule(activity.applicationContext)
                            status = "자동 스캔 예약 완료"
                        }) { Text("자동 실행 켜기") }
                        OutlinedButton(onClick = {
                            WorkScheduler.cancel(activity.applicationContext)
                            status = "자동 실행 중지"
                        }) { Text("자동 실행 끄기") }
                    }
                    Text("상태: $status", style = MaterialTheme.typography.bodyMedium)
                }

                result?.let { scan ->
                    item { SummaryCard(scan) }
                    item { SectionTitle("미국 장기 ETF") }
                    items(scan.usEtfs) { etf ->
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp)) {
                                Text("${etf.ticker} - ${etf.name}", style = MaterialTheme.typography.titleMedium)
                                Text("점수 ${etf.score} / 이번달 매수 ${etf.buyPct}% (${etf.buyKrw}원)")
                                Text(etf.condition)
                                Text("리스크: ${etf.risk}")
                            }
                        }
                    }
                    item { SectionTitle("한국 단기 일반계좌 후보") }
                    items(scan.krShortStocks) { stock ->
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp)) {
                                Text("${stock.name} (${stock.code})", style = MaterialTheme.typography.titleMedium)
                                Text("점수 ${stock.score} / 진입 ${stock.entry} / 손절 ${stock.stopLoss} / 목표 ${stock.target1}")
                                Text(stock.reason)
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TopBar() {
    TopAppBar(title = { Text("Stock Scanner") })
}

@Composable
fun SummaryCard(scan: ScanResult) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("기준시각: ${scan.createdAt}", style = MaterialTheme.typography.bodySmall)
            Text("환율: USD/KRW ${scan.fx.usdKrw} / 판단 ${scan.fx.action}", style = MaterialTheme.typography.titleMedium)
            Text("권장 환전금액: ${scan.fx.suggestedConversionKrw}원")
            Text("퇴직연금: 위험자산 ${scan.retirement.riskyPct}% / ${scan.retirement.status}")
            Text("위험자산 추가여력: ${scan.retirement.riskyBuyRoomKrw}원")
        }
    }
}

@Composable
fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleLarge)
}
