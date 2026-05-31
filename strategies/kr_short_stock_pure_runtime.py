from __future__ import annotations

import os

import pandas as pd

from config import settings
from data.market_data_fast import get_kr_stock_universe_fast
from strategies import kr_short_stock as base

MIN_TRADE_VALUE_KRW = 5_000_000_000

_ORIGINAL_SCAN = base.scan_kr_short_stocks
_ORIGINAL_RULES_LOADER = base.load_kr_short_rules
_ORIGINAL_SETUP = base._setup
_ORIGINAL_SCORE = base._score


def scan_kr_short_stocks() -> pd.DataFrame:
    """Run KR short scanner across the full liquid KRX universe.

    Runtime path deliberately removes sector-based recommendation logic:
    - no sector diversification picker
    - no sector_rank / sector_strength / market_rotation score bonus
    - selection is based on stock-level price, trend, volume, liquidity and risk only
    """
    base.get_kr_stock_universe = get_kr_stock_universe_fast
    base.load_kr_short_rules = _load_runtime_rules
    base._select_diversified = _select_top_n
    base._setup = _runtime_setup
    base._score = _runtime_score
    scanned = _ORIGINAL_SCAN()
    return _drop_untradable_rows(scanned)


def _runtime_setup(price: float, prev_close: float, prev_ma20: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, high60: float, drawdown60: float, drawdown52w: float, high252: float | None = None, ret5: float = 0.0, ret20: float = 0.0, volume_ratio: float = 0.0, value_ratio: float = 0.0, trade_value: float = 0.0, sector_rank: int = 99, market_rotation: float = 0.0, change_today: float = 0.0) -> str:
    setup = _ORIGINAL_SETUP(price, prev_close, prev_ma20, ma20, ma60, ma120, ma200, high20, high60, drawdown60, drawdown52w, high252, ret5, ret20, volume_ratio, value_ratio, trade_value, 99, 0.0, change_today)
    if setup != 'watch':
        return setup
    early_repricing = (
        price > ma20
        and price > ma60
        and change_today >= 4.0
        and ret5 >= 0.02
        and (volume_ratio >= 1.15 or value_ratio >= 1.15)
        and trade_value >= settings.min_kr_trade_value_krw * 8.0
        and (price / ma20 - 1.0) <= 0.26
        and (trade_value >= settings.min_kr_trade_value_krw * 15.0 or value_ratio >= 1.8 or volume_ratio >= 1.8)
    )
    if early_repricing:
        return 'theme_repricing_breakout'
    return setup


def _runtime_score(price: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, high60: float, volume_ratio: float, value_ratio: float, trade_value: float, ret5: float, ret20: float, ret60: float, ret252: float, drawdown60: float, drawdown52w: float, gap_ma20: float, rsi14: float, setup: str, max_gap_ma20_pct: float, sector_strength: float, sector_rank: int, market_rotation: float, change_today: float) -> float:
    score = _ORIGINAL_SCORE(price, ma20, ma60, ma120, ma200, high20, high60, volume_ratio, value_ratio, trade_value, ret5, ret20, ret60, ret252, drawdown60, drawdown52w, gap_ma20, rsi14, setup, max_gap_ma20_pct, 0.0, 99, 0.0, change_today)
    if trade_value < MIN_TRADE_VALUE_KRW:
        score -= 60.0
    elif trade_value > 0:
        score += min((trade_value / 50_000_000_000) * 3.0, 3.0)
    if value_ratio <= 0:
        score -= 50.0
    if setup == 'watch' and volume_ratio < 0.80:
        score -= 20.0
    if setup == 'watch' and value_ratio < 0.80 and volume_ratio < 0.80:
        score -= 30.0
    if setup == 'theme_repricing_breakout' and change_today >= 4.0 and ret20 < 0.075:
        score += 5.0
    if setup == 'theme_repricing_breakout' and trade_value >= settings.min_kr_trade_value_krw * 15.0:
        score += 3.0
    return max(0.0, min(score, 100.0))


def _drop_untradable_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    trade_value = pd.to_numeric(out.get('trade_value_krw'), errors='coerce').fillna(0.0)
    volume = pd.to_numeric(out.get('volume_ratio_20d'), errors='coerce').fillna(0.0)
    value = pd.to_numeric(out.get('trade_value_ratio_20d'), errors='coerce').fillna(0.0)
    setup = out.get('strategy_type', pd.Series([''] * len(out))).astype(str)
    liquid = trade_value >= MIN_TRADE_VALUE_KRW
    valid_value_ratio = value > 0.0
    low_volume_watch = (setup == 'watch') & (volume < 0.80)
    low_value_and_volume_watch = (setup == 'watch') & (value < 0.80) & (volume < 0.80)
    out = out.loc[liquid & valid_value_ratio & ~(low_volume_watch | low_value_and_volume_watch)].copy()
    if out.empty:
        return out.reset_index(drop=True)
    out['sector_rank'] = 99
    out['sector_strength_score'] = 0.0
    out['market_rotation_score'] = 0.0
    return out.sort_values(['score', 'trade_value_krw', 'change_pct_today'], ascending=[False, False, False]).reset_index(drop=True).head(_top_n())


def _load_runtime_rules():
    rules = _ORIGINAL_RULES_LOADER()
    threshold = _runtime_score_threshold(rules)
    try:
        return rules.__class__(**{**rules.__dict__, 'score_threshold': threshold})
    except Exception:
        return rules


def _runtime_score_threshold(rules) -> float:
    raw = os.getenv('KR_PURE_SCORE_THRESHOLD') or os.getenv('KR_SCORE_THRESHOLD')
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    return float(getattr(rules, 'score_threshold', 55.0) or 55.0)


def _top_n() -> int:
    try:
        return max(1, int(float(os.getenv('KR_TOP_N_RESULTS', '5'))))
    except ValueError:
        return 5


def _select_top_n(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    return ranked.head(max(max_items, _top_n())).reset_index(drop=True)
