from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from config import settings
from data import mock_data

_LAST_KR_SECTOR_SNAPSHOT: list[dict] = []


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
        return _get_kr_pykrx_history(code, lookback_days=420)
    except Exception:
        try:
            return _get_kr_yahoo_history(code, lookback_days=420)
        except Exception as exc:
            return _fallback_or_raise(lambda: mock_data.kr_etf_history(code), f'KR ETF history fetch failed for {code}', exc)


def get_kr_stock_universe() -> pd.DataFrame:
    if settings.use_mock_data:
        return _ensure_sector(mock_data.kr_stock_universe()).reset_index(drop=True)
    try:
        live = _get_dynamic_kr_stock_universe()
        if not live.empty:
            return live
        raise RuntimeError('empty dynamic KR universe')
    except Exception as exc:
        return _fallback_or_raise(lambda: _ensure_sector(mock_data.kr_stock_universe()).reset_index(drop=True), 'Dynamic KR stock universe fetch failed', exc)


def get_kr_sector_snapshot() -> list[dict]:
    return list(_LAST_KR_SECTOR_SNAPSHOT)


def get_kr_stock_history(code: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.kr_stock_history(code)
    try:
        return _get_kr_pykrx_history(code, lookback_days=420)
    except Exception:
        try:
            return _get_kr_yahoo_history(code, lookback_days=420)
        except Exception as exc:
            return _fallback_or_raise(lambda: mock_data.kr_stock_history(code), f'KR stock history fetch failed for {code}', exc)


def get_retirement_positions() -> pd.DataFrame:
    return mock_data.retirement_positions()


def _get_dynamic_kr_stock_universe() -> pd.DataFrame:
    global _LAST_KR_SECTOR_SNAPSHOT

    market_df, trade_date = _latest_kr_market_ohlcv()
    if market_df.empty:
        raise RuntimeError('empty pykrx market OHLCV')

    market_df = _attach_names_and_sectors(market_df)
    market_df = _filter_common_stocks(market_df)
    market_df = market_df[
        (market_df['close_today'] >= settings.min_kr_price)
        & (market_df['trade_value_today'] >= settings.min_kr_trade_value_krw)
    ].copy()
    if market_df.empty:
        raise RuntimeError('no liquid KR stocks after filters')

    sector_stats = _build_sector_stats(market_df)
    market_df = market_df.merge(sector_stats, on='sector', how='left')
    market_df['trade_date'] = trade_date
    market_df['market_rotation_score'] = market_df.apply(_market_rotation_score, axis=1)
    market_df = market_df.sort_values(
        ['market_rotation_score', 'sector_strength_score', 'trade_value_today', 'change_pct_today'],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    _LAST_KR_SECTOR_SNAPSHOT = (
        sector_stats.sort_values('sector_strength_score', ascending=False)
        .head(12)
        .round({'sector_strength_score': 2, 'sector_avg_change_pct': 2, 'sector_positive_ratio': 4})
        .to_dict('records')
    )
    top_n = settings.kr_universe_top_n_bull if settings.bull_market_mode else settings.kr_universe_top_n
    return _select_universe_candidates(market_df, int(top_n))


def _latest_kr_market_ohlcv(max_lookback_days: int = 10) -> tuple[pd.DataFrame, str]:
    from pykrx import stock

    last_error: Exception | None = None
    for date in _recent_kr_dates(max_lookback_days):
        frames = []
        for market in ('KOSPI', 'KOSDAQ'):
            try:
                raw = stock.get_market_ohlcv_by_ticker(date, market=market)
                if raw is None or raw.empty:
                    continue
                frame = raw.copy()
                frame['code'] = frame.index.astype(str).str.zfill(6)
                frame['market'] = market
                frames.append(frame)
            except Exception as exc:
                last_error = exc
        if not frames:
            continue
        out = pd.concat(frames, ignore_index=True)
        out = out.rename(columns={
            '종가': 'close_today',
            '거래량': 'volume_today',
            '거래대금': 'trade_value_today',
            '등락률': 'change_pct_today',
        })
        required = ['code', 'market', 'close_today', 'volume_today', 'trade_value_today', 'change_pct_today']
        missing = [col for col in required if col not in out.columns]
        if missing:
            last_error = KeyError(f'missing pykrx columns {missing}; available={list(out.columns)}')
            continue
        for col in ['close_today', 'volume_today', 'trade_value_today', 'change_pct_today']:
            out[col] = pd.to_numeric(out[col], errors='coerce').fillna(0)
        if (out['trade_value_today'] > 0).any():
            return out[required], date
    raise RuntimeError('No recent KRX market data') from last_error


def _attach_names_and_sectors(df: pd.DataFrame) -> pd.DataFrame:
    from pykrx import stock

    out = df.copy()
    name_cache: dict[str, str] = {}
    names = []
    for code in out['code'].astype(str).str.zfill(6):
        if code not in name_cache:
            try:
                name_cache[code] = stock.get_market_ticker_name(code) or ''
            except Exception:
                name_cache[code] = ''
        names.append(name_cache[code])
    out['name'] = names
    out['sector'] = out.apply(lambda r: _infer_sector(str(r.get('code', '')), str(r.get('name', ''))), axis=1)
    return out


def _filter_common_stocks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    name = out['name'].astype(str)
    exclude_name_patterns = [
        '스팩', 'SPAC', 'ETN', 'ETF', '선물', '인버스', '레버리지', '리츠',
        '우선주', '우B', '우C', '우(', '1우', '2우', '3우', '4우',
    ]
    mask = name.str.len().gt(0)
    for pattern in exclude_name_patterns:
        mask &= ~name.str.contains(pattern, case=False, regex=False, na=False)
    return out[mask].copy()


def _build_sector_stats(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby('sector', dropna=False).agg(
        sector_member_count=('code', 'count'),
        sector_trade_value_krw=('trade_value_today', 'sum'),
        sector_avg_change_pct=('change_pct_today', 'mean'),
        sector_positive_count=('change_pct_today', lambda s: int((s > 0).sum())),
    ).reset_index()
    grouped['sector_positive_ratio'] = grouped['sector_positive_count'] / grouped['sector_member_count'].clip(lower=1)
    trade_rank = grouped['sector_trade_value_krw'].rank(pct=True)
    change_rank = grouped['sector_avg_change_pct'].rank(pct=True)
    breadth_rank = grouped['sector_positive_ratio'].rank(pct=True)
    grouped['sector_strength_score'] = (trade_rank * 45.0 + change_rank * 35.0 + breadth_rank * 20.0).clip(0, 100)
    grouped['sector_rank'] = grouped['sector_strength_score'].rank(method='dense', ascending=False).astype(int)
    return grouped.sort_values('sector_strength_score', ascending=False).reset_index(drop=True)


def _market_rotation_score(row: pd.Series) -> float:
    score = 0.0
    score += min(float(row.get('sector_strength_score', 0.0)) * 0.45, 45.0)
    score += min(max(float(row.get('change_pct_today', 0.0)), -5.0), 15.0) * 2.0
    trade_value = float(row.get('trade_value_today', 0.0))
    score += min(trade_value / max(settings.min_kr_trade_value_krw, 1.0) * 6.0, 30.0)
    if int(row.get('sector_rank', 99)) <= 3:
        score += 8.0
    if float(row.get('change_pct_today', 0.0)) < 0:
        score -= 8.0
    return max(0.0, min(100.0, score))


def _select_universe_candidates(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if df.empty:
        return df
    top_n = max(20, min(top_n, 200))
    selected = []
    selected_codes = set()
    per_sector_cap = max(5, top_n // 8)
    sector_counts: dict[str, int] = {}

    for _, row in df.iterrows():
        sector = str(row.get('sector', '기타'))
        if sector_counts.get(sector, 0) >= per_sector_cap:
            continue
        selected.append(row)
        selected_codes.add(row['code'])
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= top_n:
            break

    if len(selected) < top_n:
        for _, row in df.iterrows():
            if row['code'] in selected_codes:
                continue
            selected.append(row)
            selected_codes.add(row['code'])
            if len(selected) >= top_n:
                break

    columns = [
        'code', 'name', 'sector', 'market', 'trade_date', 'close_today', 'volume_today',
        'trade_value_today', 'change_pct_today', 'sector_rank', 'sector_strength_score',
        'sector_trade_value_krw', 'sector_avg_change_pct', 'sector_positive_ratio',
        'market_rotation_score',
    ]
    return pd.DataFrame(selected)[columns].reset_index(drop=True)


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


def _get_kr_pykrx_history(code: str, lookback_days: int) -> pd.DataFrame:
    from pykrx import stock

    end = datetime.now(ZoneInfo(settings.timezone)).date()
    start = end - timedelta(days=int(lookback_days * 1.65))
    raw = stock.get_market_ohlcv_by_date(start.strftime('%Y%m%d'), end.strftime('%Y%m%d'), str(code).zfill(6))
    if raw is None or raw.empty:
        raise ValueError(f'empty pykrx history for {code}')
    df = raw.copy().reset_index()
    date_col = _first_existing_column(df, ('날짜', 'Date', 'date', 'index'))
    df = df.rename(columns={
        date_col: 'date',
        '시가': 'open',
        '고가': 'high',
        '저가': 'low',
        '종가': 'close',
        '거래량': 'volume',
        '거래대금': 'trade_value',
    })
    required = ('date', 'open', 'high', 'low', 'close', 'volume', 'trade_value')
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise KeyError(f'missing pykrx OHLCV columns {missing}; available={list(df.columns)}')
    for col in ('open', 'high', 'low', 'close', 'volume', 'trade_value'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df[['date', 'open', 'high', 'low', 'close', 'volume', 'trade_value']].dropna().tail(lookback_days).reset_index(drop=True)


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
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = _first_existing_column(df, ('Date', 'Datetime', 'date', 'datetime', 'index'))
    rename_map = {
        date_col: 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Adj Close': 'close',
        'Volume': 'volume',
    }
    df = df.rename(columns=rename_map)
    required = ('date', 'open', 'high', 'low', 'close', 'volume')
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise KeyError(f'missing OHLCV columns {missing}; available columns={list(df.columns)}')
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'trade_value' not in df.columns:
        df['trade_value'] = df['close'] * df['volume']
    return df[['date', 'open', 'high', 'low', 'close', 'volume', 'trade_value']].dropna().reset_index(drop=True)


def _normalise_yahoo_close(raw: pd.DataFrame, value_name: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError(f'empty yfinance response for {value_name}')
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = _first_existing_column(df, ('Date', 'Datetime', 'date', 'datetime', 'index'))
    close_col = _first_existing_column(df, ('Close', 'Adj Close', 'close', 'adjclose'))
    out = df[[date_col, close_col]].rename(columns={date_col: 'date', close_col: value_name})
    out[value_name] = pd.to_numeric(out[value_name], errors='coerce')
    return out.dropna().reset_index(drop=True)


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    for column in candidates:
        if column in df.columns:
            return column
    raise KeyError(f'none of columns {candidates} found in {list(df.columns)}')


def _recent_kr_dates(days: int) -> list[str]:
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(days)]


def _ensure_sector(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'sector' not in out.columns:
        out['sector'] = out.apply(lambda r: _infer_sector(str(r.get('code', '')), str(r.get('name', ''))), axis=1)
    return out


def _infer_sector(code: str, name: str) -> str:
    known = {
        '005930': '반도체',
        '000660': '반도체',
        '042700': '반도체장비/소재',
        '039030': '광통신/AI인프라',
        '094970': '광통신/AI인프라',
        '038460': '광통신/AI인프라',
        '267260': '전력기기/전선',
        '298040': '전력기기/전선',
        '034020': '원전/에너지',
        '010120': '전력기기/전선',
        '064350': '방산/철도',
        '352820': '엔터',
    }
    if code in known:
        return known[code]
    sector_rules = [
        ('광통신/AI인프라', ['광통신', '광모듈', 'CPO', '데이터센터', '이오테크닉스', '엘오티베큠', '인프라', '액침냉각']),
        ('전력반도체', ['전력반도체', 'IGBT', '실리콘카바이드', 'SIC', 'GAN']),
        ('전력기기/전선', ['일렉트릭', '전선', '전기', '효성중공업', '제룡', '산일전기', '대한전선', '가온전선', '대원전선', 'LS ELECTRIC', 'LS에코에너지']),
        ('반도체장비/소재', ['반도체', '하이닉스', 'HPSP', 'ISC', '리노공업', '테크윙', '원익', '솔브레인', 'DB하이텍', '주성엔지니어링', '피에스케이', '한미반도체', '동진쎄미켐']),
        ('AI/로봇/SW', ['로봇', 'AI', '소프트', '시스템', '네이버', '카카오', '더존', '폴라리스', '로보티즈', '레인보우', '두산로보틱스']),
        ('조선/해양', ['조선', '오션', '마린', '엔진', '한국카본', '동성화인텍', '세진중공업']),
        ('원전/에너지', ['두산에너빌리티', '원전', '한전', '전력', '에너지', '비에이치아이', '우진', '우리기술']),
        ('방산/우주', ['로템', '에어로', '항공', '스페이스', '풍산', 'LIG넥스원', '한화시스템', '쎄트렉아이', '인텔리안테크']),
        ('바이오/제약', ['바이오', '셀트리온', '제약', '헬스', '알테오젠', '리가켐', '삼천당', 'HLB', '유한양행', '한미약품', '에이비엘']),
        ('의료기기/미용', ['클래시스', '파마리서치', '제이시스', '비올', '휴젤', '메디톡스', '덴티움', '오스템']),
        ('화장품/소비', ['화장품', '아모레', '실리콘투', '브이티', '코스맥스', '한국콜마', '식품', '호텔', '유통', 'F&F']),
        ('자동차/부품', ['현대차', '기아', '모비스', '타이어', '만도', 'HL만도', '성우하이텍', '화신']),
        ('금융', ['금융', '은행', '증권', '보험', '카드', '지주']),
        ('건설/인프라', ['건설', '산업개발', '시멘트', '레미콘', '건자재']),
        ('철강/비철', ['철강', '스틸', '제강', '비철', '아연', '구리', '풍산', '고려아연']),
        ('화학/정유', ['화학', '케미칼', '정유', '석유', 'SK이노베이션', 'S-Oil', '롯데케미칼']),
        ('엔터/게임/미디어', ['하이브', '엔터', 'JYP', 'YG', 'SM', '게임', '넷마블', '크래프톤', '방송', '미디어', '스튜디오']),
        ('해운/항공/물류', ['해운', '항공', '대한항공', '아시아나', '팬오션', 'HMM', '물류', '통운']),
        ('통신', ['텔레콤', 'KT', 'LG유플러스', '통신']),
        ('OLED/디스플레이', ['디스플레이', 'OLED', '엘디스플레이', '덕산네오룩스', 'AP시스템']),
        ('PCB/전자부품', ['전자', '부품', 'PCB', '이수페타시스', '대덕전자', '비에이치', '심텍', '엠씨넥스']),
        ('친환경/풍력/태양광', ['풍력', '태양광', '씨에스윈드', 'SK오션플랜트', '한화솔루션', 'OCI']),
        ('2차전지/소재', ['에코프로', '포스코퓨처', '엘앤에프', '금양', '코스모', '천보', '대주전자', '나노신소재', '엔켐', '피엔티']),
    ]
    upper_name = name.upper()
    for sector, keywords in sector_rules:
        if any(k.upper() in upper_name for k in keywords):
            return sector
    return '기타'
