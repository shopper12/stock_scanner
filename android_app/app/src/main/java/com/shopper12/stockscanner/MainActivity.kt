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
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import com.shopper12.stockscanner.data.HistoryStore
import com.shopper12.stockscanner.data.ScannerEngine
import com.shopper12.stockscanner.model.*
import com.shopper12.stockscanner.notify.TelegramNotifier
import com.shopper12.stockscanner.ui.*
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
        WorkScheduler.schedule(applicationContext)
        setContent { StockScannerScreen(this) }
    }
}

@Composable
fun StockScannerScreen(activity: ComponentActivity) {
    val engine = remember { ScannerEngine() }
    val historyStore = remember { HistoryStore(activity.applicationContext) }
    var result by remember { mutableStateOf<ScanResult?>(null) }
    var historyItems by remember { mutableStateOf(historyStore.load()) }
    var status by remember { mutableStateOf("초기화 중") }
    var selectedTab by remember { mutableIntStateOf(0) }
    var manualSymbol by remember { mutableStateOf("VOO") }
    var manualAnalysis by remember { mutableStateOf<ManualAnalysis?>(null) }
    val tabs = listOf("요약", "전략", "직접판단", "미국 ETF", "환율", "퇴직/IRP", "한국 단기", "검증", "기록")

    LaunchedEffect(Unit) {
        status = "초기 스캔 중 / 자동 예약 등록됨"
        val scan = withContext(Dispatchers.IO) { engine.runScan() }
        val analysis = withContext(Dispatchers.IO) { engine.analyzeManualSymbol(manualSymbol) }
        withContext(Dispatchers.IO) { historyStore.saveScan(scan) }
        result = scan
        manualAnalysis = analysis
        historyItems = historyStore.load()
        status = "초기 스캔 완료 / 이후 자동 전송"
    }

    MaterialTheme {
        Scaffold(topBar = { TopBar() }) { padding ->
            Column(Modifier.padding(padding).fillMaxSize()) {
                ActionPanel(
                    status = status,
                    onScan = {
                        activity.lifecycleScope.launch {
                            status = "스캔 중"
                            val scan = withContext(Dispatchers.IO) { engine.runScan() }
                            val analysis = withContext(Dispatchers.IO) { engine.analyzeManualSymbol(manualSymbol) }
                            withContext(Dispatchers.IO) { historyStore.saveScan(scan) }
                            result = scan
                            manualAnalysis = analysis
                            historyItems = historyStore.load()
                            status = "스캔 완료 / 기록 저장"
                        }
                    },
                    onTelegram = {
                        activity.lifecycleScope.launch {
                            status = "텔레그램 전송 준비"
                            var scan = result
                            if (scan == null) {
                                scan = withContext(Dispatchers.IO) { engine.runScan() }
                                result = scan
                            }
                            val sent = withContext(Dispatchers.IO) { TelegramNotifier().send(scan!!) }
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
                            onAnalyze = {
                                activity.lifecycleScope.launch {
                                    status = "직접 판단 중"
                                    val analysis = withContext(Dispatchers.IO) { engine.analyzeManualSymbol(manualSymbol) }
                                    withContext(Dispatchers.IO) { historyStore.saveManual(analysis) }
                                    manualAnalysis = analysis
                                    historyItems = historyStore.load()
                                    status = "직접 판단 완료 / 기록 저장"
                                }
                            }
                        )
                        3 -> UsEtfTab(scan.usEtfs)
                        4 -> FxTab(scan.fx)
                        5 -> RetirementTab(scan.retirement, scan.retirementAssets)
                        6 -> KrShortTab(scan.krShortStocks)
                        7 -> ValidationTab(scan.validationLogs, scan.revisionPolicy)
                        8 -> HistoryScreen(
                            items = historyItems,
                            onClear = {
                                historyStore.clear()
                                historyItems = historyStore.load()
                                status = "기록 삭제 완료"
                            }
                        )
                    }
                } ?: LoadingState()
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
    Card(Modifier.fillMaxWidth().padding(12.dp), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("실행 제어", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("상태: $status")
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
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("오늘 요약", "기준시각: ${scan.createdAt}", "환율 ${scan.fx.action} / 미국 ETF ${scan.usEtfs.size}개 / 한국 단기 ${scan.krShortStocks.size}개") }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MetricBox("USD/KRW", scan.fx.usdKrw.toString(), scan.fx.action, Modifier.weight(1f))
                MetricBox("환전", krw(scan.fx.suggestedConversionKrw), "권장금액", Modifier.weight(1f))
            }
        }
        item { Text("상위 미국 ETF", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
        items(scan.usEtfs.take(3)) { UsEtfReviewCard(it) }
        item { Text("한국 단기 후보", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
        items(scan.krShortStocks.take(3)) { KrShortReviewCard(it) }
    }
}

@Composable
fun StrategyTab(strategies: List<StrategyInfo>, policy: StrategyRevisionPolicy) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("전략 설명", "현재 앱이 쓰는 판단 규칙", "대상·기간·리스크 규칙을 분리 표시") }
        items(strategies) { StrategyCard(it) }
        item {
            InfoBox("전략 수정 원칙", listOf(
                "검증 주기: ${policy.validationFrequency}",
                "수정 주기: ${policy.revisionFrequency}",
                "수정 임계값: ${policy.revisionThreshold}",
                "동결 규칙: ${policy.freezeRule}"
            ))
        }
    }
}

@Composable
fun ManualTab(symbol: String, analysis: ManualAnalysis?, onSymbolChange: (String) -> Unit, onAnalyze: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("직접 종목 판단", "티커/종목코드를 입력", "예: VOO, QQQ, GLD, NVDA, 005930") }
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
                    Button(onClick = onAnalyze, modifier = Modifier.fillMaxWidth()) { Text("현재가 기반 판단") }
                }
            }
        }
        analysis?.let { item { ManualReviewCard(it) } }
    }
}

@Composable
fun UsEtfTab(items: List<UsEtfSignal>) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("미국 장기 ETF", "실시간/준실시간 현재가 기반", "현재가·MA20·MA60·MA200·진입·손절·목표 표시") }
        items(items) { UsEtfReviewCard(it) }
    }
}

@Composable
fun FxTab(fx: FxSignal) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("달러 환전 판단", "USD/KRW ${fx.usdKrw}", fx.action) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MetricBox("현재 환율", fx.usdKrw.toString(), "USD/KRW", Modifier.weight(1f))
                MetricBox("60일 평균", fx.ma60.toString(), "비교 기준", Modifier.weight(1f))
            }
        }
        item { MetricBox("권장 환전금액", krw(fx.suggestedConversionKrw), fx.reason, Modifier.fillMaxWidth()) }
    }
}

@Composable
fun RetirementTab(retirement: RetirementSignal, assets: List<RetirementAssetSignal>) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("퇴직연금/IRP ETF", "주식·채권·원자재·레버리지·인버스 표시", retirement.status) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                MetricBox("위험자산", "${retirement.riskyPct}%", "한도 70%", Modifier.weight(1f))
                MetricBox("안전자산", "${retirement.safePct}%", "방어 비중", Modifier.weight(1f))
            }
        }
        item { MetricBox("위험자산 추가매수 가능", krw(retirement.riskyBuyRoomKrw), retirement.status, Modifier.fillMaxWidth()) }
        items(assets) { RetirementReviewCard(it) }
    }
}

@Composable
fun KrShortTab(items: List<KrShortSignal>) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("한국 단기 일반계좌", "현재가·진입·손절·목표 검토", "현재 한국 데이터는 Yahoo .KS/.KQ 우선, 실패 시 fallback") }
        items(items) { KrShortReviewCard(it) }
    }
}

@Composable
fun ValidationTab(logs: List<StrategyValidationLog>, policy: StrategyRevisionPolicy) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { HeaderBox("전략 기록·검증", policy.validationFrequency, "과잉 최적화를 막기 위해 수정 빈도를 제한") }
        item {
            InfoBox("수정 제한 규칙", listOf(
                "기본 수정 주기: ${policy.revisionFrequency}",
                "수정 조건: ${policy.revisionThreshold}",
                "수정 후 동결: ${policy.freezeRule}",
                "매시간은 검증만 수행하고, 전략 파라미터를 매시간 바꾸지는 않는다."
            ))
        }
        items(logs) { ValidationCard(it) }
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
fun LoadingState() {
    Box(Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.Center) {
        Text("스캔 준비 중")
    }
}
