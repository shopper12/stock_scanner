from __future__ import annotations

import os

import pandas as pd
from config import settings
from data import mock_data
from data.market_data import _attach_names_and_sectors, _filter_common_stocks, _latest_kr_market_ohlcv, _ensure_sector


def get_kr_stock_universe_fast() -> pd.DataFrame:
    """Return the full liquid KRX common-stock universe without sector scoring.

    This function intentionally does not select by sector. It returns all common
    KOSPI/KOSDAQ/KONEX rows that pass the basic price/trade-value gate, unless
    KR_FAST_UNIVERSE_TOP_N or KR_UNIVERSE_TOP_N is explicitly set to a positive
    number.

    If live KRX universe discovery fails, return a static core KR universe rather
    than raising. The later per-symbol OHLCV fetch still uses live pykrx/yfinance
    unless USE_MOCK_DATA=1, so this fallback avoids a full API 400 while keeping
    price data live where possible.
    """
    if settings.use_mock_data:
        return _fallback_fast_universe()
    try:
        market_df, trade_date = _latest_kr_market_ohlcv()
        market_df = _attach_names_and_sectors(market_df)
        market_df = _filter_common_stocks(market_df)
        market_df = market_df[
            (market_df['close_today'] >= settings.min_kr_price)
            & (market_df['trade_value_today'] >= settings.min_kr_trade_value_krw)
        ].copy()
        if market_df.empty:
            raise RuntimeError('no liquid KR stocks after fast filters')

        market_df['trade_date'] = trade_date
        market_df['fast_rank_score'] = _fast_rank_score(market_df)
        market_df = market_df.sort_values(
            ['fast_rank_score', 'change_pct_today', 'trade_value_today'],
            ascending=[False, False, False],
        )
        top_n = _fast_universe_top_n()
        if top_n is not None:
            market_df = market_df.head(top_n)
        return _ensure_fast_columns(market_df).reset_index(drop=True)
    except Exception as exc:
        print(f'[market_data_fast] fast KR stock universe fetch failed; using static core universe: {exc}')
        return _fallback_fast_universe()


def _fallback_fast_universe() -> pd.DataFrame:
    return _ensure_fast_columns(_ensure_sector(mock_data.kr_stock_universe())).reset_index(drop=True)


def _fast_universe_top_n() -> int | None:
    raw = os.getenv('KR_FAST_UNIVERSE_TOP_N') or os.getenv('KR_UNIVERSE_TOP_N')
    if raw is None or str(raw).strip() == '':
        return None
    try:
        value = int(float(raw))
    except ValueError:
        return None
    if value <= 0:
        return None
    return max(80, min(value, 3000))


def _fast_rank_score(df: pd.DataFrame) -> pd.Series:
    trade_rank = pd.to_numeric(df['trade_value_today'], errors='coerce').fillna(0).rank(pct=True)
    volume_rank = pd.to_numeric(df['volume_today'], errors='coerce').fillna(0).rank(pct=True)
    change = pd.to_numeric(df['change_pct_today'], errors='coerce').fillna(0)
    positive_change_rank = change.clip(lower=0).rank(pct=True)
    negative_penalty = change.lt(0).astype(float) * 15.0
    return (trade_rank * 35.0 + positive_change_rank * 45.0 + volume_rank * 20.0 - negative_penalty).clip(0, 100)


def _ensure_fast_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        'market': 'STATIC',
        'trade_date': 'fallback_static_core',
        'close_today': 0.0,
        'volume_today': 0.0,
        'trade_value_today': 0.0,
        'change_pct_today': 0.0,
        'sector_rank': 99,
        'sector_strength_score': 0.0,
        'market_rotation_score': 0.0,
    }
    for col, value in defaults.items():
        if col not in out.columns:
            out[col] = value
    out['code'] = out['code'].astype(str).str.zfill(6)
    out['sector_rank'] = 99
    out['sector_strength_score'] = 0.0
    out['market_rotation_score'] = 0.0
    return out[[
        'code', 'name', 'sector', 'market', 'trade_date', 'close_today', 'volume_today',
        'trade_value_today', 'change_pct_today', 'sector_rank', 'sector_strength_score',
        'market_rotation_score',
    ]]
