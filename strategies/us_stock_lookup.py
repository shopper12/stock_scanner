from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from config import settings

US_ALIASES = {
    '애플': 'AAPL', 'apple': 'AAPL',
    '마이크로소프트': 'MSFT', 'microsoft': 'MSFT',
    '엔비디아': 'NVDA', 'nvidia': 'NVDA',
    '테슬라': 'TSLA', 'tesla': 'TSLA',
    '아마존': 'AMZN', 'amazon': 'AMZN',
    '구글': 'GOOGL', '알파벳': 'GOOGL', 'google': 'GOOGL', 'alphabet': 'GOOGL',
    '메타': 'META', 'meta': 'META',
    '브로드컴': 'AVGO', 'broadcom': 'AVGO',
    '팔란티어': 'PLTR', 'palantir': 'PLTR',
    '코인베이스': 'COIN', 'coinbase': 'COIN',
    '마이크론': 'MU', 'micron': 'MU',
    '슈퍼마이크로': 'SMCI', 'supermicro': 'SMCI',
    'amd': 'AMD', 'soxl': 'SOXL', 'tqqq': 'TQQQ', 'sqqq': 'SQQQ',
    'spy': 'SPY', 'qqq': 'QQQ', 'voo': 'VOO', 'koru': 'KORU',
}


def is_us_stock_query(query: str) -> bool:
    q = str(query or '').strip()
    key = q.lower().replace(' ', '')
    if key in US_ALIASES:
        return True
    cleaned = q.upper().replace('$', '').strip()
    return bool(cleaned and cleaned.isascii() and cleaned.replace('.', '').replace('-', '').isalpha() and 1 <= len(cleaned) <= 8)


def analyze_us_stock_strategy(query: str) -> dict:
    ticker = _resolve_us_ticker(query)
    hist = yf.download(ticker, period='1y', interval='1d', progress=False, auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f'no US history for {ticker}')
    hist = _flatten_history(hist).tail(252).copy()
    if len(hist) < 65:
        raise RuntimeError(f'insufficient US history for {ticker}: {len(hist)} rows')

    close = pd.to_numeric(hist['close'], errors='coerce')
    high = pd.to_numeric(hist['high'], errors='coerce')
    low = pd.to_numeric(hist['low'], errors='coerce')
    volume = pd.to_numeric(hist['volume'], errors='coerce').fillna(0)
    price = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    ma120 = float(close.rolling(120).mean().iloc[-1]) if len(close) >= 120 else ma60
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else ma120
    high20 = float(high.iloc[-21:-1].max())
    high60 = float(high.iloc[-61:-1].max())
    high252 = float(high.max())
    low10 = float(low.tail(10).min())
    ret5 = price / float(close.iloc[-6]) - 1.0
    ret20 = price / float(close.iloc[-21]) - 1.0
    ret60 = price / float(close.iloc[-61]) - 1.0
    drawdown52w = price / high252 - 1.0 if high252 else 0.0
    drawdown60 = price / high60 - 1.0 if high60 else 0.0
    gap_ma20 = price / ma20 - 1.0 if ma20 else 0.0
    volume_ma20 = float(volume.rolling(20).mean().iloc[-1] or 0.0)
    volume_ratio = float(volume.iloc[-1] / volume_ma20) if volume_ma20 > 0 else 0.0
    atr14 = _atr14(high, low, close)
    rsi14 = _rsi14(close)
    setup = _setup(price, ma20, ma60, ma120, ma200, high20, ret5, ret20, drawdown52w, volume_ratio)
    score = _score(price, ma20, ma60, ma120, ma200, ret5, ret20, ret60, drawdown52w, gap_ma20, rsi14, volume_ratio, setup)
    entry = _entry(price, high20, ma20, setup)
    stop = _stop(price, ma20, ma60, low10, atr14, setup)
    if stop >= min(price, entry):
        stop = min(price, entry) * 0.96
    risk_pct = (entry - stop) / entry * 100.0 if entry else 0.0
    target1 = max(entry, price) * (1.06 if setup == 'theme_repricing_breakout' else 1.08)
    target2 = max(entry, price) * (1.13 if setup == 'theme_repricing_breakout' else 1.16)
    name, sector = _ticker_info(ticker)
    threshold = 58.0
    action, action_reason = _action(score, threshold, setup, risk_pct, entry, price)
    label = f'{name}({ticker})'
    return {
        'ok': True,
        'asset_class': 'US_STOCK',
        'query': query,
        'resolved_by': 'us_ticker_or_alias',
        'display_name': label,
        'stock_label': label,
        'title': label,
        'created_at_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'code': ticker,
        'name': name,
        'market': 'US',
        'sector': sector,
        'action': action,
        'action_reason': action_reason,
        'score': round(score, 1),
        'threshold': threshold,
        'setup': setup,
        'current_price': round(price, 2),
        'price_basis': 'yfinance_daily_close',
        'price_timestamp': str(hist.index[-1].date()) if hasattr(hist.index[-1], 'date') else str(hist.index[-1])[:10],
        'quote_source': 'yfinance',
        'quote_ok': True,
        'quote_error': None,
        'entry': round(entry, 2),
        'stop_loss': round(stop, 2),
        'target1': round(target1, 2),
        'target2': round(target2, 2),
        'risk_pct': round(risk_pct, 2),
        'position_size_krw': 0,
        'holding_period': '당일~10일',
        'reason': f'{sector} / {setup} / 20일 모멘텀 {ret20 * 100:.2f}% / 52주 고점대비 {drawdown52w * 100:.2f}% / RSI {rsi14:.1f}',
        'failure_condition': '종가가 stop_loss 하회, 거래량 급감, 나스닥/섹터 급락 시 무효',
        'data_source': 'yfinance',
        'scanner_exclusion_diagnosis': {'selected': None, 'display_name': label, 'reason': '미국 주식은 검색 분석 대상입니다. 한국 단기 추천 top N과는 별도입니다.'},
        'metrics': {
            'ma20': round(ma20, 2), 'ma60': round(ma60, 2), 'ma120': round(ma120, 2), 'ma200': round(ma200, 2),
            'rsi14': round(rsi14, 1), 'volume_ratio_20d': round(volume_ratio, 2), 'trade_value_ratio_20d': 0.0,
            'trade_value_krw': 0, 'momentum_5d_pct': round(ret5 * 100, 2), 'momentum_20d_pct': round(ret20 * 100, 2),
            'momentum_60d_pct': round(ret60 * 100, 2), 'drawdown_60d_pct': round(drawdown60 * 100, 2),
            'drawdown_52w_pct': round(drawdown52w * 100, 2), 'gap_ma20_pct': round(gap_ma20 * 100, 2),
        },
    }


def _resolve_us_ticker(query: str) -> str:
    q = str(query or '').strip()
    key = q.lower().replace(' ', '')
    if key in US_ALIASES:
        return US_ALIASES[key]
    return q.upper().replace('$', '').strip()


def _flatten_history(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(col[0]).lower() for col in out.columns]
    else:
        out.columns = [str(col).lower().replace(' ', '_') for col in out.columns]
    return out.dropna(subset=['close'])


def _ticker_info(ticker: str) -> tuple[str, str]:
    try:
        info = yf.Ticker(ticker).get_info()
        return str(info.get('shortName') or info.get('longName') or ticker), str(info.get('sector') or info.get('quoteType') or 'US')
    except Exception:
        return ticker, 'US'


def _setup(price: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, ret5: float, ret20: float, drawdown52w: float, volume_ratio: float) -> str:
    if price > ma20 > ma60 > ma120 and price > ma200 and price >= high20 * 0.995:
        return 'breakout'
    if price > ma20 and price > ma60 and ret5 >= 0.04 and ret20 >= 0.07 and volume_ratio >= 1.2:
        return 'theme_repricing_breakout'
    if -0.10 <= drawdown52w <= -0.03 and price > ma20:
        return 'first_pullback_after_high'
    if price > ma20 and price > ma60 and price > ma200:
        return 'trend_continuation'
    return 'watch'


def _score(price: float, ma20: float, ma60: float, ma120: float, ma200: float, ret5: float, ret20: float, ret60: float, drawdown52w: float, gap_ma20: float, rsi14: float, volume_ratio: float, setup: str) -> float:
    score = 50.0
    score += 8.0 if price > ma200 else -10.0
    score += 5.0 if price > ma60 else -4.0
    score += 5.0 if price > ma20 else -3.0
    score += 4.0 if ma20 > ma60 else -2.0
    score += max(min(ret20 * 35.0, 10.0), -8.0)
    score += max(min(ret60 * 20.0, 8.0), -8.0)
    score += max(min(ret5 * 20.0, 4.0), -4.0)
    score += max(min((volume_ratio - 1.0) * 5.0, 6.0), 0.0)
    if 45 <= rsi14 <= 65:
        score += 5.0
    elif rsi14 > 80:
        score -= 12.0
    elif rsi14 > 72:
        score -= 5.0
    if -0.12 <= drawdown52w <= -0.03 and price > ma20:
        score += 5.0
    if gap_ma20 > 0.15 and setup != 'theme_repricing_breakout':
        score -= 8.0
    if setup == 'theme_repricing_breakout':
        score += 7.0
    elif setup == 'first_pullback_after_high':
        score += 8.0
    elif setup == 'breakout':
        score += 2.0
    elif setup == 'watch':
        score -= 8.0
    return max(0.0, min(score, 100.0))


def _entry(price: float, high20: float, ma20: float, setup: str) -> float:
    return max(price * 1.003, high20 * 1.001) if setup == 'breakout' else max(price, ma20 * 1.003) if setup == 'first_pullback_after_high' else price


def _stop(price: float, ma20: float, ma60: float, low10: float, atr14: float, setup: str) -> float:
    atr_line = price - atr14 * (2.0 if setup == 'theme_repricing_breakout' else 1.6)
    structure = min(low10 * 0.99, ma20 * 0.97)
    trend = ma60 * 0.965 if price > ma60 else price * 0.94
    return max(min(atr_line, structure), trend)


def _action(score: float, threshold: float, setup: str, risk_pct: float, entry: float, price: float) -> tuple[str, str]:
    if score < threshold:
        return '관망', f'점수 {score:.1f}가 기준 {threshold:.1f} 미만입니다.'
    if risk_pct > 14.0:
        return '회피', f'손절폭 {risk_pct:.2f}%가 넓어 단기 진입 위험이 큽니다.'
    if entry / price - 1.0 > 0.04:
        return '조건부 대기', '진입가가 현재가보다 멀어 추격매수 금지입니다.'
    return ('매수 후보', '미국 종목 단기 조건을 통과했습니다.') if setup in {'theme_repricing_breakout', 'first_pullback_after_high', 'breakout'} else ('조건부 매수', '추세는 양호하나 확인 진입이 맞습니다.')


def _atr14(high: pd.Series, low: pd.Series, close: pd.Series) -> float:
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return float(tr.rolling(14).mean().iloc[-1])


def _rsi14(close: pd.Series) -> float:
    delta = close.diff().dropna().tail(14)
    gains = delta.clip(lower=0).mean()
    losses = (-delta.clip(upper=0)).mean()
    if losses <= 0:
        return 100.0 if gains > 0 else 50.0
    return float(100.0 - (100.0 / (1.0 + gains / losses)))
