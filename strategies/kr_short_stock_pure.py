from __future__ import annotations

import os

import pandas as pd

from data.market_data_fast import get_kr_stock_universe_fast
from strategies import kr_short_stock as base
from strategies.metrics import score_clip


def scan_kr_short_stocks() -> pd.DataFrame:
    base.get_kr_stock_universe = get_kr_stock_universe_fast
    base._score = _score_pure
    base._select_diversified = _select_top_n
    return base.scan_kr_short_stocks()


def _top_n() -> int:
    try:
        return max(1, int(float(os.getenv('KR_TOP_N_RESULTS', '5'))))
    except ValueError:
        return 5


def _select_top_n(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    """섹터 분산 없이 순수 score 상위 N개 반환."""
    return ranked.head(_top_n()).reset_index(drop=True)


def _score_pure(price: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, high60: float, volume_ratio: float, value_ratio: float, trade_value: float, ret5: float, ret20: float, ret60: float, ret252: float, drawdown60: float, drawdown52w: float, gap_ma20: float, rsi14: float, setup: str, max_gap_ma20_pct: float, sector_strength: float, sector_rank: int, market_rotation: float, change_today: float) -> float:
    score = 50.0
    score += 12.0 if price > ma200 else -15.0
    score += 8.0 if price > ma60 else -5.0
    score += 7.0 if price > ma20 else -3.0
    score += 5.0 if ma20 > ma60 else -2.0
    score += 3.0 if ma60 > ma120 else -2.0
    score += score_clip(ret252 * 30.0, -12.0, 18.0)
    score += score_clip(ret20 * 65.0, -8.0, 14.0)
    score += score_clip(ret60 * 35.0, -8.0, 10.0)
    score += score_clip(ret5 * 38.0, -5.0, 5.0)
    if -0.18 <= drawdown60 <= -0.05 and price > ma60:
        score += 4.0
    if drawdown52w > -0.03 and setup != 'new_52w_high_breakout':
        score -= 5.0
    if -0.08 <= drawdown52w <= -0.03 and price > ma20:
        score += 6.0
    score += score_clip(drawdown52w * 30.0, -12.0, 0.0)
    if 50 <= rsi14 <= 68:
        score += 5.0
    elif rsi14 > 82:
        score -= 10.0
    elif rsi14 > 75:
        score -= 4.0
    elif rsi14 < 35:
        score -= 5.0
    score += score_clip((volume_ratio - 1.0) * 10.0, 0.0, 10.0)
    score += score_clip((value_ratio - 1.0) * 8.0, 0.0, 10.0)
    if change_today >= 3.0:
        score += 3.0
    elif change_today < -1.0:
        score -= 4.0
    if setup == 'new_52w_high_breakout':
        score += 9.0
    elif setup == 'breakout':
        score += score_clip((price / high20 - 0.98) * 260.0, 0.0, 7.0)
    elif setup == 'pullback_reversal':
        score += 5.0
    elif setup == 'trend_continuation':
        score += 3.0
    elif setup == 'first_pullback_after_high':
        score += 7.0
    if gap_ma20 > max_gap_ma20_pct / 100.0:
        score -= 12.0
    if ret5 < -0.06:
        score -= 8.0
    if drawdown60 < -0.25:
        score -= 10.0
    return score_clip(score, 0.0, 100.0)
