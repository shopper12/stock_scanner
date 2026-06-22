from __future__ import annotations

import pandas as pd

from config import settings
from strategies.kr_short_rules import load_kr_short_rules
from strategies.kr_short_stock_pure_runtime import scan_kr_short_stocks as _runtime_scan

MAX_TRADE_VALUE_KRW = 50_000_000_000_000
MAX_TRADE_VALUE_RATIO = 50.0
MIN_5D_MOMENTUM_PCT = -15.0


def scan_kr_short_stocks() -> pd.DataFrame:
    df = _runtime_scan()
    if df.empty:
        return df
    out = df.copy()
    before = len(out)
    out = _drop_bad_market_data(out)
    out = _penalize_risk_overflow(out)
    out = _fix_zero_position_size(out)
    out = _restore_sector_scores(out)
    out = out.sort_values(['score', 'sector_strength_score', 'trade_value_krw'], ascending=[False, False, False]).reset_index(drop=True)
    print(f'[guarded_scan] before={before} after={len(out)}')
    return out


def _drop_bad_market_data(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    trade_value = pd.to_numeric(out.get('trade_value_krw'), errors='coerce').fillna(0.0)
    value_ratio = pd.to_numeric(out.get('trade_value_ratio_20d'), errors='coerce').fillna(0.0)
    momentum5 = pd.to_numeric(out.get('momentum_5d_pct'), errors='coerce').fillna(0.0)
    bad_trade_value = trade_value > MAX_TRADE_VALUE_KRW
    bad_value_ratio = value_ratio > MAX_TRADE_VALUE_RATIO
    severe_drop = momentum5 < MIN_5D_MOMENTUM_PCT
    if bad_trade_value.any() or bad_value_ratio.any() or severe_drop.any():
        print('[guarded_scan] drop_bad_market_data=', out.loc[bad_trade_value | bad_value_ratio | severe_drop, ['code', 'name', 'trade_value_krw', 'trade_value_ratio_20d', 'momentum_5d_pct']].to_dict('records'))
    return out.loc[~(bad_trade_value | bad_value_ratio | severe_drop)].copy()


def _penalize_risk_overflow(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rules = load_kr_short_rules()
    max_risk = float(getattr(rules, 'max_risk_pct', 12.0) or 12.0)
    risk = pd.to_numeric(out.get('risk_pct'), errors='coerce').fillna(0.0)
    risk_over = risk > max_risk * 1.1
    if risk_over.any():
        out.loc[risk_over, 'score'] = (pd.to_numeric(out.loc[risk_over, 'score'], errors='coerce').fillna(0.0) - 40.0).clip(lower=0.0)
        out.loc[risk_over, 'reason'] = out.loc[risk_over, 'reason'].astype(str) + f' + risk {max_risk:.1f}% 초과 패널티'
        print('[guarded_scan] penalize_risk_overflow=', out.loc[risk_over, ['code', 'name', 'risk_pct', 'score']].to_dict('records'))
    return out


def _fix_zero_position_size(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'position_size_krw' not in out.columns:
        out['position_size_krw'] = 0
    position = pd.to_numeric(out['position_size_krw'], errors='coerce').fillna(0.0)
    zero_position = position <= 0
    if zero_position.any():
        fallback_position = round(max(float(getattr(settings, 'account_equity_krw', 0.0) or 0.0) * 0.30, 0.0))
        out.loc[zero_position, 'position_size_krw'] = fallback_position
        out.loc[zero_position, 'reason'] = out.loc[zero_position, 'reason'].astype(str) + ' + position_size 0 보정'
        print('[guarded_scan] fix_zero_position_size=', out.loc[zero_position, ['code', 'name', 'position_size_krw']].to_dict('records'))
    return out


def _restore_sector_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    trade_value = pd.to_numeric(out.get('trade_value_krw'), errors='coerce').fillna(0.0)
    change = pd.to_numeric(out.get('change_pct_today'), errors='coerce').fillna(0.0)
    score = pd.to_numeric(out.get('score'), errors='coerce').fillna(0.0)
    out['_tv'] = trade_value
    out['_change'] = change
    out['_score'] = score
    sector = out.groupby('sector').agg(
        trade_value_sum=('_tv', 'sum'),
        avg_change=('_change', 'mean'),
        avg_score=('_score', 'mean'),
        count=('code', 'count'),
    ).reset_index()
    if sector.empty:
        out['sector_rank'] = 99
        out['sector_strength_score'] = 0.0
        return out.drop(columns=['_tv', '_change', '_score'], errors='ignore')
    tv_rank = pd.to_numeric(sector['trade_value_sum'], errors='coerce').fillna(0.0).rank(pct=True)
    ch_rank = pd.to_numeric(sector['avg_change'], errors='coerce').fillna(0.0).clip(lower=0).rank(pct=True)
    score_rank = pd.to_numeric(sector['avg_score'], errors='coerce').fillna(0.0).rank(pct=True)
    sector['sector_strength_score'] = (tv_rank * 35.0 + ch_rank * 30.0 + score_rank * 35.0).clip(0, 100)
    sector['sector_rank'] = sector['sector_strength_score'].rank(method='dense', ascending=False).astype(int)
    out = out.drop(columns=['sector_rank', 'sector_strength_score'], errors='ignore').merge(sector[['sector', 'sector_rank', 'sector_strength_score']], on='sector', how='left')
    out['sector_rank'] = pd.to_numeric(out['sector_rank'], errors='coerce').fillna(99).astype(int)
    out['sector_strength_score'] = pd.to_numeric(out['sector_strength_score'], errors='coerce').fillna(0.0).round(1)
    return out.drop(columns=['_tv', '_change', '_score'], errors='ignore')
