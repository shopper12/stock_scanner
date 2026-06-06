from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.gemini_report import review_report
from backtest.missed_surge_audit import run_missed_surge_audit
from data.market_data import get_kr_stock_history, get_kr_stock_universe
from strategies.kr_short_rules import KrShortRules, load_kr_short_rules, rules_with_summary, save_kr_short_rules
from strategies.kr_short_stock import _entry, _failure_condition, _prepare_history, _reason, _rsi14, _score, _setup, _stop
from strategies.metrics import momentum

REPORT_DIR = Path(__file__).resolve().parents[1] / 'reports'
REPORT_PATH = REPORT_DIR / 'kr_short_evolution_latest.json'


def run_kr_short_backtest(rules: KrShortRules | None = None, max_symbols: int | None = None, write_trades: bool = False) -> dict:
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

    if write_trades:
        try:
            from data.chart_builder import save_backtest_trades
            save_backtest_trades(trades)
        except Exception:
            pass
    return _summarise(trades, rules)


def evolve_kr_short_rules(write: bool = False, max_symbols: int | None = None, ai_review: bool = True) -> dict:
    base = load_kr_short_rules()
    audit_summary = _safe_missed_surge_audit(max_symbols=max_symbols)
    base_summary = run_kr_short_backtest(base, max_symbols=max_symbols)
    candidates = _candidate_rules(base, audit_summary)
    scored = []
    for candidate in candidates:
        summary = run_kr_short_backtest(candidate, max_symbols=max_symbols)
        scored.append((candidate, summary, _fitness(summary, audit_summary)))

    base_fitness = _fitness(base_summary, audit_summary)
    best_rules, best_summary, best_fitness = max(scored, key=lambda x: x[2], default=(base, base_summary, base_fitness))
    best_summary = run_kr_short_backtest(best_rules, max_symbols=max_symbols, write_trades=True)
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
        'missed_surge_audit': audit_summary,
        'candidate_count': len(candidates),
        'trades_report': 'reports/kr_short_trades_latest.json',
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


def _safe_missed_surge_audit(max_symbols: int | None = None) -> dict:
    try:
        return run_missed_surge_audit(max_symbols=max_symbols)
    except Exception as exc:
        return {
            'total_missed': 0,
            'audit_error': f'{exc.__class__.__name__}: {exc}',
            'recommendation': '미포착 급등 감사 실패. 기존 백테스트만 사용.',
        }


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

        trade_return, exit_reason, exit_date, exit_price = _simulate_trade(entry, stop, future, rules.hold_days)
        max_forward = float(surge_future['high'].max() / price - 1.0)
        caught_surge = max_forward >= rules.surge_threshold_pct / 100.0
        risk_per_share = max(entry - stop, price * 0.01)
        target1 = entry + risk_per_share * 2.0
        target2 = entry + risk_per_share * 3.2
        out.append({
            'code': str(row.get('code', '')).zfill(6),
            'name': row.get('name', ''),
            'sector': row.get('sector', '기타'),
            'date': str(latest['date'].date() if hasattr(latest['date'], 'date') else latest['date']),
            'entry_date': str(latest['date'].date() if hasattr(latest['date'], 'date') else latest['date']),
            'exit_date': exit_date,
            'setup': setup,
            'score': round(score, 2),
            'entry': round(entry, 2),
            'stop': round(stop, 2),
            'target1': round(target1, 2),
            'target2': round(target2, 2),
            'exit_price': round(exit_price, 2),
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


def _simulate_trade(entry: float, stop: float, future: pd.DataFrame, hold_days: int) -> tuple[float, str, str, float]:
    risk = max(entry - stop, entry * 0.01)
    target1 = entry + risk * 2.0
    target2 = entry + risk * 3.2
    entered = False
    last_close = entry
    last_date = ''
    for _, bar in future.head(hold_days).iterrows():
        low = float(bar['low'])
        high = float(bar['high'])
        close = float(bar['close'])
        last_close = close
        last_date = str(bar['date'].date() if hasattr(bar['date'], 'date') else bar['date'])
        if not entered:
            if high >= entry:
                entered = True
            else:
                continue
        if low <= stop:
            return stop / entry - 1.0, 'stop', last_date, stop
        if high >= target2:
            return target2 / entry - 1.0, 'target2', last_date, target2
        if high >= target1:
            return target1 / entry - 1.0, 'target1', last_date, target1
    if not entered:
        return 0.0, 'not_entered', last_date, last_close
    return last_close / entry - 1.0, 'time_exit', last_date, last_close


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


def _candidate_rules(base: KrShortRules, audit_summary: dict | None = None) -> list[KrShortRules]:
    audit_summary = audit_summary or {}
    score_values = {base.score_threshold - 4, base.score_threshold - 2, base.score_threshold, base.score_threshold + 2, base.score_threshold + 4}
    if int(audit_summary.get('within_3pts_of_threshold', 0) or 0) >= 5:
        score_values.update({base.score_threshold - 3, base.score_threshold - 1})
    if int(audit_summary.get('within_5pts_of_threshold', 0) or 0) >= 8:
        score_values.add(base.score_threshold - 5)

    candidates = [base]
    for score_threshold in sorted(score_values):
        for max_gap in sorted(set([base.max_gap_ma20_pct - 3, base.max_gap_ma20_pct, base.max_gap_ma20_pct + 3])):
            for max_risk in sorted(set([base.max_risk_pct - 2, base.max_risk_pct, base.max_risk_pct + 2])):
                if score_threshold < 48 or max_gap < 6 or max_risk < 5:
                    continue
                candidates.append(replace(base, score_threshold=score_threshold, max_gap_ma20_pct=max_gap, max_risk_pct=max_risk))
    return candidates


def _passes_guardrails(rules: KrShortRules, summary: dict) -> bool:
    return (
        summary.get('trades', 0) >= rules.min_backtest_trades
        and summary.get('surge_precision', 0.0) >= rules.min_surge_precision
        and summary.get('avg_return_pct', 0.0) >= rules.min_avg_return_pct
        and summary.get('profit_factor', 0.0) >= rules.min_profit_factor
        and summary.get('win_rate', 0.0) >= rules.min_win_rate
    )


def _fitness(summary: dict, audit_summary: dict | None = None) -> float:
    audit_summary = audit_summary or {}
    trade_penalty = 0.0 if summary.get('trades', 0) >= 10 else -1.0
    missed_count = float(audit_summary.get('total_missed', 0) or 0)
    near_threshold = float(audit_summary.get('within_5pts_of_threshold', 0) or 0)
    missed_penalty = min(missed_count / 200.0, 1.0)
    recoverable_bonus = min(near_threshold / 50.0, 0.5)
    return (
        summary.get('avg_return_pct', 0.0) / 10.0
        + summary.get('win_rate', 0.0)
        + summary.get('surge_precision', 0.0)
        + min(summary.get('profit_factor', 0.0), 5.0) / 5.0
        + summary.get('avg_r_multiple', 0.0) / 3.0
        + trade_penalty
        - missed_penalty
        + recoverable_bonus
    )


def _ratio(value: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return value / baseline
