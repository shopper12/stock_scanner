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
    Instrument('IWM', 'Russell 2000 ETF', 'US', 'Equity ETF'),
    Instrument('DIA', 'Dow Jones ETF', 'US', 'Equity ETF'),
    Instrument('SMH', 'Semiconductor ETF', 'US', 'Sector ETF'),
    Instrument('SOXX', 'Semiconductor ETF', 'US', 'Sector ETF'),
    Instrument('XLK', 'Technology ETF', 'US', 'Sector ETF'),
    Instrument('XLE', 'Energy ETF', 'US', 'Sector ETF'),
    Instrument('XLF', 'Financials ETF', 'US', 'Sector ETF'),
    Instrument('XLI', 'Industrials ETF', 'US', 'Sector ETF'),
    Instrument('NVDA', 'NVIDIA', 'US', 'US Stock'),
    Instrument('AVGO', 'Broadcom', 'US', 'US Stock'),
    Instrument('MSFT', 'Microsoft', 'US', 'US Stock'),
    Instrument('AAPL', 'Apple', 'US', 'US Stock'),
    Instrument('AMZN', 'Amazon', 'US', 'US Stock'),
    Instrument('GOOGL', 'Alphabet', 'US', 'US Stock'),
    Instrument('META', 'Meta Platforms', 'US', 'US Stock'),
    Instrument('TSLA', 'Tesla', 'US', 'US Stock'),
    Instrument('AMD', 'Advanced Micro Devices', 'US', 'US Stock'),
    Instrument('PLTR', 'Palantir', 'US', 'US Stock'),
)

COMMODITY_UNIVERSE: tuple[Instrument, ...] = (
    Instrument('GLD', 'Gold ETF', 'Commodity', 'Precious Metal'),
    Instrument('SLV', 'Silver ETF', 'Commodity', 'Precious Metal'),
    Instrument('USO', 'Crude Oil ETF', 'Commodity', 'Energy Commodity'),
    Instrument('UNG', 'Natural Gas ETF', 'Commodity', 'Energy Commodity'),
    Instrument('DBC', 'Broad Commodity ETF', 'Commodity', 'Commodity Basket'),
    Instrument('CPER', 'Copper ETF', 'Commodity', 'Industrial Metal'),
    Instrument('DBA', 'Agriculture ETF', 'Commodity', 'Agriculture'),
    Instrument('CORN', 'Corn ETF', 'Commodity', 'Agriculture'),
    Instrument('WEAT', 'Wheat ETF', 'Commodity', 'Agriculture'),
    Instrument('SOYB', 'Soybean ETF', 'Commodity', 'Agriculture'),
)


STRONG_KR_SETUPS = {
    'theme_repricing_breakout',
    'new_52w_high_breakout',
    'first_pullback_after_high',
    'pullback_reversal',
}


def scan_global_signal_watch(kr_short_rows: list[dict] | None = None) -> list[dict]:
    """Scan liquid US stocks/ETFs, commodity ETFs, and KR candidates for high-conviction alerts.

    Design principle:
    - LLM/research inspiration is converted into deterministic factors.
    - No discretionary LLM trade execution; only factor rules are scored.
    - Alert only when trend, time-series momentum, relative strength, breakout, volume,
      exhaustion guard, and ATR risk gates align.
    """
    records: list[dict] = []
    metrics: list[dict] = []

    for instrument in (*US_AND_ETF_UNIVERSE, *COMMODITY_UNIVERSE):
        item = _scan_instrument(instrument)
        if item:
            metrics.append(item)

    _apply_relative_strength_rank(metrics)
    for item in metrics:
        if _passes_global_gate(item):
            records.append(_as_alert_record(item))

    records.extend(_kr_rows_as_global_alerts(kr_short_rows or []))
    return sorted(records, key=lambda x: (float(x.get('score', 0)), float(x.get('relative_strength_pctile', 0))), reverse=True)[:8]


def _scan_instrument(instrument: Instrument) -> dict | None:
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
    volume_ratio = _ratio(float(latest['volume']), float(latest['volume_ma20']))
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
    volume_confirm = volume_ratio >= (0.95 if instrument.asset_class.endswith('ETF') or instrument.market == 'Commodity' else 1.20)
    exhaustion_guard = rsi14 <= 78 and gap_ma20 <= 0.18 and ret21 <= 0.30
    stop_distance = max(atr14 * 2.2, price * 0.045)
    stop = max(price - stop_distance, price * 0.80)
    risk_pct = (price - stop) / price * 100.0 if price > 0 else 0.0
    rr_ok = 3.0 <= risk_pct <= 12.0
    rs_raw = ret126 * 0.45 + ret252 * 0.35 + ret63 * 0.20

    score = 0.0
    score += 18.0 if trend_ok else -12.0
    score += 18.0 if tsmom_aligned else -10.0
    score += 16.0 if breakout55 else 10.0 if breakout20 else -5.0
    score += 12.0 if volume_confirm else -6.0
    score += 10.0 if 45 <= rsi14 <= 70 else 4.0 if 70 < rsi14 <= 78 else -10.0
    score += 8.0 if rr_ok else -8.0
    score += min(max(rs_raw * 35.0, -8.0), 14.0)
    if not exhaustion_guard:
        score -= 15.0

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
        'volume_ratio_20d': round(volume_ratio, 2),
        'breakout20': bool(breakout20),
        'breakout55': bool(breakout55),
        'trend_ok': bool(trend_ok),
        'tsmom_aligned': bool(tsmom_aligned),
        'exhaustion_guard': bool(exhaustion_guard),
        'risk_pct': round(risk_pct, 2),
        'entry': round(price, 2),
        'stop_loss': round(stop, 2),
        'target1': round(price + (price - stop) * 2.0, 2),
        'target2': round(price + (price - stop) * 3.2, 2),
        'timestamp_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
    }


def _passes_global_gate(item: dict) -> bool:
    return (
        float(item.get('score', 0)) >= 72.0
        and float(item.get('relative_strength_pctile', 0)) >= 0.80
        and bool(item.get('trend_ok'))
        and bool(item.get('tsmom_aligned'))
        and bool(item.get('exhaustion_guard'))
        and (bool(item.get('breakout20')) or bool(item.get('breakout55')))
    )


def _as_alert_record(item: dict) -> dict:
    breakout = '55일 신고가권' if item.get('breakout55') else '20일 신고가권'
    reason = (
        f"{breakout} + 3/6/12개월 TSMOM 정렬 + 상대강도 상위 "
        f"{float(item.get('relative_strength_pctile', 0)) * 100:.0f}% + "
        f"거래량 {item.get('volume_ratio_20d')}배 + RSI {item.get('rsi14')}"
    )
    return {
        'ticker': item['ticker'],
        'name': item['name'],
        'market': item['market'],
        'asset_class': item['asset_class'],
        'direction': 'LONG',
        'strategy_type': 'global_tsmom_breakout',
        'score': item['score'],
        'relative_strength_pctile': round(float(item.get('relative_strength_pctile', 0)), 4),
        'current_price': item['current_price'],
        'entry': item['entry'],
        'stop_loss': item['stop_loss'],
        'target1': item['target1'],
        'target2': item['target2'],
        'risk_pct': item['risk_pct'],
        'ret_1m_pct': item['ret_1m_pct'],
        'ret_3m_pct': item['ret_3m_pct'],
        'ret_6m_pct': item['ret_6m_pct'],
        'ret_12m_pct': item['ret_12m_pct'],
        'rsi14': item['rsi14'],
        'volume_ratio_20d': item['volume_ratio_20d'],
        'reason': reason,
        'failure_condition': '종가 기준 MA20 이탈, 돌파선 재이탈, 거래량 급감, 또는 stop_loss 이탈',
        'source_strategy': 'FinRL/TradingAgents inspired deterministic factor stack',
        'timestamp_kst': item['timestamp_kst'],
    }


def _kr_rows_as_global_alerts(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        setup = str(row.get('strategy_type') or '')
        score = float(row.get('score') or 0.0)
        if setup not in STRONG_KR_SETUPS or score < 72.0:
            continue
        out.append({
            'ticker': str(row.get('code', '')).zfill(6),
            'name': row.get('name', ''),
            'market': 'KR',
            'asset_class': 'KR Stock',
            'direction': 'LONG',
            'strategy_type': f'kr_{setup}',
            'score': round(score, 1),
            'relative_strength_pctile': 1.0,
            'current_price': row.get('current_price'),
            'entry': row.get('entry'),
            'stop_loss': row.get('stop_loss'),
            'target1': row.get('target1'),
            'target2': row.get('target2'),
            'risk_pct': row.get('risk_pct'),
            'ret_1m_pct': row.get('momentum_20d_pct'),
            'ret_3m_pct': row.get('momentum_60d_pct'),
            'ret_6m_pct': None,
            'ret_12m_pct': None,
            'rsi14': row.get('rsi14'),
            'volume_ratio_20d': row.get('volume_ratio_20d'),
            'reason': f"KR 기존 단기 스캐너 강신호: {row.get('reason', '')}",
            'failure_condition': row.get('failure_condition') or 'MA20/손절가 이탈',
            'source_strategy': 'existing KR runtime scanner + global alert bridge',
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
        item['score'] = round(min(100.0, float(item.get('score', 0)) + max(0.0, item['relative_strength_pctile'] - 0.70) * 30.0), 1)


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
