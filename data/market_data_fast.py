from __future__ import annotations

import os

import pandas as pd
from config import settings
from data import mock_data
from data.market_data import _attach_names_and_sectors, _filter_common_stocks, _latest_kr_market_ohlcv, _ensure_sector


def get_kr_stock_universe_fast() -> pd.DataFrame:
    """Return the full liquid KRX common-stock universe with lightweight sector scoring.

    This function intentionally does not select by sector. It returns all common
    KOSPI/KOSDAQ/KONEX rows that pass the basic price/trade-value gate, unless
    KR_FAST_UNIVERSE_TOP_N or KR_UNIVERSE_TOP_N is explicitly set to a positive
    number. If KRX market-wide OHLCV is blocked on Render, it falls back to a
    static core universe enriched with Naver realtime quote fields so the scan can
    still produce candidates instead of an empty latest report.
    """
    if settings.use_mock_data:
        return _ensure_fast_columns(_apply_sector_scores(_ensure_sector(mock_data.kr_stock_universe()))).reset_index(drop=True)
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
        market_df = _apply_sector_scores(market_df)
        market_df = market_df.sort_values(
            ['fast_rank_score', 'sector_strength_score', 'change_pct_today', 'trade_value_today'],
            ascending=[False, False, False, False],
        )
        top_n = _fast_universe_top_n()
        if top_n is not None:
            market_df = market_df.head(top_n)
        return _ensure_fast_columns(market_df).reset_index(drop=True)
    except Exception as exc:
        print(f'[market_data_fast] KRX market universe failed; using realtime static fallback: {exc}')
        return _static_realtime_universe(str(exc))


def _static_realtime_universe(error_message: str) -> pd.DataFrame:
    base = _ensure_sector(mock_data.kr_stock_universe()).copy()
    rows = []
    for row in base.to_dict('records'):
        code = str(row.get('code', '')).zfill(6)
        close_today = 0.0
        volume_today = 0.0
        trade_value_today = 0.0
        change_pct_today = 0.0
        try:
            from data.realtime_price import try_kr_realtime_quote
            quote = try_kr_realtime_quote(code)
            if quote.get('ok'):
                close_today = float(quote.get('price') or 0.0)
                volume_today = float(quote.get('volume') or 0.0)
                trade_value_today = float(quote.get('trade_value') or 0.0)
                change_pct_today = float(quote.get('change_pct') or 0.0)
        except Exception as quote_exc:
            print(f'[market_data_fast] quote fallback failed for {code}: {quote_exc}')
        rows.append({
            'code': code,
            'name': row.get('name', ''),
            'sector': row.get('sector', '기타'),
            'market': 'STATIC_NAVER_FALLBACK',
            'trade_date': f'krx_universe_failed: {error_message[:80]}',
            'close_today': close_today,
            'volume_today': volume_today,
            'trade_value_today': trade_value_today,
            'change_pct_today': change_pct_today,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return _ensure_fast_columns(base).reset_index(drop=True)
    out['fast_rank_score'] = _fast_rank_score(out)
    out = _apply_sector_scores(out)
    out = out.sort_values(['fast_rank_score', 'sector_strength_score', 'trade_value_today', 'change_pct_today'], ascending=[False, False, False, False])
    return _ensure_fast_columns(out).reset_index(drop=True)


def _apply_sector_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = _ensure_sector(df.copy())
    if out.empty:
        return out
    trade_value = pd.to_numeric(out.get('trade_value_today'), errors='coerce').fillna(0.0)
    change = pd.to_numeric(out.get('change_pct_today'), errors='coerce').fillna(0.0)
    fast_score = pd.to_numeric(out.get('fast_rank_score'), errors='coerce').fillna(0.0)
    out['_tv'] = trade_value
    out['_change'] = change
    out['_fast'] = fast_score
    sector = out.groupby('sector').agg(
        trade_value_sum=('_tv', 'sum'),
        avg_change=('_change', 'mean'),
        positive_rate=('_change', lambda s: float((s > 0).mean()) if len(s) else 0.0),
        avg_fast=('_fast', 'mean'),
        count=('code', 'count'),
    ).reset_index()
    if sector.empty:
        out['sector_rank'] = 99
        out['sector_strength_score'] = 0.0
        out['market_rotation_score'] = _fallback_rotation_score(change, trade_value)
        return out.drop(columns=['_tv', '_change', '_fast'], errors='ignore')
    tv_rank = pd.to_numeric(sector['trade_value_sum'], errors='coerce').fillna(0.0).rank(pct=True)
    ch_rank = pd.to_numeric(sector['avg_change'], errors='coerce').fillna(0.0).clip(lower=0).rank(pct=True)
    fast_rank = pd.to_numeric(sector['avg_fast'], errors='coerce').fillna(0.0).rank(pct=True)
    pos = pd.to_numeric(sector['positive_rate'], errors='coerce').fillna(0.0)
    sector['sector_strength_score'] = (tv_rank * 35.0 + ch_rank * 35.0 + fast_rank * 20.0 + pos * 10.0).clip(0, 100)
    sector['sector_rank'] = sector['sector_strength_score'].rank(method='dense', ascending=False).astype(int)
    out = out.merge(sector[['sector', 'sector_rank', 'sector_strength_score']], on='sector', how='left')
    out['sector_rank'] = pd.to_numeric(out['sector_rank'], errors='coerce').fillna(99).astype(int)
    out['sector_strength_score'] = pd.to_numeric(out['sector_strength_score'], errors='coerce').fillna(0.0)
    out['market_rotation_score'] = _fallback_rotation_score(change, trade_value)
    return out.drop(columns=['_tv', '_change', '_fast'], errors='ignore')


def _fallback_rotation_score(change_pct_today, trade_value_today):
    change = pd.to_numeric(change_pct_today, errors='coerce').fillna(0.0) if hasattr(change_pct_today, '__len__') and not isinstance(change_pct_today, (str, bytes)) else float(change_pct_today or 0.0)
    trade_value = pd.to_numeric(trade_value_today, errors='coerce').fillna(0.0) if hasattr(trade_value_today, '__len__') and not isinstance(trade_value_today, (str, bytes)) else float(trade_value_today or 0.0)
    score = change.clip(-5.0, 8.0) * 4.0 if hasattr(change, 'clip') else max(min(change, 8.0), -5.0) * 4.0
    tv_score = (trade_value / max(settings.min_kr_trade_value_krw, 1.0) * 20.0).clip(0.0, 40.0) if hasattr(trade_value, 'clip') else min(trade_value / max(settings.min_kr_trade_value_krw, 1.0) * 20.0, 40.0)
    return (score + tv_score).clip(0.0, 100.0) if hasattr(score, 'clip') else max(0.0, min(100.0, score + tv_score))


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
        'market': 'UNKNOWN',
        'trade_date': 'unknown',
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
    out['sector_rank'] = pd.to_numeric(out['sector_rank'], errors='coerce').fillna(99).astype(int)
    out['sector_strength_score'] = pd.to_numeric(out['sector_strength_score'], errors='coerce').fillna(0.0)
    out['market_rotation_score'] = pd.to_numeric(out['market_rotation_score'], errors='coerce').fillna(0.0)
    return out[[
        'code', 'name', 'sector', 'market', 'trade_date', 'close_today', 'volume_today',
        'trade_value_today', 'change_pct_today', 'sector_rank', 'sector_strength_score',
        'market_rotation_score',
    ]]
