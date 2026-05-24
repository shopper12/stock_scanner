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
        .us_history(ticker)
    try:
        import yfinance as yf

        raw = yf.download(ticker, period='18mo', interval='1d', auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError('empty yfinance response')
        raw = raw.reset_index().rename(
            columns={'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
        )
        return raw[['date', 'open', 'high', 'low', 'close', 'volume']].dropna()
    except Exception:
        return mock_data.us_history(ticker)


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
    except Exception:
        return mock_data.fx_history()


def get_kr_retirement_etfs() -> pd.DataFrame:
    return mock_data.kr_etf_universe()


def get_kr_etf_history(code: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.kr_etf_history(code)
    try:
        return _get_kr_ohlcv_by_date(code, lookback_days=420)
    except Exception:
        return mock_data.kr_etf_history(code)


def get_kr_stock_universe() -> pd.DataFrame:
    if settings.use_mock_data:
        return _ensure_sector(mock_data.kr_stock_universe())

    try:
        trade_date, frame = _latest_kr_market_snapshot()
        frame = frame.copy()
        frame['code'] = frame.index.astype(str).str.zfill(6)
        frame['name'] = frame['code'].map(_ticker_name)
        frame['trade_value_today'] = pd.to_numeric(frame.get('거래대금', 0), errors='coerce').fillna(0)
        frame['volume_today'] = pd.to_numeric(frame.get('거래량', 0), errors='coerce').fillna(0)
        frame['close_today'] = pd.to_numeric(frame.get('종가', 0), errors='coerce').fillna(0)
        frame = frame[(frame['trade_value_today'] > 0) & (frame['volume_today'] > 0) & (frame['close_today'] >= settings.min_kr_price)]
        frame = frame.sort_values('trade_value_today', ascending=False).head(settings.kr_universe_top_n)
        out = frame[['code', 'name', 'market', 'trade_date', 'trade_value_today', 'volume_today', 'close_today']].reset_index(drop=True)

        # Always keep several user-relevant momentum sectors in the universe even if a single-day turnover rank misses them.
        watch = _ensure_sector(mock_data.kr_stock_universe())
        out_codes = set(out['code'])
        missing_watch = watch[~watch['code'].isin(out_codes)].copy()
        if not missing_watch.empty:
            missing_watch['market'] = 'WATCH'
            missing_watch['trade_date'] = trade_date
            missing_watch['trade_value_today'] = 0
            missing_watch['volume_today'] = 0
            missing_watch['close_today'] = 0
            out = pd.concat([out, missing_watch[out.columns]], ignore_index=True)
        return _ensure_sector(out)
    except Exception:
        return _ensure_sector(mock_data.kr_stock_universe())


def get_kr_stock_history(code: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.kr_stock_history(code)
    try:
        return _get_kr_ohlcv_by_date(code, lookback_days=260)
    except Exception as exc:
    if settings.allow_data_fallback:
        return mock_data.kr_stock_history(code)
    raise RuntimeError(f'KR stock history fetch failed for {code}') from exc


def get_retirement_positions() -> pd.DataFrame:
    return mock_data.retirement_positions()


def _latest_kr_market_snapshot() -> tuple[str, pd.DataFrame]:
    from pykrx import stock

    frames = []
    for yyyymmdd in _recent_kr_dates(14):
        frames.clear()
        for market in ('KOSPI', 'KOSDAQ'):
            df = stock.get_market_ohlcv_by_ticker(yyyymmdd, market=market)
            if df is None or df.empty:
                continue
            df = df.copy()
            df['market'] = market
            df['trade_date'] = yyyymmdd
            frames.append(df)
        if frames:
            return yyyymmdd, pd.concat(frames, axis=0)
    raise ValueError('No recent KRX market snapshot')


def _get_kr_ohlcv_by_date(code: str, lookback_days: int) -> pd.DataFrame:
    from pykrx import stock

    end = datetime.now(ZoneInfo(settings.timezone)).date()
    start = end - timedelta(days=lookback_days * 2)
    raw = stock.get_market_ohlcv_by_date(start.strftime('%Y%m%d'), end.strftime('%Y%m%d'), str(code).zfill(6))
    if raw is None or raw.empty:
        raise ValueError(f'empty pykrx response for {code}')
    return _normalise_kr_ohlcv(raw)


def _normalise_kr_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.reset_index()
    first_col = df.columns[0]
    df = df.rename(
        columns={
            first_col: 'date',
            '날짜': 'date',
            '시가': 'open',
            '고가': 'high',
            '저가': 'low',
            '종가': 'close',
            '거래량': 'volume',
            '거래대금': 'trade_value',
        }
    )
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'trade_value' not in df.columns:
        df['trade_value'] = df['close'] * df['volume']
    else:
        df['trade_value'] = pd.to_numeric(df['trade_value'], errors='coerce').fillna(df['close'] * df['volume'])
    return df[['date', 'open', 'high', 'low', 'close', 'volume', 'trade_value']].dropna().reset_index(drop=True)


def _recent_kr_dates(days: int) -> list[str]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(days)]


def _ticker_name(code: str) -> str:
    try:
        from pykrx import stock

        return stock.get_market_ticker_name(str(code).zfill(6)) or str(code).zfill(6)
    except Exception:
        return str(code).zfill(6)


def _ensure_sector(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'sector' not in out.columns:
        out['sector'] = out.apply(lambda r: _infer_sector(str(r.get('code', '')), str(r.get('name', ''))), axis=1)
    return out


def _infer_sector(code: str, name: str) -> str:
    known = {
        '005930': '반도체',
        '000660': '반도체',
        '042700': '반도체장비',
        '267260': '전력기기',
        '034020': '원전/에너지',
        '010120': '전력기기',
        '064350': '방산/철도',
        '352820': '엔터',
    }
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
