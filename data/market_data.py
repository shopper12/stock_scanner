from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from config import settings
from data import mock_data


def get_us_etf_universe() -> pd.DataFrame:
    return mock_data.us_etf_universe()


def get_us_history(ticker: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.us_history(ticker)
    try:
        import yfinance as yf
        raw = yf.download(ticker, period='18mo', interval='1d', auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError('empty yfinance response')
        return _normalise_yahoo_ohlcv(raw)
    except Exception as exc:
        return _fallback_or_raise(lambda: mock_data.us_history(ticker), f'US history fetch failed for {ticker}', exc)


def get_fx_history() -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.fx_history()
    try:
        import yfinance as yf
        usdkrw = yf.download('KRW=X', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        dxy = yf.download('DX-Y.NYB', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        us10y = yf.download('^TNX', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        vix = yf.download('^VIX', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        df = usdkrw[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'usdkrw'})
        df = df.merge(dxy[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'dxy'}), on='date', how='left')
        df = df.merge(us10y[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'us10y'}), on='date', how='left')
        df = df.merge(vix[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'vix'}), on='date', how='left')
        return df.ffill().dropna()
    except Exception as exc:
        return _fallback_or_raise(mock_data.fx_history, 'FX history fetch failed', exc)


def get_kr_retirement_etfs() -> pd.DataFrame:
    return mock_data.kr_etf_universe()


def get_kr_etf_history(code: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.kr_etf_history(code)
    try:
        return _get_kr_yahoo_history(code, lookback_days=420)
    except Exception as exc:
        return _fallback_or_raise(lambda: mock_data.kr_etf_history(code), f'KR ETF history fetch failed for {code}', exc)


def get_kr_stock_universe() -> pd.DataFrame:
    base = _ensure_sector(mock_data.kr_stock_universe()).copy()
    today = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y%m%d')
    base['market'] = base.get('market', 'WATCH')
    base['trade_date'] = today
    base['trade_value_today'] = pd.to_numeric(base.get('trade_value_today', 0), errors='coerce').fillna(0)
    base['volume_today'] = pd.to_numeric(base.get('volume_today', 0), errors='coerce').fillna(0)
    base['close_today'] = pd.to_numeric(base.get('close_today', 0), errors='coerce').fillna(0)
    return base.reset_index(drop=True)


def get_kr_stock_history(code: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.kr_stock_history(code)
    try:
        return _get_kr_yahoo_history(code, lookback_days=260)
    except Exception as exc:
        return _fallback_or_raise(lambda: mock_data.kr_stock_history(code), f'KR stock history fetch failed for {code}', exc)


def get_retirement_positions() -> pd.DataFrame:
    return mock_data.retirement_positions()


def _fallback_or_raise(fallback, message: str, exc: Exception) -> pd.DataFrame:
    if settings.allow_data_fallback:
        return fallback()
    raise RuntimeError(message) from exc


def _get_kr_yahoo_history(code: str, lookback_days: int) -> pd.DataFrame:
    import yfinance as yf
    period = '3y' if lookback_days >= 420 else '18mo'
    last_error: Exception | None = None
    for suffix in ('.KS', '.KQ'):
        ticker = f"{str(code).zfill(6)}{suffix}"
        try:
            raw = yf.download(ticker, period=period, interval='1d', auto_adjust=True, progress=False)
            if raw is None or raw.empty:
                raise ValueError(f'empty yfinance response for {ticker}')
            df = _normalise_yahoo_ohlcv(raw)
            if len(df) < min(80, lookback_days // 3):
                raise ValueError(f'insufficient yfinance rows for {ticker}: {len(df)}')
            return df.tail(lookback_days).reset_index(drop=True)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f'No Yahoo KR history for {code}') from last_error


def _normalise_yahoo_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={'Date': 'date', 'Datetime': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'trade_value' not in df.columns:
        df['trade_value'] = df['close'] * df['volume']
    return df[['date', 'open', 'high', 'low', 'close', 'volume', 'trade_value']].dropna().reset_index(drop=True)


def _recent_kr_dates(days: int) -> list[str]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(days)]


def _ensure_sector(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'sector' not in out.columns:
        out['sector'] = out.apply(lambda r: _infer_sector(str(r.get('code', '')), str(r.get('name', ''))), axis=1)
    return out


def _infer_sector(code: str, name: str) -> str:
    known = {'005930': '반도체', '000660': '반도체', '042700': '반도체장비', '267260': '전력기기', '034020': '원전/에너지', '010120': '전력기기', '064350': '방산/철도', '352820': '엔터'}
    if code in known:
        return known[code]
    sector_rules = [
        ('반도체', ['반도체', '하이닉스', 'HPSP', 'ISC', '리노공업', '테크윙', '원익', '솔브레인']),
        ('전력기기', ['일렉트릭', '전선', '전기', '효성중공업', '제룡']),
        ('조선/해양', ['조선', '오션', '마린', '엔진']),
        ('방산/우주', ['로템', '에어로', '항공', '스페이스', '풍산']),
        ('바이오', ['바이오', '셀트리온', '제약', '헬스', '알테오젠']),
        ('자동차', ['차', '모비스', '타이어', '만도']),
        ('AI/로봇', ['로봇', 'AI', '소프트', '시스템', '네이버', '카카오']),
        ('금융', ['금융', '은행', '증권', '보험']),
        ('2차전지', ['에코프로', '포스코퓨처', '엘앤에프', '금양', '코스모']),
        ('화장품/소비', ['화장품', '아모레', '실리콘투', '식품', '호텔']),
    ]
    upper_name = name.upper()
    for sector, keywords in sector_rules:
        if any(k.upper() in upper_name for k in keywords):
            return sector
    return '기타'
