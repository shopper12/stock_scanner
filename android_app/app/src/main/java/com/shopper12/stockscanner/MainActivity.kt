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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.shopper12.stockscanner.data.ScannerEngine
import com.shopper12.stockscanner.model.*
import com.shopper12.stockscanner.notify.TelegramNotifier
import com.shopper12.stockscanner.work.WorkScheduler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.NumberFormat
import java.util.Locale

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
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("요약", "미국 ETF", "환율", "퇴직연금", "한국 단기")

    MaterialTheme {
        Scaffold(topBar = { TopBar() }) { padding ->
            Column(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
            ) {
                ActionPanel(
                    status = status,
                    onScan = {
                        activity.lifecycleScope.launch {
                            status = "스캔 중"
                            result = withContext(Dispatchers.Default) { ScannerEngine().runScan() }
                            status = "스캔 완료"
                        }
                    },
                    onTelegram = {
                        activity.lifecycleScope.launch {
                            val scan = result ?: ScannerEngine().runScan()
                            val sent = withContext(Dispatchers.IO) { TelegramNotifier().send(scan) }
                            status = if (sent) "텔레그램 전송 완료" else "텔레그램 전송 실패"
                        }
                    },
                    onScheduleOn = {
                        WorkScheduler.schedule(activity.applicationContext)
                        status = "자동 스캔 예약 완료: 15분 주기"
                    },
                    onScheduleOff = {
                        WorkScheduler.cancel(activity.applicationContext)
                        status = "자동 실행 중지"
                    }
                )

                ScrollableTabRow(selectedTabIndex = selectedTab, edgePadding = 12.dp) {
                    tabs.forEachIndexed { index, title ->
                        Tab(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            text = { Text(title) }
                        )
                    }
                }

                result?.let { scan ->
                    when (selectedTab) {
                        0 -> SummaryTab(scan)
                        1 -> UsEtfTab(scan.usEtfs)
                        2 -> FxTab(scan.fx)
                        3 -> RetirementTab(scan.retirement)
                        4 -> KrShortTab(scan.krShortStocks)
                    }
                } ?: EmptyState()
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
fun ActionPanel(
    status: String,
    onScan: () -> Unit,
    onTelegram: () -> Unit,
    onScheduleOn: () -> Unit,
    onScheduleOff: () -> Unit
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(12.dp),
        shape = RoundedCornerShape(18.dp)
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("실행 제어", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("상태: $status", style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onScan, modifier = Modifier.weight(1f)) { Text("수동 스캔") }
                Button(onClick = onTelegram, modifier = Modifier.weight(1f)) { Text("텔레그램") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onScheduleOn, modifier = Modifier.weight(1f)) { Text("자동 켜기") }
                OutlinedButton(onClick = onScheduleOff, modifier = Modifier.weight(1f)) { Text("자동 끄기") }
            }
        }
    }
}

@Composable
fun SummaryTab(scan: ScanResult) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            HeaderCard(
                title = "오늘 요약",
                subtitle = "기준시각: ${scan.createdAt}",
                body = "환율 ${scan.fx.action} / 미국 ETF 상위 ${scan.usEtfs.firstOrNull()?.ticker ?: "-"} / 단기 후보 ${scan.krShortStocks.size}개"
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MiniMetricCard("USD/KRW", scan.fx.usdKrw.toString(), scan.fx.action, Modifier.weight(1f))
                MiniMetricCard("환전", krw(scan.fx.suggestedConversionKrw), "권장금액", Modifier.weight(1f))
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MiniMetricCard("위험자산", "${scan.retirement.riskyPct}%", scan.retirement.status, Modifier.weight(1f))
                MiniMetricCard("추가여력", krw(scan.retirement.riskyBuyRoomKrw), "퇴직연금", Modifier.weight(1f))
            }
        }
        item { SectionTitle("상위 미국 ETF") }
        items(scan.usEtfs.take(3)) { etf -> UsEtfCard(etf) }
        item { SectionTitle("한국 단기 후보") }
        items(scan.krShortStocks.take(3)) { stock -> KrShortCard(stock) }
        item {
            InfoCard(
                title = "운용 메모",
                lines = listOf(
                    "미국 주식은 단기 매매 없이 ETF 장기 분할매수 기준이다.",
                    "한국 장기투자는 퇴직연금 ETF 한도와 별도 관리한다.",
                    "한국 단기 후보는 일반계좌 전용이며 진입·손절·목표가를 반드시 같이 본다.",
                    "현재 앱 데이터는 1차 MVP용 mock 기반이다. 다음 단계에서 실데이터 API를 연결한다."
                )
            )
        }
    }
}

@Composable
fun UsEtfTab(items: List<UsEtfSignal>) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("미국 장기 ETF", "1년~10년 보유 전제", "월 기본매수 + 조정 시 추가매수 구조") }
        items(items) { UsEtfCard(it) }
    }
}

@Composable
fun FxTab(fx: FxSignal) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("달러 환전 판단", "USD/KRW ${fx.usdKrw}", fx.action) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MiniMetricCard("현재 환율", fx.usdKrw.toString(), "USD/KRW", Modifier.weight(1f))
                MiniMetricCard("60일 평균", fx.ma60.toString(), "비교 기준", Modifier.weight(1f))
            }
        }
        item { MiniMetricCard("권장 환전금액", krw(fx.suggestedConversionKrw), fx.reason, Modifier.fillMaxWidth()) }
        item {
            InfoCard(
                title = "판단 규칙",
                lines = listOf(
                    "60일 평균보다 낮고 달러 약세면 선환전 비중 확대",
                    "60일 평균권이면 3~4회 분할환전",
                    "60일 평균보다 높고 달러 강세면 최소환전",
                    "미국 ETF가 크게 빠졌을 때만 고환율 일부 감수"
                )
            )
        }
    }
}

@Composable
fun RetirementTab(retirement: RetirementSignal) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("퇴직연금 ETF", "위험자산 한도 점검", retirement.status) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MiniMetricCard("위험자산", "${retirement.riskyPct}%", "한도 70%", Modifier.weight(1f))
                MiniMetricCard("안전자산", "${retirement.safePct}%", "방어 비중", Modifier.weight(1f))
            }
        }
        item { MiniMetricCard("위험자산 추가매수 가능", krw(retirement.riskyBuyRoomKrw), retirement.status, Modifier.fillMaxWidth()) }
        item {
            InfoCard(
                title = "퇴직연금 원칙",
                lines = listOf(
                    "국내상장 ETF 중 퇴직연금 매수 가능 상품만 사용",
                    "레버리지·인버스 제외",
                    "위험자산 70% 한도 초과 시 주식형 ETF 추가매수 금지",
                    "증권사별 매수 가능 ETF 목록은 다음 단계에서 실제 목록으로 교체"
                )
            )
        }
    }
}

@Composable
fun KrShortTab(items: List<KrShortSignal>) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("한국 단기 일반계좌", "당일~10일 후보", "퇴직연금과 완전 분리") }
        items(items) { KrShortCard(it) }
        item {
            InfoCard(
                title = "단기 매매 체크",
                lines = listOf(
                    "진입가는 돌파/회복 기준으로만 사용",
                    "손절가 이탈 시 재해석 금지",
                    "목표가 도달 전 거래량 급감·장대음봉이면 비중 축소",
                    "현재 앱은 mock 후보 표시 단계다. 실제 수급·거래대금 연결 필요"
                )
            )
        }
    }
}

@Composable
fun HeaderCard(title: String, subtitle: String, body: String) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(subtitle, style = MaterialTheme.typography.bodyMedium)
            Text(body, style = MaterialTheme.typography.bodyLarge)
        }
    }
}

@Composable
fun MiniMetricCard(title: String, value: String, label: String, modifier: Modifier = Modifier) {
    ElevatedCard(modifier, shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.labelLarge)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
fun UsEtfCard(etf: UsEtfSignal) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("${etf.ticker} - ${etf.name}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("점수 ${etf.score} / 이번달 매수 ${etf.buyPct}%")
                }
                AssistChip(onClick = {}, label = { Text(krw(etf.buyKrw)) })
            }
            LinearProgressIndicator(
                progress = { (etf.score / 100.0).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth()
            )
            Text("조건: ${etf.condition}")
            Text("리스크: ${etf.risk}")
        }
    }
}

@Composable
fun KrShortCard(stock: KrShortSignal) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text("${stock.name} (${stock.code})", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("점수 ${stock.score} / ${stock.reason}")
                }
                AssistChip(onClick = {}, label = { Text("${stock.score}") })
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                TradePriceBox("진입", stock.entry, Modifier.weight(1f))
                TradePriceBox("손절", stock.stopLoss, Modifier.weight(1f))
                TradePriceBox("목표", stock.target1, Modifier.weight(1f))
            }
            Text("실패 조건: 진입 실패 후 손절가 이탈")
        }
    }
}

@Composable
fun TradePriceBox(label: String, price: Long, modifier: Modifier = Modifier) {
    Card(modifier, shape = RoundedCornerShape(12.dp)) {
        Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, style = MaterialTheme.typography.labelMedium)
            Text(krw(price), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
fun InfoCard(title: String, lines: List<String>) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            lines.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
        }
    }
}

@Composable
fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
}

@Composable
fun EmptyState() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text("스캔 결과 없음")
    }
}

fun krw(value: Long): String = NumberFormat.getNumberInstance(Locale.KOREA).format(value) + "원"
