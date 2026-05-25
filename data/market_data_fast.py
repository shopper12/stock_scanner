from __future__ import annotations

import pandas as pd
from config import settings
from data import mock_data
from data.market_data import _attach_names_and_sectors, _filter_common_stocks, _latest_kr_market_ohlcv, _ensure_sector, _fallback_or_raise


def get_kr_stock_universe_fast() -> pd.DataFrame:
    """KRX 전체 시장에서 섹터 점수 계산 없이 액티브 후보만 빠르게 반환한다.

    - sector 컬럼은 참고용으로 유지한다.
    - sector_rank / sector_strength_score / market_rotation_score는 점수에 쓰지 않는다.
    - 종목별 히스토리는 이 단계에서 다운로드하지 않는다.
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
        top_n = settings.kr_universe_top_n_bull if settings.bull_market_mode else settings.kr_universe_top_n
        top_n = max(20, min(int(top_n), 200))
        market_df['trade_date'] = trade_date
        market_df = market_df.sort_values(
            ['trade_value_today', 'change_pct_today', 'volume_today'],
            ascending=[False, False, False],
        ).head(top_n)
        return _ensure_fast_columns(market_df).reset_index(drop=True)
    except Exception as exc:
        return _fallback_or_raise(lambda: _ensure_fast_columns(_ensure_sector(mock_data.kr_stock_universe())).reset_index(drop=True), 'Fast KR stock universe fetch failed', exc)


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
