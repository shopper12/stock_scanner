package com.shopper12.stockscanner

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
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
    val engine = remember { ScannerEngine() }
    var result by remember { mutableStateOf<ScanResult?>(engine.runScan()) }
    var status by remember { mutableStateOf("대기") }
    var selectedTab by remember { mutableIntStateOf(0) }
    var manualSymbol by remember { mutableStateOf("VOO") }
    var manualAnalysis by remember { mutableStateOf<ManualAnalysis?>(engine.analyzeManualSymbol("VOO")) }
    val tabs = listOf("요약", "전략", "직접판단", "미국 ETF", "환율", "퇴직/IRP", "한국 단기", "검증")

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
                            result = withContext(Dispatchers.Default) { engine.runScan() }
                            manualAnalysis = withContext(Dispatchers.Default) { engine.analyzeManualSymbol(manualSymbol) }
                            status = "스캔 완료"
                        }
                    },
                    onTelegram = {
                        activity.lifecycleScope.launch {
                            val scan = result ?: engine.runScan()
                            val sent = withContext(Dispatchers.IO) { TelegramNotifier().send(scan) }
                            status = if (sent) "텔레그램 전송 완료" else "텔레그램 전송 실패"
                        }
                    },
                    onScheduleOn = {
                        WorkScheduler.schedule(activity.applicationContext)
                        status = "자동 검증 예약 완료: 15분 주기"
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
                        1 -> StrategyTab(scan.strategies, scan.revisionPolicy)
                        2 -> ManualTab(
                            symbol = manualSymbol,
                            analysis = manualAnalysis,
                            onSymbolChange = { manualSymbol = it },
                            onAnalyze = { manualAnalysis = engine.analyzeManualSymbol(manualSymbol) }
                        )
                        3 -> UsEtfTab(scan.usEtfs)
                        4 -> FxTab(scan.fx)
                        5 -> RetirementTab(scan.retirement, scan.retirementAssets)
                        6 -> KrShortTab(scan.krShortStocks)
                        7 -> ValidationTab(scan.validationLogs, scan.revisionPolicy)
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
                body = "환율 ${scan.fx.action} / 전략 ${scan.strategies.size}개 / 직접입력 판단 가능 / 검증로그 ${scan.validationLogs.size}개"
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
                MiniMetricCard("추가여력", krw(scan.retirement.riskyBuyRoomKrw), "퇴직/IRP", Modifier.weight(1f))
            }
        }
        item { SectionTitle("현재 전략 핵심") }
        items(scan.strategies.take(3)) { strategy -> StrategyCard(strategy) }
        item { SectionTitle("상위 미국 ETF") }
        items(scan.usEtfs.take(3)) { etf -> UsEtfCard(etf) }
        item { SectionTitle("한국 단기 후보") }
        items(scan.krShortStocks.take(3)) { stock -> KrShortCard(stock) }
        item {
            InfoCard(
                title = "현재 단계",
                lines = listOf(
                    "앱 화면·전략 설명·직접 종목 판단·검증 로그·예상 차트가 들어간 2차 MVP다.",
                    "데이터는 아직 mock 기반이다. 다음 단계에서 실시간 가격/수급/API를 연결해야 한다.",
                    "전략은 매시간 검증하지만 파라미터 수정은 주 1회 또는 임계값 충족 시로 제한한다."
                )
            )
        }
    }
}

@Composable
fun StrategyTab(strategies: List<StrategyInfo>, policy: StrategyRevisionPolicy) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("전략 설명", "현재 앱이 쓰는 판단 규칙", "각 전략의 대상·기간·리스크 규칙을 분리 표시") }
        items(strategies) { StrategyCard(it) }
        item {
            InfoCard(
                title = "전략 수정 원칙",
                lines = listOf(
                    "검증 주기: ${policy.validationFrequency}",
                    "수정 주기: ${policy.revisionFrequency}",
                    "수정 임계값: ${policy.revisionThreshold}",
                    "동결 규칙: ${policy.freezeRule}"
                )
            )
        }
    }
}

@Composable
fun ManualTab(
    symbol: String,
    analysis: ManualAnalysis?,
    onSymbolChange: (String) -> Unit,
    onAnalyze: () -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("직접 종목 판단", "티커/종목코드를 입력", "예: VOO, QQQ, GLD, 005930, 042700") }
        item {
            ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = symbol,
                        onValueChange = onSymbolChange,
                        label = { Text("종목/ETF 입력") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Button(onClick = onAnalyze, modifier = Modifier.fillMaxWidth()) { Text("판단하기") }
                }
            }
        }
        analysis?.let { a ->
            item { ManualAnalysisCard(a) }
            item { ProjectionChart(a.chartPoints) }
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
        item { HeaderCard("미국 장기 ETF", "1년~10년 보유 전제", "주식·채권·금·원자재 ETF까지 표시") }
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
fun RetirementTab(retirement: RetirementSignal, assets: List<RetirementAssetSignal>) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("퇴직연금/IRP ETF", "주식·채권·원자재·레버리지·인버스 표시", retirement.status) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MiniMetricCard("위험자산", "${retirement.riskyPct}%", "한도 70%", Modifier.weight(1f))
                MiniMetricCard("안전자산", "${retirement.safePct}%", "방어 비중", Modifier.weight(1f))
            }
        }
        item { MiniMetricCard("위험자산 추가매수 가능", krw(retirement.riskyBuyRoomKrw), retirement.status, Modifier.fillMaxWidth()) }
        item { SectionTitle("자산군 후보") }
        items(assets) { RetirementAssetCard(it) }
        item {
            InfoCard(
                title = "퇴직/IRP 원칙 변경 반영",
                lines = listOf(
                    "증권사별 후보 차이를 전제로 하지 않고 공통 후보군 기준으로 표시한다.",
                    "주식 ETF 외 채권, 금, 원유, 원자재, 달러형 ETF를 포함한다.",
                    "레버리지·인버스도 표시하되 고위험/장기부적합 태그를 붙인다.",
                    "실제 매수 가능 여부와 위험자산 분류는 계좌 화면에서 최종 확인해야 한다."
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
        item { HeaderCard("한국 단기 일반계좌", "당일~10일 후보", "진입·손절·목표와 예상 경로 표시") }
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
fun ValidationTab(logs: List<StrategyValidationLog>, policy: StrategyRevisionPolicy) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item { HeaderCard("전략 기록·검증", policy.validationFrequency, "과잉 최적화를 막기 위해 수정 빈도를 제한") }
        item {
            InfoCard(
                title = "수정 제한 규칙",
                lines = listOf(
                    "기본 수정 주기: ${policy.revisionFrequency}",
                    "수정 조건: ${policy.revisionThreshold}",
                    "수정 후 동결: ${policy.freezeRule}",
                    "매시간은 검증만 수행하고, 전략 파라미터를 매시간 바꾸지는 않는다."
                )
            )
        }
        items(logs) { ValidationCard(it) }
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
fun StrategyCard(strategy: StrategyInfo) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(strategy.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("대상: ${strategy.target}")
            Text("기간: ${strategy.horizon}")
            Text("상태: ${strategy.currentStatus}")
            Text("규칙", fontWeight = FontWeight.Bold)
            strategy.rules.forEach { Text("• $it") }
            Text("리스크", fontWeight = FontWeight.Bold)
            strategy.riskRules.forEach { Text("• $it") }
        }
    }
}

@Composable
fun ManualAnalysisCard(analysis: ManualAnalysis) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text("${analysis.symbol} (${analysis.market})", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(analysis.opinion)
                }
                AssistChip(onClick = {}, label = { Text("점수 ${analysis.score}") })
            }
            Text("진입: ${analysis.entry}")
            Text("손절/축소: ${analysis.stop}")
            Text("목표/관리: ${analysis.target}")
            analysis.reasons.forEach { Text("• $it") }
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
            ProjectionChart(etf.chartPoints)
            Text("조건: ${etf.condition}")
            Text("리스크: ${etf.risk}")
        }
    }
}

@Composable
fun RetirementAssetCard(asset: RetirementAssetSignal) {
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
            Text("레버리지: ${if (asset.isLeveraged) "예" else "아니오"} / 인버스: ${if (asset.isInverse) "예" else "아니오"}")
            ProjectionChart(asset.chartPoints)
            Text("리스크: ${asset.risk}")
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
            ProjectionChart(stock.chartPoints)
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
fun ProjectionChart(points: List<ChartPoint>) {
    if (points.isEmpty()) return
    val maxValue = points.maxOf { it.value }.coerceAtLeast(1.0)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("예상 경로", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
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

@Composable
fun ValidationCard(log: StrategyValidationLog) {
    ElevatedCard(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("${log.strategyId} / ${log.result}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("시간: ${log.time}")
            Text("발견: ${log.finding}")
            Text("조치: ${log.action}")
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
