from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.gemini_report import review_report
from data.market_data import get_kr_stock_history, get_kr_stock_universe
from strategies.kr_short_rules import KrShortRules, load_kr_short_rules, rules_with_summary, save_kr_short_rules
from strategies.kr_short_stock import _entry, _failure_condition, _prepare_history, _reason, _rsi14, _score, _select_diversified, _setup, _stop
from strategies.metrics import momentum

REPORT_DIR = Path(__file__).resolve().parents[1] / 'reports'
REPORT_PATH = REPORT_DIR / 'kr_short_evolution_latest.json'


def run_kr_short_backtest(rules: KrShortRules | None = None, max_symbols: int | None = None) -> dict:
    rules = rules or load_kr_short_rules()
    universe = get_kr_stock_universe()
    if max_symbols:
        universe = universe.head(max_symbols)

    trades: list[dict] = []
    for row in universe.to_dict('records'):
        try:
            hist = _prepare_history(get_kr_stock_history(row['code']).copy())
            if len(hist) < 150:
                continue
            trades.extend(_backtest_one_symbol(hist, row, rules))
        except Exception:
            continue

    return _summarise(trades, rules)


def evolve_kr_short_rules(write: bool = False, max_symbols: int | None = None, ai_review: bool = True) -> dict:
    base = load_kr_short_rules()
    base_summary = run_kr_short_backtest(base, max_symbols=max_symbols)
    candidates = _candidate_rules(base)
    scored = []
    for candidate in candidates:
        summary = run_kr_short_backtest(candidate, max_symbols=max_symbols)
        scored.append((candidate, summary, _fitness(summary)))

    base_fitness = _fitness(base_summary)
    best_rules, best_summary, best_fitness = max(scored, key=lambda x: x[2], default=(base, base_summary, base_fitness))
    improvement = best_fitness - base_fitness
    accepted = _passes_guardrails(best_rules, best_summary) and improvement >= getattr(base, 'min_improvement_score', 0.05)

    result = {
        'created_at_kst': datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'base_rules': asdict(base),
        'base_summary': base_summary,
        'base_fitness': round(base_fitness, 4),
        'best_rules': asdict(best_rules),
        'best_summary': best_summary,
        'best_fitness': round(best_fitness, 4),
        'improvement': round(improvement, 4),
        'accepted': accepted,
        'write_requested': write,
    }
    if ai_review:
        try:
            result['ai_review'] = review_report(result)
        except Exception as exc:
            result['ai_review'] = {'enabled': True, 'used': False, 'error': str(exc)}

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pd.Series(result, dtype='object').to_json(REPORT_PATH, force_ascii=False, indent=2)

    if write and accepted:
        save_kr_short_rules(rules_with_summary(best_rules, best_summary))
        result['rules_written'] = True
    else:
        result['rules_written'] = False
    return result


def _backtest_one_symbol(hist: pd.DataFrame, row: dict, rules: KrShortRules) -> list[dict]:
    out: list[dict] = []
    start = 121
    end = len(hist) - max(rules.hold_days, rules.surge_lookahead_days) - 1
    for i in range(start, max(start, end)):
        window = hist.iloc[: i + 1].copy()
        latest = window.iloc[-1]
        prev = window.iloc[-2]
        price = float(latest['close'])
        ma20 = float(latest['ma20'])
        ma60 = float(latest['ma60'])
        ma120 = float(latest['ma120'])
        ma200 = float(latest['ma200'])
        atr14 = float(latest['atr14'])
        rsi14 = _rsi14(window['close'])
        if min(price, ma20, ma60, ma120, ma200, atr14) <= 0:
            continue

        high20 = float(window['high'].iloc[-21:-1].max())
        high60 = float(window['high'].iloc[-61:-1].max())
        high252 = float(window['high'].tail(252).max()) if len(window) >= 252 else float(window['high'].max())
        low10 = float(window['low'].tail(10).min())
        volume_ratio = _ratio(float(latest['volume']), float(latest['volume_ma20']))
        trade_value = float(latest.get('trade_value', price * latest['volume']))
        value_ratio = _ratio(trade_value, float(latest['trade_value_ma20']))
        drawdown60 = price / high60 - 1.0 if high60 else 0.0
        drawdown52w = price / high252 - 1.0 if high252 else 0.0
        gap_ma20 = price / ma20 - 1.0
        ret5 = momentum(window['close'], 5)
        ret20 = momentum(window['close'], 20)
        ret60 = momentum(window['close'], 60)
        ret252 = momentum(window['close'], min(252, len(window) - 1))

        sector_strength = float(row.get('sector_strength_score') or 0.0)
        sector_rank = int(row.get('sector_rank') or 99)
        market_rotation = float(row.get('market_rotation_score') or 0.0)
        change_today = float(row.get('change_pct_today') or 0.0)

        setup = _setup(price, float(prev['close']), float(prev['ma20']), ma20, ma60, ma120, ma200, high20, high60, drawdown60, drawdown52w, high252)
        score = _score(price, ma20, ma60, ma120, ma200, high20, high60, volume_ratio, value_ratio, trade_value, ret5, ret20, ret60, ret252, drawdown60, drawdown52w, gap_ma20, rsi14, setup, rules.max_gap_ma20_pct, sector_strength, sector_rank, market_rotation, change_today)
        if score < rules.score_threshold:
            continue

        stop = _stop(price, ma20, ma60, ma200, low10, atr14, setup)
        if stop >= price:
            stop = price * 0.96
        risk_pct = (price - stop) / price * 100.0
        if risk_pct < rules.min_risk_pct or risk_pct > rules.max_risk_pct:
            continue

        entry = _entry(price, high20, ma20, setup, high252)
        if entry / price - 1.0 > rules.max_entry_gap_pct / 100.0:
            continue

        future = hist.iloc[i + 1 : i + 1 + rules.hold_days]
        surge_future = hist.iloc[i + 1 : i + 1 + rules.surge_lookahead_days]
        if future.empty or surge_future.empty:
            continue

        trade_return, exit_reason = _simulate_trade(entry, stop, future, rules.hold_days)
        max_forward = float(surge_future['high'].max() / price - 1.0)
        caught_surge = max_forward >= rules.surge_threshold_pct / 100.0
        risk_per_share = max(entry - stop, price * 0.01)
        out.append({
            'code': str(row.get('code', '')).zfill(6),
            'name': row.get('name', ''),
            'sector': row.get('sector', '기타'),
            'date': str(latest['date'].date() if hasattr(latest['date'], 'date') else latest['date']),
            'setup': setup,
            'score': round(score, 2),
            'entry': round(entry, 2),
            'stop': round(stop, 2),
            'risk_pct': round(risk_pct, 2),
            'trade_return_pct': round(trade_return * 100, 2),
            'exit_reason': exit_reason,
            'max_forward_pct': round(max_forward * 100, 2),
            'caught_surge': caught_surge,
            'r_multiple': round((trade_return * entry) / risk_per_share, 2),
            'reason': _reason(row.get('sector', '기타'), setup, volume_ratio, value_ratio, ret20, drawdown60, drawdown52w, gap_ma20, rsi14, rules.max_gap_ma20_pct, sector_rank, sector_strength, market_rotation, change_today),
            'failure_condition': _failure_condition(setup),
        })
    return out


def _simulate_trade(entry: float, stop: float, future: pd.DataFrame, hold_days: int) -> tuple[float, str]:
    risk = max(entry - stop, entry * 0.01)
    target1 = entry + risk * 2.0
    target2 = entry + risk * 3.2
    entered = False
    last_close = entry
    for _, bar in future.head(hold_days).iterrows():
        low = float(bar['low'])
        high = float(bar['high'])
        close = float(bar['close'])
        if not entered:
            if high >= entry:
                entered = True
            else:
                last_close = close
                continue
        if low <= stop:
            return stop / entry - 1.0, 'stop'
        if high >= target2:
            return target2 / entry - 1.0, 'target2'
        if high >= target1:
            return target1 / entry - 1.0, 'target1'
        last_close = close
    if not entered:
        return 0.0, 'not_entered'
    return last_close / entry - 1.0, 'time_exit'


def _summarise(trades: list[dict], rules: KrShortRules) -> dict:
    if not trades:
        return {
            'trades': 0,
            'avg_return_pct': 0.0,
            'win_rate': 0.0,
            'surge_precision': 0.0,
            'profit_factor': 0.0,
            'avg_r_multiple': 0.0,
            'by_setup': {},
            'rules': asdict(rules),
        }
    df = pd.DataFrame(trades)
    gains = df.loc[df['trade_return_pct'] > 0, 'trade_return_pct'].sum()
    losses = abs(df.loc[df['trade_return_pct'] < 0, 'trade_return_pct'].sum())
    pf = float(gains / losses) if losses else float('inf')
    by_setup = df.groupby('setup').agg(
        trades=('code', 'count'),
        avg_return_pct=('trade_return_pct', 'mean'),
        win_rate=('trade_return_pct', lambda s: float((s > 0).mean())),
        surge_precision=('caught_surge', 'mean'),
        avg_r_multiple=('r_multiple', 'mean'),
    ).round(4).to_dict('index')
    return {
        'trades': int(len(df)),
        'avg_return_pct': round(float(df['trade_return_pct'].mean()), 4),
        'median_return_pct': round(float(df['trade_return_pct'].median()), 4),
        'win_rate': round(float((df['trade_return_pct'] > 0).mean()), 4),
        'surge_precision': round(float(df['caught_surge'].mean()), 4),
        'profit_factor': round(pf, 4) if pf != float('inf') else 999.0,
        'avg_r_multiple': round(float(df['r_multiple'].mean()), 4),
        'stop_rate': round(float((df['exit_reason'] == 'stop').mean()), 4),
        'target_rate': round(float(df['exit_reason'].isin(['target1', 'target2']).mean()), 4),
        'by_setup': by_setup,
        'rules': asdict(rules),
    }


def _candidate_rules(base: KrShortRules) -> list[KrShortRules]:
    candidates = [base]
    for score_threshold in sorted(set([base.score_threshold - 4, base.score_threshold - 2, base.score_threshold, base.score_threshold + 2, base.score_threshold + 4])):
        for max_gap in sorted(set([base.max_gap_ma20_pct - 3, base.max_gap_ma20_pct, base.max_gap_ma20_pct + 3])):
            for max_risk in sorted(set([base.max_risk_pct - 2, base.max_risk_pct, base.max_risk_pct + 2])):
                if score_threshold < 50 or max_gap < 6 or max_risk < 5:
                    continue
                candidates.append(replace(base, score_threshold=float(score_threshold), max_gap_ma20_pct=float(max_gap), max_risk_pct=float(max_risk)))
    return candidates


def _fitness(summary: dict) -> float:
    trades = summary.get('trades', 0)
    if trades <= 0:
        return -999.0
    sample_penalty = min(1.0, trades / 30.0)
    avg_return = summary.get('avg_return_pct', 0.0)
    surge_precision = summary.get('surge_precision', 0.0)
    profit_factor = min(summary.get('profit_factor', 0.0), 3.0)
    stop_rate = summary.get('stop_rate', 1.0)
    win_rate = summary.get('win_rate', 0.0)
    return sample_penalty * (
        avg_return * 0.40
        + (win_rate - 0.50) * 12.0
        + surge_precision * 6.0
        + profit_factor * 1.0
        - stop_rate * 2.5
    )


def _passes_guardrails(rules: KrShortRules, summary: dict) -> bool:
    return (
        summary.get('trades', 0) >= rules.min_backtest_trades
        and summary.get('surge_precision', 0.0) >= getattr(rules, 'min_surge_precision', 0.15)
        and summary.get('avg_return_pct', 0.0) >= getattr(rules, 'min_avg_return_pct', 0.3)
        and summary.get('profit_factor', 0.0) >= getattr(rules, 'min_profit_factor', 1.05)
        and summary.get('win_rate', 0.0) >= getattr(rules, 'min_win_rate', 0.45)
    )


def _ratio(num: float, den: float) -> float:
    return 0.0 if den <= 0 else num / den
