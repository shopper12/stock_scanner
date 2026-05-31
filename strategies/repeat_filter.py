from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings

ROOT_DIR = Path(__file__).resolve().parents[1]
HISTORY_REPORT_PATH = ROOT_DIR / 'reports' / 'recommendation_history.json'


def apply_repeat_penalty(df: pd.DataFrame) -> pd.DataFrame:
    """최근 추천 이력이 있는 종목을 감점해 같은 종목 반복 노출을 줄인다.

    완전 제외가 아니라 감점 방식이다. 정말 강한 종목은 남기되, 비슷한 점수면 새 후보를 위로 올린다.
    """
    if df.empty:
        return df
    lookback_days = _int_env('KR_REPEAT_LOOKBACK_DAYS', 7)
    penalty = _float_env('KR_REPEAT_SCORE_PENALTY', 8.0)
    top_n = _int_env('KR_TOP_N_RESULTS', 5)
    counts = _recent_recommendation_counts(lookback_days)
    if not counts:
        return df

    out = df.copy()
    repeat_counts = []
    adjusted_scores = []
    for _, row in out.iterrows():
        code = str(row.get('code', '')).zfill(6)
        repeat_count = int(counts.get(code, 0))
        raw_score = float(row.get('score') or 0.0)
        adjusted = max(0.0, raw_score - penalty * repeat_count)
        repeat_counts.append(repeat_count)
        adjusted_scores.append(round(adjusted, 1))

    out['raw_score'] = out['score']
    out['repeat_count_lookback'] = repeat_counts
    out['score'] = adjusted_scores
    out['repeat_penalty_note'] = [
        f'최근 {lookback_days}일 내 추천 {n}회 감점' if n else ''
        for n in repeat_counts
    ]
    sort_cols = [c for c in ['score', 'raw_score', 'trade_value_krw'] if c in out.columns]
    return out.sort_values(sort_cols, ascending=[False] * len(sort_cols)).head(top_n).reset_index(drop=True)


def _recent_recommendation_counts(lookback_days: int) -> dict[str, int]:
    history = _read_history()
    items = history.get('items', [])
    if not items:
        return {}
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    cutoff = today - timedelta(days=max(1, lookback_days))
    counts: dict[str, int] = {}
    for item in items:
        raw_date = str(item.get('scan_date') or '')[:10]
        try:
            scan_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except Exception:
            continue
        if scan_date < cutoff:
            continue
        code = str(item.get('code', '')).zfill(6)
        if code:
            counts[code] = counts.get(code, 0) + 1
    return counts


def _read_history() -> dict:
    if not HISTORY_REPORT_PATH.exists():
        return {'items': []}
    try:
        return json.loads(HISTORY_REPORT_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'items': []}


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
