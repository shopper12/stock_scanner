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
        usdkrw = _normalise_yahoo_close(yf.download('KRW=X', period='9mo', interval='1d', auto_adjust=True, progress=False), 'usdkrw')
        dxy = _normalise_yahoo_close(yf.download('DX-Y.NYB', period='9mo', interval='1d', auto_adjust=True, progress=False), 'dxy')
        us10y = _normalise_yahoo_close(yf.download('^TNX', period='9mo', interval='1d', auto_adjust=True, progress=False), 'us10y')
        vix = _normalise_yahoo_close(yf.download('^VIX', period='9mo', interval='1d', auto_adjust=True, progress=False), 'vix')
        df = usdkrw.merge(dxy, on='date', how='left')
        df = df.merge(us10y, on='date', how='left')
        df = df.merge(vix, on='date', how='left')
        return df.sort_values('date').ffill().dropna().reset_index(drop=True)
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
    base['market'] = _series_or_default(base, 'market', 'WATCH')
    base['trade_date'] = today
    base['trade_value_today'] = _numeric_series_or_zero(base, 'trade_value_today')
    base['volume_today'] = _numeric_series_or_zero(base, 'volume_today')
    base['close_today'] = _numeric_series_or_zero(base, 'close_today')
    return base.reset_index(drop=True)


def get_kr_stock_history(code: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.kr_stock_history(code)
    try:
        return _get_kr_yahoo_history(code, lookback_days=260)
    except Exception as exc:
        return _fallback_or_raise(lambda: mock_data.kr_stock_history(code), f'KR stock history failed for {code}', exc)


def get_retirement_positions() -> pd.DataFrame:
    return mock_data.retirement_positions()


def _series_or_default(df: pd.DataFrame, column: str, default) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series([default] * len(df), index=df.index)


def _numeric_series_or_zero(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_series_or_default(df, column, 0), errors='coerce').fillna(0)


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
    if raw is None or raw.empty:
        raise ValueError('empty yfinance OHLCV response')
    df = _reset_yahoo_frame(raw)
    date_col = _find_date_column(df)
    open_col = _first_existing_column(df, ('Open', 'open'))
    high_col = _first_existing_column(df, ('High', 'high'))
    low_col = _first_existing_column(df, ('Low', 'low'))
    close_col = _first_existing_column(df, ('Close', 'Adj Close', 'close', 'adjclose'))
    volume_col = _first_existing_column(df, ('Volume', 'volume'), required=False)

    out = pd.DataFrame(
        {
            'date': pd.to_datetime(df[date_col], errors='coerce'),
            'open': pd.to_numeric(df[open_col], errors='coerce'),
            'high': pd.to_numeric(df[high_col], errors='coerce'),
            'low': pd.to_numeric(df[low_col], errors='coerce'),
            'close': pd.to_numeric(df[close_col], errors='coerce'),
            'volume': pd.to_numeric(df[volume_col], errors='coerce').fillna(0) if volume_col else 0,
        }
    )
    out['trade_value'] = out['close'] * out['volume']
    return out[['date', 'open', 'high', 'low', 'close', 'volume', 'trade_value']].dropna(subset=['date', 'open', 'high', 'low', 'close']).reset_index(drop=True)


def _normalise_yahoo_close(raw: pd.DataFrame, value_name: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError(f'empty yfinance response for {value_name}')
    df = _reset_yahoo_frame(raw)
    date_col = _find_date_column(df)
    close_col = _first_existing_column(df, ('Close', 'Adj Close', 'close', 'adjclose'))
    out = pd.DataFrame(
        {
            'date': pd.to_datetime(df[date_col], errors='coerce'),
            value_name: pd.to_numeric(df[close_col], errors='coerce'),
        }
    )
    return out.dropna().reset_index(drop=True)


def _reset_yahoo_frame(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [_normalise_column_name(column) for column in df.columns]
    df = df.reset_index()
    df.columns = [_normalise_column_name(column) for column in df.columns]
    return df.loc[:, ~pd.Index(df.columns).duplicated()].copy()


def _normalise_column_name(column) -> str:
    if isinstance(column, tuple):
        parts = [str(part) for part in column if part is not None and str(part) and str(part) != 'nan']
        price_names = {'Date', 'Datetime', 'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume'}
        for part in parts:
            if part in price_names:
                return part
        return '_'.join(parts) if parts else 'index'
    return str(column)


def _find_date_column(df: pd.DataFrame) -> str:
    preferred = _first_existing_column(df, ('Date', 'Datetime', 'date', 'datetime', 'index'), required=False)
    if preferred:
        return preferred
    for column in df.columns:
        converted = pd.to_datetime(df[column], errors='coerce')
        if converted.notna().mean() >= 0.8:
            return column
    raise KeyError(f'no date-like column found in {list(df.columns)}')


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...], required: bool = True) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    if required:
        raise KeyError(f'none of columns {candidates} found in {list(df.columns)}')
    return None


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
