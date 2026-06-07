from __future__ import annotations

import os

import pandas as pd

from config import settings
from data.market_data_fast import get_kr_stock_universe_fast
from strategies import kr_short_stock as base

MIN_TRADE_VALUE_KRW = 5_000_000_000
RELAXED_MIN_TRADE_VALUE_KRW = 500_000_000

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
        object.__setattr__(settings, 'bull_market_mode', False)  # [FIX-1] base threshold에서 bull_market_mode 이중 가산 제거
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
    setup = out.get('strategy_type', pd.Series([''] * len(out))).astype(str)
    rules = _ORIGINAL_RULES_LOADER()
    original_max_risk = float(getattr(rules, 'max_risk_pct', 12.0) or 12.0)
    liquid = trade_value >= MIN_TRADE_VALUE_KRW
    valid_value_ratio = value > 0.0
    low_volume_watch = (setup == 'watch') & (volume < 0.80)
    low_value_and_volume_watch = (setup == 'watch') & (value < 0.80) & (volume < 0.80)
    weak_backtested_setup = setup.isin(['breakout', 'trend_continuation'])  # [FIX-2] PF < 1.0 setup 제거
    non_theme_excess_risk = (setup != 'theme_repricing_breakout') & (risk > original_max_risk)  # [FIX-3] 16% 완화는 theme에만 적용
    watch_without_pullback = (setup == 'watch') & (drawdown52w > -3.0)  # [FIX-4] 눌림 없는 watch 제거
    final_mask = (
        liquid
        & valid_value_ratio
        & ~(low_volume_watch | low_value_and_volume_watch)
        & ~weak_backtested_setup
        & ~non_theme_excess_risk
        & ~watch_without_pullback
    )
    _print_runtime_filter_stats(out, liquid, valid_value_ratio, low_volume_watch, low_value_and_volume_watch, weak_backtested_setup, non_theme_excess_risk, watch_without_pullback, final_mask)
    filtered = out.loc[final_mask].copy()
    if filtered.empty:
        filtered = _relaxed_fallback(out, trade_value, setup, risk, original_max_risk)
    if filtered.empty:
        return filtered.reset_index(drop=True)
    filtered['sector_rank'] = 99
    filtered['sector_strength_score'] = 0.0
    filtered['market_rotation_score'] = 0.0
    return filtered.sort_values(['score', 'trade_value_krw', 'change_pct_today'], ascending=[False, False, False]).reset_index(drop=True).head(_top_n())


def _print_runtime_filter_stats(out: pd.DataFrame, liquid: pd.Series, valid_value_ratio: pd.Series, low_volume_watch: pd.Series, low_value_and_volume_watch: pd.Series, weak_backtested_setup: pd.Series, non_theme_excess_risk: pd.Series, watch_without_pullback: pd.Series, final_mask: pd.Series) -> None:
    stats = {
        'input': int(len(out)),
        'liquid_pass': int(liquid.sum()),
        'value_ratio_pass': int(valid_value_ratio.sum()),
        'low_volume_watch': int(low_volume_watch.sum()),
        'low_value_and_volume_watch': int(low_value_and_volume_watch.sum()),
        'weak_setup': int(weak_backtested_setup.sum()),
        'excess_risk': int(non_theme_excess_risk.sum()),
        'watch_without_pullback': int(watch_without_pullback.sum()),
        'final_pass': int(final_mask.sum()),
    }
    top = out[['code', 'name', 'strategy_type', 'score', 'trade_value_krw', 'trade_value_ratio_20d', 'risk_pct', 'drawdown_52w_pct']].head(10).to_dict('records') if not out.empty else []
    print(f'[runtime_filter] stats={stats}')
    print(f'[runtime_filter] top_before_filter={top}')


def _relaxed_fallback(out: pd.DataFrame, trade_value: pd.Series, setup: pd.Series, risk: pd.Series, original_max_risk: float) -> pd.DataFrame:
    relaxed_mask = (
        (trade_value >= RELAXED_MIN_TRADE_VALUE_KRW)
        & ~setup.isin(['breakout', 'trend_continuation'])
        & ((setup == 'theme_repricing_breakout') | (risk <= max(original_max_risk, 16.0)))
    )
    relaxed = out.loc[relaxed_mask].copy()
    if relaxed.empty:
        print('[runtime_filter] relaxed_fallback_pass=0')
        return relaxed
    relaxed['reason'] = relaxed.get('reason', '').astype(str) + ' + KRX/거래대금 데이터 불안정으로 완화 fallback 적용'
    print(f'[runtime_filter] relaxed_fallback_pass={len(relaxed)}')
    return relaxed


def _load_runtime_rules():
    rules = _ORIGINAL_RULES_LOADER()
    threshold = _runtime_score_threshold(rules)  # [FIX-1] 기본 55점 기준 유지
    max_risk = max(float(getattr(rules, 'max_risk_pct', 12.0) or 12.0), 16.0)  # [FIX-3] theme_repricing_breakout 후보 복구용 risk buffer
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
        return max(1, int(float(os.getenv('KR_TOP_N_RESULTS', '5'))))
    except ValueError:
        return 5


def _pre_filter_buffer_size() -> int:
    raw = os.getenv('KR_PREFILTER_RESULT_BUFFER')
    if raw is not None:
        try:
            return max(_top_n(), int(float(raw)))
        except ValueError:
            pass
    return max(80, _top_n() * 20)


def _select_pre_filter_buffer(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    return ranked.head(_pre_filter_buffer_size()).reset_index(drop=True)
