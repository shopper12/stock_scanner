from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings


@dataclass(frozen=True)
class Instrument:
    ticker: str
    name: str
    market: str
    asset_class: str


US_AND_ETF_UNIVERSE: tuple[Instrument, ...] = (
    Instrument('SPY', 'S&P 500 ETF', 'US', 'Equity ETF'),
    Instrument('QQQ', 'Nasdaq 100 ETF', 'US', 'Equity ETF'),
    Instrument('SMH', 'Semiconductor ETF', 'US', 'Sector ETF'),
    Instrument('SOXX', 'Semiconductor ETF', 'US', 'Sector ETF'),
    Instrument('XLK', 'Technology ETF', 'US', 'Sector ETF'),
    Instrument('TSM', 'Taiwan Semiconductor ADR', 'US', 'US Stock'),
    Instrument('AMAT', 'Applied Materials', 'US', 'US Stock'),
    Instrument('LRCX', 'Lam Research', 'US', 'US Stock'),
    Instrument('KLAC', 'KLA Corp.', 'US', 'US Stock'),
    Instrument('TER', 'Teradyne', 'US', 'US Stock'),
    Instrument('MRVL', 'Marvell Technology', 'US', 'US Stock'),
    Instrument('AVGO', 'Broadcom', 'US', 'US Stock'),
    Instrument('MU', 'Micron Technology', 'US', 'US Stock'),
    Instrument('ALAB', 'Astera Labs', 'US', 'US Stock'),
    Instrument('VRT', 'Vertiv', 'US', 'US Stock'),
    Instrument('SMCI', 'Super Micro Computer', 'US', 'US Stock'),
    Instrument('APH', 'Amphenol', 'US', 'US Stock'),
    Instrument('NVDA', 'NVIDIA', 'US', 'US Stock'),
    Instrument('AMD', 'Advanced Micro Devices', 'US', 'US Stock'),
    Instrument('PLTR', 'Palantir', 'US', 'US Stock'),
    Instrument('GOOGL', 'Alphabet', 'US', 'US Stock'),
    Instrument('MSFT', 'Microsoft', 'US', 'US Stock'),
    Instrument('META', 'Meta Platforms', 'US', 'US Stock'),
    Instrument('AMZN', 'Amazon', 'US', 'US Stock'),
)

COMMODITY_UNIVERSE: tuple[Instrument, ...] = (
    Instrument('GLD', 'Gold ETF', 'Commodity', 'Precious Metal'),
    Instrument('SLV', 'Silver ETF', 'Commodity', 'Precious Metal'),
    Instrument('USO', 'Crude Oil ETF', 'Commodity', 'Energy Commodity'),
    Instrument('UNG', 'Natural Gas ETF', 'Commodity', 'Energy Commodity'),
    Instrument('DBC', 'Broad Commodity ETF', 'Commodity', 'Commodity Basket'),
    Instrument('CPER', 'Copper ETF', 'Commodity', 'Industrial Metal'),
    Instrument('DBA', 'Agriculture ETF', 'Commodity', 'Agriculture'),
)

STRONG_KR_SETUPS = {
    'theme_repricing_breakout',
    'new_52w_high_breakout',
    'first_pullback_after_high',
    'pullback_reversal',
}

HIGH_CONVICTION_RULESET = {
    'regime_gate': 'MA50/MA200 상회, 유동성 충분, 광의 리스크 crash 아님',
    'trend_momentum_gate': '6개월/12개월 상대강도 스캔 유니버스 상위 10%',
    'breakout_gate': '20일 또는 55일 고점 돌파 + 20일 평균 거래량 1.5배 이상',
    'risk_gate': 'ATR 기반 손절폭 허용 + 기대 보상위험비 2:1 이상',
    'confirmation_gate': '가격·거래량 데이터와 뉴스/브리핑 확인을 앱 카드에 같이 표시',
}


def scan_global_signal_watch(kr_short_rows: list[dict] | None = None) -> list[dict]:
    """Scan U.S. stocks/ETFs, KR candidates, and commodity ETFs for app alerts.

    The function returns no rows unless the candidate passes the high-conviction
    gates requested in the recurring alert prompt.
    """
    records: list[dict] = []
    metrics: list[dict] = []
    regime = _market_regime()

    for instrument in (*US_AND_ETF_UNIVERSE, *COMMODITY_UNIVERSE):
        item = _scan_instrument(instrument, regime)
        if item:
            metrics.append(item)

    _apply_relative_strength_rank(metrics)
    ranked_snapshot = _ranked_snapshot(metrics)

    for item in metrics:
        if _passes_global_gate(item, regime):
            records.append(_as_alert_record(item, regime, ranked_snapshot))

    records.extend(_kr_rows_as_global_alerts(kr_short_rows or [], regime))
    return sorted(
        records,
        key=lambda x: (float(x.get('confidence', 0)), float(x.get('score', 0)), float(x.get('relative_strength_pctile', 0))),
        reverse=True,
    )[:8]


def _market_regime() -> dict:
    spy = _latest_index_state('SPY')
    qqq = _latest_index_state('QQQ')
    spy_break = bool(spy and spy.get('price', 0) < spy.get('ma200', 0))
    qqq_break = bool(qqq and qqq.get('price', 0) < qqq.get('ma200', 0))
    crash_mode = spy_break and qqq_break
    return {
        'crash_mode': crash_mode,
        'broad_risk_ok': not crash_mode,
        'spy': spy,
        'qqq': qqq,
        'reason': 'SPY/QQQ 둘 다 200일선 아래' if crash_mode else '광의 리스크 crash 아님',
    }


def _latest_index_state(ticker: str) -> dict | None:
    hist = _load_history(ticker)
    if hist.empty or len(hist) < 220:
        return None
    hist = _prepare_history(hist)
    if hist.empty:
        return None
    latest = hist.iloc[-1]
    return {
        'ticker': ticker,
        'price': round(float(latest['close']), 2),
        'ma50': round(float(latest['ma50']), 2),
        'ma200': round(float(latest['ma200']), 2),
    }


def _scan_instrument(instrument: Instrument, regime: dict) -> dict | None:
    hist = _load_history(instrument.ticker)
    if hist.empty or len(hist) < 220:
        return None
    hist = _prepare_history(hist)
    if hist.empty:
        return None

    latest = hist.iloc[-1]
    prev_high20 = float(hist['high'].iloc[-21:-1].max())
    prev_high55 = float(hist['high'].iloc[-56:-1].max())
    price = float(latest['close'])
    ma20 = float(latest['ma20'])
    ma50 = float(latest['ma50'])
    ma200 = float(latest['ma200'])
    atr14 = float(latest['atr14'])
    volume_ma20 = float(latest['volume_ma20'])
    volume_ratio = _ratio(float(latest['volume']), volume_ma20)
    avg_dollar_volume = price * volume_ma20
    ret21 = _return(hist['close'], 21)
    ret63 = _return(hist['close'], 63)
    ret126 = _return(hist['close'], 126)
    ret252 = _return(hist['close'], 252)
    rsi14 = _rsi14(hist['close'])
    gap_ma20 = price / ma20 - 1.0 if ma20 > 0 else 0.0

    trend_ok = price > ma50 and price > ma200 and ma50 >= ma200 * 0.98
    tsmom_aligned = ret63 > 0 and ret126 > 0 and ret252 > 0
    breakout20 = price >= prev_high20 * 0.997
    breakout55 = price >= prev_high55 * 0.997
    commodity_trend_confirm = instrument.market == 'Commodity' and tsmom_aligned and ret126 >= 0.08 and ret252 >= 0.12
    volume_confirm = volume_ratio >= 1.5 or commodity_trend_confirm
    liquidity_ok = avg_dollar_volume >= _min_dollar_volume(instrument)
    exhaustion_guard = rsi14 <= 76 and gap_ma20 <= 0.16 and ret21 <= 0.28
    stop_distance = max(atr14 * 2.0, price * 0.04)
    stop = max(price - stop_distance, price * 0.78)
    risk_per_share = max(price - stop, 0.0)
    risk_pct = (risk_per_share / price * 100.0) if price > 0 else 0.0
    target1 = price + risk_per_share * 2.1
    target2 = price + risk_per_share * 3.2
    rr_ratio = (target1 - price) / risk_per_share if risk_per_share > 0 else 0.0
    risk_ok = 3.0 <= risk_pct <= 11.5 and rr_ratio >= 2.0
    rs_raw = ret126 * 0.50 + ret252 * 0.35 + ret63 * 0.15

    score = 0.0
    score += 16.0 if regime.get('broad_risk_ok') else -25.0
    score += 16.0 if trend_ok else -12.0
    score += 16.0 if tsmom_aligned else -10.0
    score += 14.0 if breakout55 else 10.0 if breakout20 else 8.0 if commodity_trend_confirm else -8.0
    score += 12.0 if volume_confirm else -10.0
    score += 10.0 if liquidity_ok else -10.0
    score += 8.0 if exhaustion_guard else -16.0
    score += 8.0 if risk_ok else -12.0
    score += min(max(rs_raw * 30.0, -8.0), 13.0)

    return {
        'ticker': instrument.ticker,
        'name': instrument.name,
        'market': instrument.market,
        'asset_class': instrument.asset_class,
        'current_price': round(price, 2),
        'ma20': round(ma20, 2),
        'ma50': round(ma50, 2),
        'ma200': round(ma200, 2),
        'score': round(max(0.0, min(score, 100.0)), 1),
        'rs_raw': rs_raw,
        'ret_1m_pct': round(ret21 * 100, 2),
        'ret_3m_pct': round(ret63 * 100, 2),
        'ret_6m_pct': round(ret126 * 100, 2),
        'ret_12m_pct': round(ret252 * 100, 2),
        'rsi14': round(rsi14, 1),
        'gap_ma20_pct': round(gap_ma20 * 100, 2),
        'avg_dollar_volume': round(avg_dollar_volume, 0),
        'volume_ratio_20d': round(volume_ratio, 2),
        'breakout20': bool(breakout20),
        'breakout55': bool(breakout55),
        'commodity_trend_confirm': bool(commodity_trend_confirm),
        'trend_ok': bool(trend_ok),
        'tsmom_aligned': bool(tsmom_aligned),
        'liquidity_ok': bool(liquidity_ok),
        'exhaustion_guard': bool(exhaustion_guard),
        'risk_ok': bool(risk_ok),
        'rr_ratio': round(rr_ratio, 2),
        'risk_pct': round(risk_pct, 2),
        'entry': round(price, 2),
        'entry_low': round(max(price - atr14 * 0.6, price * 0.985), 2),
        'entry_high': round(price + atr14 * 0.25, 2),
        'stop_loss': round(stop, 2),
        'target1': round(target1, 2),
        'target2': round(target2, 2),
        'timestamp_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
    }


def _passes_global_gate(item: dict, regime: dict) -> bool:
    return (
        bool(regime.get('broad_risk_ok'))
        and float(item.get('score', 0)) >= 78.0
        and float(item.get('relative_strength_pctile', 0)) >= 0.90
        and bool(item.get('trend_ok'))
        and bool(item.get('tsmom_aligned'))
        and bool(item.get('liquidity_ok'))
        and bool(item.get('exhaustion_guard'))
        and bool(item.get('risk_ok'))
        and (
            (bool(item.get('breakout20')) or bool(item.get('breakout55'))) and float(item.get('volume_ratio_20d', 0)) >= 1.5
            or bool(item.get('commodity_trend_confirm'))
        )
    )


def _as_alert_record(item: dict, regime: dict, ranked_snapshot: list[dict]) -> dict:
    breakout = '55일 신고가 돌파' if item.get('breakout55') else '20일 신고가 돌파' if item.get('breakout20') else '원자재 3/6/12개월 추세 정렬'
    entry_zone = f"{item.get('entry_low')}~{item.get('entry_high')}"
    trigger_condition = (
        f"{breakout}, 거래량 {item.get('volume_ratio_20d')}배, "
        f"6M/12M RS 상위 {float(item.get('relative_strength_pctile', 0)) * 100:.0f}%, MA50·MA200 상회"
    )
    reason = (
        f"{trigger_condition}. ATR 손절 {item.get('risk_pct')}%, R/R {item.get('rr_ratio')}:1. "
        f"{regime.get('reason')}. 뉴스/이벤트 확인은 앱 브리핑 카드의 보조 확인이 필요합니다."
    )
    return {
        'ticker': item['ticker'],
        'code': item['ticker'],
        'name': item['name'],
        'asset_name': item['name'],
        'market': item['market'],
        'asset_class': item['asset_class'],
        'direction': 'LONG',
        'strategy_type': 'high_conviction_5_gate_breakout',
        'score': item['score'],
        'confidence': _confidence(item),
        'relative_strength_pctile': round(float(item.get('relative_strength_pctile', 0)), 4),
        'relative_strength_rank': item.get('relative_strength_rank'),
        'current_price': item['current_price'],
        'basis_price': item['current_price'],
        'entry': item['entry'],
        'entry_zone': entry_zone,
        'entry_low': item.get('entry_low'),
        'entry_high': item.get('entry_high'),
        'stop_loss': item['stop_loss'],
        'target1': item['target1'],
        'target2': item['target2'],
        'risk_pct': item['risk_pct'],
        'rr_ratio': item.get('rr_ratio'),
        'ret_1m_pct': item['ret_1m_pct'],
        'ret_3m_pct': item['ret_3m_pct'],
        'ret_6m_pct': item['ret_6m_pct'],
        'ret_12m_pct': item['ret_12m_pct'],
        'rsi14': item['rsi14'],
        'volume_ratio_20d': item['volume_ratio_20d'],
        'avg_dollar_volume': item.get('avg_dollar_volume'),
        'trigger_condition': trigger_condition,
        'reason': reason,
        'rationale': reason,
        'why_better_than_candidates': _why_better_than_candidates(item, ranked_snapshot),
        'invalidation': '종가 기준 손절가 이탈, 돌파선 재이탈, 거래량 급감, MA20 이탈, 또는 이벤트 갭 리스크 발생',
        'failure_condition': '종가 기준 손절가 이탈, 돌파선 재이탈, 거래량 급감, MA20 이탈, 또는 이벤트 갭 리스크 발생',
        'confirmation_sources': ['Yahoo Finance OHLCV via yfinance', '앱 브리핑/뉴스 확인 필요'],
        'ruleset': HIGH_CONVICTION_RULESET,
        'source_strategy': 'high-conviction app scanner: regime + RS top-decile + breakout + ATR risk gates',
        'source_note': '앱 자동 고확신 조건검색',
        'timestamp_kst': item['timestamp_kst'],
    }


def _confidence(item: dict) -> float:
    base = 6.8
    base += min(max((float(item.get('relative_strength_pctile', 0)) - 0.90) * 6.0, 0.0), 0.6)
    base += 0.3 if bool(item.get('breakout55')) else 0.0
    base += 0.3 if float(item.get('volume_ratio_20d') or 0) >= 2.0 else 0.0
    base += 0.2 if 45 <= float(item.get('rsi14') or 50) <= 70 else -0.2
    return round(max(6.0, min(base, 8.6)), 1)


def _ranked_snapshot(items: list[dict]) -> list[dict]:
    return [
        {
            'ticker': item.get('ticker'),
            'score': item.get('score'),
            'rs': round(float(item.get('relative_strength_pctile', 0)) * 100, 0),
            'ret_1m_pct': item.get('ret_1m_pct'),
            'rsi14': item.get('rsi14'),
            'volume_ratio_20d': item.get('volume_ratio_20d'),
        }
        for item in sorted(items, key=lambda x: float(x.get('score') or 0), reverse=True)[:8]
    ]


def _why_better_than_candidates(item: dict, ranked_snapshot: list[dict]) -> str:
    alternatives = [row for row in ranked_snapshot if row.get('ticker') != item.get('ticker')][:4]
    if not alternatives:
        return '동일 유니버스에서 최고 점수 후보이며 모든 5단계 게이트를 통과했습니다.'
    names = ', '.join(str(row.get('ticker')) for row in alternatives)
    return (
        f"{item.get('ticker')}는 {names} 대비 5단계 게이트를 모두 통과했습니다. "
        f"RS 상위 {float(item.get('relative_strength_pctile', 0)) * 100:.0f}%, "
        f"거래량 {item.get('volume_ratio_20d')}배, ATR 손절 {item.get('risk_pct')}%, "
        f"R/R {item.get('rr_ratio')}:1 조합이 더 안정적입니다."
    )


def _kr_rows_as_global_alerts(rows: list[dict], regime: dict) -> list[dict]:
    if not regime.get('broad_risk_ok'):
        return []
    out: list[dict] = []
    for row in rows:
        setup = str(row.get('strategy_type') or '')
        score = float(row.get('score') or 0.0)
        volume_ratio = float(row.get('volume_ratio_20d') or 0.0)
        rsi = float(row.get('rsi14') or 50.0)
        risk_pct = float(row.get('risk_pct') or 0.0)
        if setup not in STRONG_KR_SETUPS or score < 80.0:
            continue
        if volume_ratio and volume_ratio < 1.5:
            continue
        if rsi > 76:
            continue
        if risk_pct and not (3.0 <= risk_pct <= 11.5):
            continue
        trigger = f"KR 강신호 {setup}, score {score:.1f}, volume {volume_ratio or '-'}x"
        reason = f"{trigger}. 기존 KR 스캐너 통과 + 글로벌 앱 고확신 필터 통과: {row.get('reason', '')}"
        out.append({
            'ticker': str(row.get('code', '')).zfill(6),
            'code': str(row.get('code', '')).zfill(6),
            'name': row.get('name', ''),
            'asset_name': row.get('name', ''),
            'market': 'KR',
            'asset_class': 'KR Stock',
            'direction': 'LONG',
            'strategy_type': f'kr_high_conviction_{setup}',
            'score': round(score, 1),
            'confidence': round(min(8.4, 6.8 + max(score - 80.0, 0.0) / 50.0), 1),
            'relative_strength_pctile': 1.0,
            'current_price': row.get('current_price'),
            'basis_price': row.get('current_price'),
            'entry': row.get('entry'),
            'entry_zone': row.get('entry_zone') or row.get('entry'),
            'stop_loss': row.get('stop_loss'),
            'target1': row.get('target1'),
            'target2': row.get('target2'),
            'risk_pct': row.get('risk_pct'),
            'ret_1m_pct': row.get('momentum_20d_pct'),
            'ret_3m_pct': row.get('momentum_60d_pct'),
            'rsi14': row.get('rsi14'),
            'volume_ratio_20d': row.get('volume_ratio_20d'),
            'trigger_condition': trigger,
            'reason': reason,
            'rationale': reason,
            'why_better_than_candidates': 'KR 단기 후보 중 score·거래량·위험폭 필터를 동시에 통과한 후보입니다.',
            'invalidation': row.get('failure_condition') or 'MA20/손절가 이탈',
            'failure_condition': row.get('failure_condition') or 'MA20/손절가 이탈',
            'confirmation_sources': ['KR scanner live quote', 'KR scanner strategy factors'],
            'ruleset': HIGH_CONVICTION_RULESET,
            'source_strategy': 'existing KR runtime scanner + high-conviction app bridge',
            'source_note': '앱 자동 고확신 조건검색',
            'timestamp_kst': row.get('price_timestamp') or datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        })
    return out


def _apply_relative_strength_rank(items: list[dict]) -> None:
    if not items:
        return
    ranked = sorted(items, key=lambda x: float(x.get('rs_raw', 0)), reverse=True)
    denom = max(len(ranked) - 1, 1)
    for idx, item in enumerate(ranked):
        item['relative_strength_rank'] = idx + 1
        item['relative_strength_pctile'] = 1.0 - (idx / denom)
        item['score'] = round(min(100.0, float(item.get('score', 0)) + max(0.0, item['relative_strength_pctile'] - 0.85) * 25.0), 1)


def _load_history(ticker: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return pd.DataFrame()
    try:
        import yfinance as yf
        raw = yf.download(ticker, period='18mo', interval='1d', auto_adjust=True, progress=False)
        return _normalise_yahoo_ohlcv(raw)
    except Exception as exc:
        print(f'[global_signal_watch] history fetch failed for {ticker}: {exc}')
        return pd.DataFrame()


def _min_dollar_volume(instrument: Instrument) -> float:
    if instrument.asset_class == 'US Stock':
        return 50_000_000.0
    if instrument.market == 'Commodity':
        return 10_000_000.0
    return 20_000_000.0


def _normalise_yahoo_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = _first_existing_column(df, ('Date', 'Datetime', 'date', 'datetime', 'index'))
    df = df.rename(columns={
        date_col: 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Adj Close': 'close',
        'Volume': 'volume',
    })
    required = ('date', 'open', 'high', 'low', 'close', 'volume')
    if any(col not in df.columns for col in required):
        return pd.DataFrame()
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df[['date', 'open', 'high', 'low', 'close', 'volume']].dropna().reset_index(drop=True)


def _prepare_history(hist: pd.DataFrame) -> pd.DataFrame:
    out = hist.sort_values('date').reset_index(drop=True).copy()
    out['ma20'] = out['close'].rolling(20).mean()
    out['ma50'] = out['close'].rolling(50).mean()
    out['ma200'] = out['close'].rolling(200).mean()
    out['volume_ma20'] = out['volume'].rolling(20).mean()
    out['atr14'] = _atr14(out)
    return out.dropna().reset_index(drop=True)


def _atr14(df: pd.DataFrame) -> pd.Series:
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean()


def _rsi14(close: pd.Series) -> float:
    if len(close) < 15:
        return 50.0
    changes = close.astype(float).diff().dropna().tail(14)
    gains = changes.clip(lower=0).mean()
    losses = (-changes.clip(upper=0)).mean()
    if losses <= 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return float(100.0 - (100.0 / (1.0 + rs)))


def _return(close: pd.Series, window: int) -> float:
    if len(close) <= window:
        return 0.0
    base = float(close.iloc[-window - 1])
    last = float(close.iloc[-1])
    if base <= 0:
        return 0.0
    return last / base - 1.0


def _ratio(num: float, den: float) -> float:
    return 0.0 if den <= 0 else num / den


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise KeyError(f'none of columns {candidates} found in {list(df.columns)}')
