from __future__ import annotations

import pandas as pd

from config import settings
from data.market_data import get_kr_stock_history
from strategies.ict_analysis import analyze_ict_structure
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
    out = _neutralize_sector_scores(out)
    out = _apply_ict_confirmation(out)
    out = out.sort_values(['score', 'trade_value_krw'], ascending=[False, False]).reset_index(drop=True)
    print(f'[guarded_scan] before={before} after={len(out)} sector_score_used=false ict_used=true')
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


def _neutralize_sector_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['sector_rank'] = 99
    out['sector_strength_score'] = 0.0
    return out


def _apply_ict_confirmation(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    defaults = {
        'ict_bias': 'UNKNOWN',
        'ict_structure': 'INSUFFICIENT_DATA',
        'ict_structure_event': 'NONE',
        'ict_liquidity_event': 'NONE',
        'ict_fair_value_gap': 'NONE',
        'ict_dealing_range_location': 'UNKNOWN',
        'ict_preferred_entry_low': None,
        'ict_preferred_entry_high': None,
        'ict_invalidation': None,
        'ict_score_adjustment': 0.0,
        'ict_summary': '',
    }
    for column, value in defaults.items():
        if column not in out.columns:
            out[column] = value

    for index, row in out.iterrows():
        code = str(row.get('code', '')).zfill(6)
        if not code or code == '000000':
            continue
        try:
            history = get_kr_stock_history(code)
            current_price = float(row.get('current_price') or row.get('entry') or 0.0)
            ict = analyze_ict_structure(history, current_price=current_price if current_price > 0 else None)
            for key, value in ict.items():
                target = {
                    'bias': 'ict_bias',
                    'structure': 'ict_structure',
                    'structure_event': 'ict_structure_event',
                    'liquidity_event': 'ict_liquidity_event',
                    'fair_value_gap': 'ict_fair_value_gap',
                    'dealing_range_location': 'ict_dealing_range_location',
                    'preferred_entry_low': 'ict_preferred_entry_low',
                    'preferred_entry_high': 'ict_preferred_entry_high',
                    'invalidation': 'ict_invalidation',
                    'score_adjustment': 'ict_score_adjustment',
                    'summary': 'ict_summary',
                }.get(key)
                if target:
                    out.at[index, target] = value
            adjustment = float(ict.get('score_adjustment') or 0.0)
            score = float(row.get('score') or 0.0)
            out.at[index, 'score'] = max(0.0, min(100.0, score + adjustment))
            summary = str(ict.get('summary') or '')
            if summary:
                out.at[index, 'reason'] = f"{str(row.get('reason') or '')} + {summary}"
            if ict.get('bias') == 'BEARISH':
                out.at[index, 'failure_condition'] = f"{str(row.get('failure_condition') or '')} + ICT 약세 구조 지속 시 진입 보류"
        except Exception as exc:
            out.at[index, 'ict_summary'] = f'ICT_FAILED: {exc.__class__.__name__}'
            print(f'[guarded_scan] ict failed code={code}: {exc}')
    return out
