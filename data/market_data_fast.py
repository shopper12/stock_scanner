from __future__ import annotations

import os

import pandas as pd
from config import settings
from data import mock_data
from data.market_data import _attach_names_and_sectors, _filter_common_stocks, _latest_kr_market_ohlcv, _ensure_sector, _fallback_or_raise


def get_kr_stock_universe_fast() -> pd.DataFrame:
    """KRX 전체 시장에서 섹터 점수 계산 없이 액티브 후보를 빠르게 반환한다.

    - sector 컬럼은 참고용으로 유지한다.
    - sector_rank / sector_strength_score / market_rotation_score는 점수에 쓰지 않는다.
    - 종목별 히스토리는 이 단계에서 다운로드하지 않는다.
    - 거래대금 상위만 뽑지 않고 당일 등락률+거래대금+거래량을 혼합해 대형주 편향을 줄인다.
    """
    if settings.use_mock_data:
        return _ensure_fast_columns(_ensure_sector(mock_data.kr_stock_universe())).reset_index(drop=True)
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
        top_n = _fast_universe_top_n()
        market_df = market_df.sort_values(
            ['fast_rank_score', 'change_pct_today', 'trade_value_today'],
            ascending=[False, False, False],
        ).head(top_n)
        return _ensure_fast_columns(market_df).reset_index(drop=True)
    except Exception as exc:
        return _fallback_or_raise(lambda: _ensure_fast_columns(_ensure_sector(mock_data.kr_stock_universe())).reset_index(drop=True), 'Fast KR stock universe fetch failed', exc)


def _fast_universe_top_n() -> int:
    raw = os.getenv('KR_FAST_UNIVERSE_TOP_N') or os.getenv('KR_UNIVERSE_TOP_N')
    if raw is None:
        raw = '200'
    try:
        value = int(float(raw))
    except ValueError:
        value = 200
    return max(80, min(value, 300))


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
        'market': 'UNKNOWN',
        'trade_date': 'unknown',
        'close_today': 0.0,
        'volume_today': 0.0,
        'trade_value_today': 0.0,
        'change_pct_today': 0.0,
        'sector_rank': 0,
        'sector_strength_score': 0.0,
        'market_rotation_score': 0.0,
    }
    for col, value in defaults.items():
        if col not in out.columns:
            out[col] = value
    return out[[
        'code', 'name', 'sector', 'market', 'trade_date', 'close_today', 'volume_today',
        'trade_value_today', 'change_pct_today', 'sector_rank', 'sector_strength_score',
        'market_rotation_score',
    ]]
