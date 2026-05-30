from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from config import settings
from data.market_data_fast import get_kr_stock_universe_fast
from strategies import kr_short_stock as base
from strategies.metrics import score_clip

_ORIGINAL_SCAN = base.scan_kr_short_stocks
_ORIGINAL_RULES_LOADER = base.load_kr_short_rules
ROOT_DIR = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT_DIR / 'reports' / 'recommendation_history.json'


def scan_kr_short_stocks() -> pd.DataFrame:
    base.get_kr_stock_universe = get_kr_stock_universe_fast
    base.load_kr_short_rules = _load_pure_rules
    base._score = _score_pure
    base._select_diversified = _select_top_n
    return _ORIGINAL_SCAN()


def _load_pure_rules():
    rules = _ORIGINAL_RULES_LOADER()
    threshold = _pure_score_threshold()
    try:
        return rules.__class__(**{**rules.__dict__, 'score_threshold': threshold})
    except Exception:
        return rules


def _pure_score_threshold() -> float:
    raw = os.getenv('KR_PURE_SCORE_THRESHOLD', '55')
    try:
        return float(raw)
    except ValueError:
        return 55.0


def _top_n() -> int:
    try:
        return max(1, int(float(os.getenv('KR_TOP_N_RESULTS', '5'))))
    except ValueError:
        return 5


def _repeat_exclude_days() -> int:
    try:
        return max(0, int(float(os.getenv('KR_REPEAT_EXCLUDE_DAYS', '5'))))
    except ValueError:
        return 5


def _repeat_penalty() -> float:
    try:
        return max(0.0, float(os.getenv('KR_REPEAT_SCORE_PENALTY', '8')))
    except ValueError:
        return 8.0


def _select_top_n(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    if ranked.empty:
        return ranked.head(0).reset_index(drop=True)
    top_n = _top_n()
    scored = _apply_recent_repeat_penalty(ranked.copy())
    fresh = scored[~scored['recent_repeat']].copy()
    if len(fresh) >= top_n:
        return fresh.sort_values(['adjusted_score', 'score', 'trade_value_krw'], ascending=[False, False, False]).head(top_n).drop(columns=['adjusted_score', 'recent_repeat'], errors='ignore').reset_index(drop=True)
    fallback = scored.sort_values(['adjusted_score', 'score', 'trade_value_krw'], ascending=[False, False, False]).head(top_n)
    return fallback.drop(columns=['adjusted_score', 'recent_repeat'], errors='ignore').reset_index(drop=True)


def _apply_recent_repeat_penalty(df: pd.DataFrame) -> pd.DataFrame:
    recent_codes = _recent_recommended_codes(_repeat_exclude_days())
    if not recent_codes:
        df['recent_repeat'] = False
        df['adjusted_score'] = pd.to_numeric(df.get('score', 0), errors='coerce').fillna(0.0)
        return df
    codes = df['code'].astype(str).str.zfill(6)
    df['recent_repeat'] = codes.isin(recent_codes)
    base_score = pd.to_numeric(df.get('score', 0), errors='coerce').fillna(0.0)
    df['adjusted_score'] = base_score - df['recent_repeat'].astype(float) * _repeat_penalty()
    df['reason'] = df.apply(_append_repeat_note, axis=1)
    return df


def _append_repeat_note(row: pd.Series) -> str:
    reason = str(row.get('reason') or '')
    if bool(row.get('recent_repeat')):
        return f'{reason} / 최근추천반복: 감점 적용'
    return reason


def _recent_recommended_codes(days: int) -> set[str]:
    if days <= 0 or not HISTORY_PATH.exists():
        return set()
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))
        cutoff = datetime.now() - timedelta(days=days)
        out: set[str] = set()
        for item in data.get('items', []):
            raw_date = str(item.get('scan_date') or '').strip()
            if not raw_date:
                continue
            try:
                scan_date = datetime.fromisoformat(raw_date[:10])
            except ValueError:
                continue
            if scan_date >= cutoff:
                code = str(item.get('code') or '').zfill(6)
                if code and code != '000000':
                    out.add(code)
        return out
    except Exception:
        return set()


def _score_pure(price: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, high60: float, volume_ratio: float, value_ratio: float, trade_value: float, ret5: float, ret20: float, ret60: float, ret252: float, drawdown60: float, drawdown52w: float, gap_ma20: float, rsi14: float, setup: str, max_gap_ma20_pct: float, sector_strength: float, sector_rank: int, market_rotation: float, change_today: float) -> float:
    if setup == 'watch':
        return 0.0

    score = 50.0
    score += 12.0 if price > ma200 else -12.0
    score += 8.0 if price > ma60 else -4.0
    score += 7.0 if price > ma20 else -2.0
    score += 5.0 if ma20 > ma60 else -2.0
    score += 3.0 if ma60 > ma120 else -2.0
    score += score_clip(ret252 * 28.0, -10.0, 16.0)
    score += score_clip(ret20 * 70.0, -8.0, 16.0)
    score += score_clip(ret60 * 40.0, -8.0, 12.0)
    score += score_clip(ret5 * 42.0, -5.0, 6.0)
    if -0.18 <= drawdown60 <= -0.05 and price > ma60:
        score += 4.0
    if drawdown52w > -0.03 and setup != 'new_52w_high_breakout':
        score -= 4.0
    if -0.10 <= drawdown52w <= -0.025 and price > ma20:
        score += 6.0
    score += score_clip(drawdown52w * 25.0, -10.0, 0.0)
    if 48 <= rsi14 <= 72:
        score += 5.0
    elif rsi14 > 84:
        score -= 9.0
    elif rsi14 > 78:
        score -= 3.0
    elif rsi14 < 35:
        score -= 5.0
    score += score_clip((trade_value / settings.min_kr_trade_value_krw) * 10.0, 0.0, 14.0)
    score += score_clip((volume_ratio - 1.0) * 12.0, 0.0, 12.0)
    score += score_clip((value_ratio - 1.0) * 10.0, 0.0, 12.0)
    if change_today >= 5.0:
        score += 5.0
    elif change_today >= 2.0:
        score += 3.0
    elif change_today < -2.0:
        score -= 5.0
    elif change_today < -1.0:
        score -= 3.0
    if setup == 'new_52w_high_breakout':
        score += 10.0
    elif setup == 'breakout':
        score += score_clip((price / high20 - 0.98) * 280.0, 0.0, 8.0)
    elif setup == 'pullback_reversal':
        score += 6.0
    elif setup == 'trend_continuation':
        score += 4.0
    elif setup == 'first_pullback_after_high':
        score += 8.0
    if gap_ma20 > max_gap_ma20_pct / 100.0:
        score -= 10.0
    if ret5 < -0.06:
        score -= 8.0
    if drawdown60 < -0.25:
        score -= 10.0
    return score_clip(score, 0.0, 100.0)
