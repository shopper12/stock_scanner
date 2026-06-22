from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from config import settings
from data.market_data_fast import get_kr_stock_universe_fast
from strategies import kr_short_stock as base

MIN_TRADE_VALUE_KRW = 5_000_000_000
RELAXED_MIN_TRADE_VALUE_KRW = 500_000_000
MAX_REASONABLE_TRADE_VALUE_KRW = 50_000_000_000_000
MAX_REASONABLE_VALUE_RATIO = 50.0
THEME_MAX_RISK_PCT = 16.0
REPORT_DIR = Path(__file__).resolve().parents[1] / 'reports'
HISTORY_PATH = REPORT_DIR / 'recommendation_history.json'
LATEST_PATH = REPORT_DIR / 'latest.json'

_ORIGINAL_SCAN = base.scan_kr_short_stocks
_ORIGINAL_RULES_LOADER = base.load_kr_short_rules
_ORIGINAL_SETUP = base._setup
_ORIGINAL_SCORE = base._score


def scan_kr_short_stocks() -> pd.DataFrame:
    """Run KR short scanner without sector-based selection."""
    base.get_kr_stock_universe = get_kr_stock_universe_fast
    base.load_kr_short_rules = _load_runtime_rules
    base._select_diversified = _select_pre_filter_buffer
    base._setup = _runtime_setup
    base._score = _runtime_score
    original_bull_market_mode = settings.bull_market_mode
    try:
        object.__setattr__(settings, 'bull_market_mode', False)
        scanned = _ORIGINAL_SCAN()
    finally:
        object.__setattr__(settings, 'bull_market_mode', original_bull_market_mode)
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
    if value_ratio > MAX_REASONABLE_VALUE_RATIO:
        score -= 40.0
    if ret5 < -0.15:
        score -= 25.0
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
        print('[runtime_filter] input_empty=true')
        return df
    out = df.copy()
    trade_value = pd.to_numeric(out.get('trade_value_krw'), errors='coerce').fillna(0.0)
    volume = pd.to_numeric(out.get('volume_ratio_20d'), errors='coerce').fillna(0.0)
    value = pd.to_numeric(out.get('trade_value_ratio_20d'), errors='coerce').fillna(0.0)
    risk = pd.to_numeric(out.get('risk_pct'), errors='coerce').fillna(0.0)
    drawdown52w = pd.to_numeric(out.get('drawdown_52w_pct'), errors='coerce').fillna(0.0)
    ret5_pct = pd.to_numeric(out.get('momentum_5d_pct'), errors='coerce').fillna(0.0)
    setup = out.get('strategy_type', pd.Series([''] * len(out))).astype(str)
    rules = _ORIGINAL_RULES_LOADER()
    original_max_risk = float(getattr(rules, 'max_risk_pct', 12.0) or 12.0)

    abnormal_trade_value = (trade_value > MAX_REASONABLE_TRADE_VALUE_KRW) | (value > MAX_REASONABLE_VALUE_RATIO)
    severe_5d_downtrend = ret5_pct < -15.0
    risk_excess_penalty = risk > (original_max_risk * 1.1)
    if abnormal_trade_value.any():
        out.loc[abnormal_trade_value, 'reason'] = out.loc[abnormal_trade_value, 'reason'].astype(str) + ' + 거래대금 이상값 제외'
    if severe_5d_downtrend.any():
        out.loc[severe_5d_downtrend, 'strategy_type'] = 'watch'
        out.loc[severe_5d_downtrend, 'score'] = pd.to_numeric(out.loc[severe_5d_downtrend, 'score'], errors='coerce').fillna(0.0) - 25.0
        setup = out.get('strategy_type', pd.Series([''] * len(out))).astype(str)
    if risk_excess_penalty.any():
        out.loc[risk_excess_penalty, 'score'] = pd.to_numeric(out.loc[risk_excess_penalty, 'score'], errors='coerce').fillna(0.0) - 40.0
        out.loc[risk_excess_penalty, 'reason'] = out.loc[risk_excess_penalty, 'reason'].astype(str) + ' + 손절폭 과다 score 패널티'
    out['score'] = pd.to_numeric(out.get('score'), errors='coerce').fillna(0.0).clip(0.0, 100.0)

    liquid = trade_value >= MIN_TRADE_VALUE_KRW
    valid_value_ratio = (value > 0.0) & (value <= MAX_REASONABLE_VALUE_RATIO)
    low_volume_watch = (setup == 'watch') & (volume < 0.80)
    low_value_and_volume_watch = (setup == 'watch') & (value < 0.80) & (volume < 0.80)
    weak_backtested_setup = setup.isin(['breakout', 'trend_continuation'])
    non_theme_excess_risk = (setup != 'theme_repricing_breakout') & (risk > original_max_risk)
    theme_extreme_risk = (setup == 'theme_repricing_breakout') & (risk > THEME_MAX_RISK_PCT)
    watch_without_pullback = (setup == 'watch') & (drawdown52w > -3.0)
    final_mask = (
        liquid
        & valid_value_ratio
        & ~abnormal_trade_value
        & ~(low_volume_watch | low_value_and_volume_watch)
        & ~weak_backtested_setup
        & ~non_theme_excess_risk
        & ~theme_extreme_risk
        & ~watch_without_pullback
    )
    _print_runtime_filter_stats(out, liquid, valid_value_ratio, low_volume_watch, low_value_and_volume_watch, weak_backtested_setup, non_theme_excess_risk | theme_extreme_risk, watch_without_pullback, final_mask, abnormal_trade_value, severe_5d_downtrend, risk_excess_penalty)
    filtered = out.loc[final_mask].copy()
    if filtered.empty:
        filtered = _relaxed_fallback(out, trade_value, setup, risk, original_max_risk)
    if filtered.empty:
        return filtered.reset_index(drop=True)
    filtered['sector_rank'] = pd.to_numeric(filtered.get('sector_rank'), errors='coerce').fillna(99).astype(int)
    filtered['sector_strength_score'] = pd.to_numeric(filtered.get('sector_strength_score'), errors='coerce').fillna(0.0)
    filtered['market_rotation_score'] = pd.to_numeric(filtered.get('market_rotation_score'), errors='coerce').fillna(0.0)
    filtered = _repair_position_size(filtered)
    return _select_diverse_recent_aware(filtered)


def _print_runtime_filter_stats(out: pd.DataFrame, liquid: pd.Series, valid_value_ratio: pd.Series, low_volume_watch: pd.Series, low_value_and_volume_watch: pd.Series, weak_backtested_setup: pd.Series, excess_risk: pd.Series, watch_without_pullback: pd.Series, final_mask: pd.Series, abnormal_trade_value: pd.Series, severe_5d_downtrend: pd.Series, risk_excess_penalty: pd.Series) -> None:
    stats = {
        'input': int(len(out)),
        'liquid_pass': int(liquid.sum()),
        'value_ratio_pass': int(valid_value_ratio.sum()),
        'abnormal_trade_value': int(abnormal_trade_value.sum()),
        'severe_5d_downtrend': int(severe_5d_downtrend.sum()),
        'risk_score_penalty': int(risk_excess_penalty.sum()),
        'low_volume_watch': int(low_volume_watch.sum()),
        'low_value_and_volume_watch': int(low_value_and_volume_watch.sum()),
        'weak_setup': int(weak_backtested_setup.sum()),
        'excess_risk': int(excess_risk.sum()),
        'watch_without_pullback': int(watch_without_pullback.sum()),
        'final_pass': int(final_mask.sum()),
    }
    top = out[['code', 'name', 'sector', 'sector_rank', 'sector_strength_score', 'strategy_type', 'score', 'trade_value_krw', 'trade_value_ratio_20d', 'risk_pct', 'momentum_5d_pct', 'drawdown_52w_pct']].head(10).to_dict('records') if not out.empty else []
    print(f'[runtime_filter] stats={stats}')
    print(f'[runtime_filter] top_before_filter={top}')


def _repair_position_size(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if 'position_size_krw' not in out.columns:
        out['position_size_krw'] = 0.0
    position = pd.to_numeric(out['position_size_krw'], errors='coerce').fillna(0.0)
    entry = pd.to_numeric(out.get('entry'), errors='coerce').fillna(0.0)
    repair_mask = (position <= 0.0) & (entry > 0.0)
    if repair_mask.any():
        fallback_position = max(0.0, float(settings.account_equity_krw) * 0.30)
        out.loc[repair_mask, 'position_size_krw'] = fallback_position
        out.loc[repair_mask, 'reason'] = out.loc[repair_mask, 'reason'].astype(str) + ' + position_size_krw 30% fallback 적용'
    return out


def _select_diverse_recent_aware(df: pd.DataFrame) -> pd.DataFrame:
    top_n = _top_n()
    ranked = df.copy()
    recent_counts = _recent_recommendation_counts()
    ranked['repeat_count_30d'] = ranked['code'].astype(str).str.zfill(6).map(recent_counts).fillna(0).astype(int)
    ranked['diversity_score'] = (
        pd.to_numeric(ranked.get('score'), errors='coerce').fillna(0.0)
        + (pd.to_numeric(ranked.get('sector_strength_score'), errors='coerce').fillna(0.0).clip(0, 100) * 0.05)
        + (pd.to_numeric(ranked.get('trade_value_ratio_20d'), errors='coerce').fillna(0.0).clip(0, 3) * 1.5)
        + (pd.to_numeric(ranked.get('volume_ratio_20d'), errors='coerce').fillna(0.0).clip(0, 3) * 1.0)
        + (pd.to_numeric(ranked.get('change_pct_today'), errors='coerce').fillna(0.0).clip(-5, 8) * 0.4)
        - ranked['repeat_count_30d'] * _repeat_penalty()
    )
    ranked = ranked.sort_values(['diversity_score', 'score', 'sector_strength_score', 'trade_value_krw'], ascending=[False, False, False, False])
    selected = []
    selected_codes: set[str] = set()
    sector_counts: dict[str, int] = {}
    cooldown = _repeat_cooldown_count()
    max_per_sector = _max_per_sector()
    for _, row in ranked.iterrows():
        code = str(row.get('code', '')).zfill(6)
        sector = str(row.get('sector') or '기타')
        if code in selected_codes:
            continue
        if int(row.get('repeat_count_30d') or 0) >= cooldown and len(ranked) > top_n:
            continue
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        selected.append(row)
        selected_codes.add(code)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= top_n:
            break
    if len(selected) < top_n:
        for _, row in ranked.iterrows():
            code = str(row.get('code', '')).zfill(6)
            if code in selected_codes:
                continue
            selected.append(row)
            selected_codes.add(code)
            if len(selected) >= top_n:
                break
    result = pd.DataFrame(selected).reset_index(drop=True)
    print(f'[runtime_filter] selected_diverse={result[["code", "name", "sector", "sector_rank", "sector_strength_score", "score", "repeat_count_30d", "diversity_score"]].to_dict("records") if not result.empty else []}')
    return result.head(top_n)


def _recent_recommendation_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    _add_counts_from_latest(counts)
    _add_counts_from_history(counts)
    return counts


def _add_counts_from_latest(counts: dict[str, int]) -> None:
    if not LATEST_PATH.exists():
        return
    try:
        data = json.loads(LATEST_PATH.read_text(encoding='utf-8'))
        for row in data.get('kr_short_stocks') or []:
            code = str(row.get('code') or '').zfill(6)
            if code and code != '000000':
                counts[code] = counts.get(code, 0) + 2
    except Exception as exc:
        print(f'[runtime_filter] latest history read failed: {exc}')


def _add_counts_from_history(counts: dict[str, int]) -> None:
    if not HISTORY_PATH.exists():
        return
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))
        rows = data.get('items') or []
        for row in rows[:80]:
            code = str(row.get('code') or '').zfill(6)
            if code and code != '000000':
                counts[code] = counts.get(code, 0) + 1
    except Exception as exc:
        print(f'[runtime_filter] recent history read failed: {exc}')


def _relaxed_fallback(out: pd.DataFrame, trade_value: pd.Series, setup: pd.Series, risk: pd.Series, original_max_risk: float) -> pd.DataFrame:
    relaxed_mask = (
        (trade_value >= RELAXED_MIN_TRADE_VALUE_KRW)
        & ~setup.isin(['breakout', 'trend_continuation'])
        & ((setup == 'theme_repricing_breakout') | (risk <= max(original_max_risk, 16.0)))
        & (trade_value <= MAX_REASONABLE_TRADE_VALUE_KRW)
    )
    relaxed = out.loc[relaxed_mask].copy()
    if relaxed.empty:
        print('[runtime_filter] relaxed_fallback_pass=0')
        return relaxed
    relaxed['reason'] = relaxed.get('reason', '').astype(str) + ' + KRX/거래대금 데이터 불안정으로 완화 fallback 적용'
    print(f'[runtime_filter] relaxed_fallback_pass={len(relaxed)}')
    return _repair_position_size(relaxed)


def _load_runtime_rules():
    rules = _ORIGINAL_RULES_LOADER()
    threshold = _runtime_score_threshold(rules)
    max_risk = max(float(getattr(rules, 'max_risk_pct', 12.0) or 12.0), 16.0)
    try:
        return rules.__class__(**{**rules.__dict__, 'score_threshold': threshold, 'max_risk_pct': max_risk})
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
        return max(1, int(float(os.getenv('KR_TOP_N_RESULTS', '7'))))
    except ValueError:
        return 7


def _max_per_sector() -> int:
    try:
        return max(1, int(float(os.getenv('KR_MAX_PER_SECTOR', '2'))))
    except ValueError:
        return 2


def _repeat_cooldown_count() -> int:
    try:
        return max(1, int(float(os.getenv('KR_REPEAT_COOLDOWN_COUNT', '2'))))
    except ValueError:
        return 2


def _repeat_penalty() -> float:
    try:
        return max(0.0, float(os.getenv('KR_REPEAT_PENALTY', '8.0')))
    except ValueError:
        return 8.0


def _pre_filter_buffer_size() -> int:
    raw = os.getenv('KR_PREFILTER_RESULT_BUFFER')
    if raw is not None:
        try:
            return max(_top_n(), int(float(raw)))
        except ValueError:
            pass
    return max(120, _top_n() * 25)


def _select_pre_filter_buffer(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    return ranked.head(_pre_filter_buffer_size()).reset_index(drop=True)
