from __future__ import annotations

import os

import pandas as pd

from data.market_data_fast import get_kr_stock_universe_fast
from strategies import kr_short_stock as base

_ORIGINAL_SCAN = base.scan_kr_short_stocks
_ORIGINAL_RULES_LOADER = base.load_kr_short_rules


def scan_kr_short_stocks() -> pd.DataFrame:
    """Run KR short scanner with the fast KRX universe and pure top-N selection.

    The actual scoring logic lives in strategies.kr_short_stock._score.
    This wrapper must not override _score, otherwise score calibration/backtest fixes in
    the base strategy will not affect the app runtime path.
    """
    base.get_kr_stock_universe = get_kr_stock_universe_fast
    base.load_kr_short_rules = _load_runtime_rules
    base._select_diversified = _select_top_n
    return _ORIGINAL_SCAN()


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
    return ranked.head(_top_n()).reset_index(drop=True)
