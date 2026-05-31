from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from data.market_data import get_kr_stock_history, get_kr_stock_universe
from strategies.kr_short_rules import load_kr_short_rules
from strategies.kr_short_stock import _prepare_history, _rsi14, _score, _setup
from strategies.metrics import momentum

REPORT_DIR = Path(__file__).resolve().parents[1] / 'reports'
REPORT_LATEST_PATH = REPORT_DIR / 'missed_surge_audit_latest.json'


def run_missed_surge_audit(
    lookback_days: int = 30,
    surge_threshold_pct: float = 15.0,
    lookahead_days: int = 20,
    max_symbols: int | None = None,
) -> dict:
    """Find stocks that were not selected by the strategy but surged afterwards.

    This is a historical audit, not a live recommendation engine. It answers:
    "Which future winners were below the strategy threshold, and why?"
    """
    rules = load_kr_short_rules()
    universe = get_kr_stock_universe()
    if max_symbols:
        universe = universe.head(max_symbols)

    missed: list[dict] = []
    for row in universe.to_dict('records'):
        code = str(row.get('code', '')).zfill(6)
        if not code:
            continue
        try:
            hist = _prepare_history(get_kr_stock_history(code).copy())
            if len(hist) < 150:
                continue
            start = max(121, len(hist) - lookback_days - lookahead_days)
            end = len(hist) - lookahead_days
            for i in range(start, max(start, end)):
                current = _score_snapshot(hist.iloc[: i + 1].copy(), row, rules)
                if not current:
                    continue
                score = float(current['score'])
                threshold = float(rules.score_threshold)
                if score >= threshold:
                    continue
                future = hist.iloc[i + 1 : i + 1 + lookahead_days]
                if future.empty:
                    continue
                price = float(hist.iloc[i]['close'])
                if price <= 0:
                    continue
                max_fwd = float(future['high'].max() / price - 1.0)
                if max_fwd < surge_threshold_pct / 100.0:
                    continue
                missed.append({
                    'code': code,
                    'name': row.get('name', ''),
                    'sector': row.get('sector', ''),
                    'date': _date_text(hist.iloc[i].get('date')),
                    'score_at_miss': round(score, 1),
                    'threshold_at_miss': round(threshold, 1),
                    'score_gap': round(threshold - score, 1),
                    'setup_at_miss': current['setup'],
                    'max_surge_pct': round(max_fwd * 100, 1),
                    'miss_reason': _diagnose_miss(
                        score=score,
                        threshold=threshold,
                        setup=current['setup'],
                        rsi14=current['rsi14'],
                        drawdown52w=current['drawdown52w'],
                        gap_ma20=current['gap_ma20'],
                        volume_ratio=current['volume_ratio'],
                        value_ratio=current['value_ratio'],
                        rules=rules,
                    ),
                    'rsi14': round(current['rsi14'], 1),
                    'drawdown52w_pct': round(current['drawdown52w'] * 100, 1),
                    'volume_ratio': round(current['volume_ratio'], 2),
                    'trade_value_ratio': round(current['value_ratio'], 2),
                    'gap_ma20_pct': round(current['gap_ma20'] * 100, 1),
                    'ret5_pct': round(current['ret5'] * 100, 1),
                    'ret20_pct': round(current['ret20'] * 100, 1),
                })
        except Exception:
            continue

    summary = _summarise_misses(missed)
    _save_audit(missed, summary)
    return summary


def _score_snapshot(hist: pd.DataFrame, row: dict, rules) -> dict | None:
    if len(hist) < 122:
        return None
    latest = hist.iloc[-1]
    prev = hist.iloc[-2]
    price = float(latest['close'])
    ma20 = float(latest['ma20'])
    ma60 = float(latest['ma60'])
    ma120 = float(latest['ma120'])
    ma200 = float(latest['ma200'])
    if min(price, ma20, ma60, ma120, ma200) <= 0:
        return None

    high20 = float(hist['high'].iloc[-21:-1].max())
    high60 = float(hist['high'].iloc[-61:-1].max())
    high252 = float(hist['high'].tail(252).max()) if len(hist) >= 252 else float(hist['high'].max())
    volume_ratio = _ratio(float(latest['volume']), float(latest['volume_ma20']))
    trade_value = float(latest.get('trade_value', price * latest['volume']))
    value_ratio = _ratio(trade_value, float(latest['trade_value_ma20']))
    drawdown60 = price / high60 - 1.0 if high60 else 0.0
    drawdown52w = price / high252 - 1.0 if high252 else 0.0
    gap_ma20 = price / ma20 - 1.0
    ret5 = momentum(hist['close'], 5)
    ret20 = momentum(hist['close'], 20)
    ret60 = momentum(hist['close'], 60)
    ret252 = momentum(hist['close'], min(252, len(hist) - 1))
    rsi14 = _rsi14(hist['close'])
    sector_strength = float(row.get('sector_strength_score') or 0.0)
    sector_rank = int(row.get('sector_rank') or 99)
    market_rotation = float(row.get('market_rotation_score') or 0.0)
    change_today = float(row.get('change_pct_today') or 0.0)
    setup = _setup(
        price,
        float(prev['close']),
        float(prev['ma20']),
        ma20,
        ma60,
        ma120,
        ma200,
        high20,
        high60,
        drawdown60,
        drawdown52w,
        high252,
        ret5,
        ret20,
        volume_ratio,
        value_ratio,
        trade_value,
        sector_rank,
        market_rotation,
        change_today,
    )
    score = _score(
        price,
        ma20,
        ma60,
        ma120,
        ma200,
        high20,
        high60,
        volume_ratio,
        value_ratio,
        trade_value,
        ret5,
        ret20,
        ret60,
        ret252,
        drawdown60,
        drawdown52w,
        gap_ma20,
        rsi14,
        setup,
        rules.max_gap_ma20_pct,
        sector_strength,
        sector_rank,
        market_rotation,
        change_today,
    )
    return {
        'setup': setup,
        'score': score,
        'rsi14': rsi14,
        'drawdown52w': drawdown52w,
        'gap_ma20': gap_ma20,
        'volume_ratio': volume_ratio,
        'value_ratio': value_ratio,
        'ret5': ret5,
        'ret20': ret20,
    }


def _diagnose_miss(score: float, threshold: float, setup: str, rsi14: float, drawdown52w: float, gap_ma20: float, volume_ratio: float, value_ratio: float, rules) -> str:
    reasons = []
    if score < threshold:
        reasons.append(f'score({score:.1f}) < threshold({threshold:.1f})')
    if rsi14 > 72:
        reasons.append(f'RSI 과매수({rsi14:.1f})')
    if gap_ma20 > rules.max_gap_ma20_pct / 100.0:
        reasons.append(f'MA20 괴리 과도({gap_ma20 * 100:.1f}%)')
    if drawdown52w > -0.03 and setup not in ('new_52w_high_breakout', 'theme_repricing_breakout'):
        reasons.append('52주 고점 근접 패널티')
    if volume_ratio < 1.0 and value_ratio < 1.0:
        reasons.append(f'거래량/거래대금 부족({volume_ratio:.2f}/{value_ratio:.2f})')
    if setup == 'watch':
        reasons.append('setup=watch (패턴 미분류)')
    return ' | '.join(reasons) if reasons else 'score 소폭 미달 또는 위험/진입 필터 문제'


def _summarise_misses(missed: list[dict]) -> dict:
    if not missed:
        return {
            'created_at_kst': _now_kst(),
            'total_missed': 0,
            'recommendation': '놓친 급등 없음',
        }
    df = pd.DataFrame(missed)
    reason_counter = Counter()
    for reason in df['miss_reason'].fillna('unknown'):
        for part in str(reason).split(' | '):
            if part:
                reason_counter[part] += 1
    avg_score_gap = round(float(df['score_gap'].mean()), 2)
    avg_surge = round(float(df['max_surge_pct'].mean()), 1)
    within_3pts = int((df['score_gap'] <= 3).sum())
    within_5pts = int((df['score_gap'] <= 5).sum())
    return {
        'created_at_kst': _now_kst(),
        'total_missed': int(len(missed)),
        'avg_score_gap': avg_score_gap,
        'avg_surge_pct': avg_surge,
        'within_3pts_of_threshold': within_3pts,
        'within_5pts_of_threshold': within_5pts,
        'top_miss_reasons': dict(reason_counter.most_common(8)),
        'top_missed_setups': df['setup_at_miss'].value_counts().to_dict(),
        'recommendation': _auto_recommend(avg_score_gap, within_3pts, len(missed)),
    }


def _auto_recommend(avg_gap: float, within_3: int, total: int) -> str:
    if total == 0:
        return '놓친 급등 없음'
    ratio = within_3 / total
    if ratio >= 0.5 and avg_gap <= 4.0:
        return f'놓친 {total}건 중 {within_3}건이 threshold 3점 이내 미달. threshold 1~3점 하향 후보를 우선 검토.'
    if avg_gap > 8.0:
        return f'평균 score 부족분 {avg_gap:.1f}점. threshold보다 score 함수, volume/momentum 계수 개선 필요.'
    return f'놓친 {total}건, 평균 {avg_gap:.1f}점 부족. setup 분류와 과열 패널티 세부 검토 필요.'


def _save_audit(missed: list[dict], summary: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d_%H%M%S')
    payload = {
        'schema_version': 1,
        'summary': summary,
        'missed_list': missed,
    }
    path = REPORT_DIR / f'missed_surge_audit_{ts}.json'
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    path.write_text(text, encoding='utf-8')
    REPORT_LATEST_PATH.write_text(text, encoding='utf-8')


def _date_text(value) -> str:
    return str(value.date() if hasattr(value, 'date') else value)


def _now_kst() -> str:
    return datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S %Z')


def _ratio(num: float, den: float) -> float:
    return 0.0 if den <= 0 else num / den


if __name__ == '__main__':
    print(json.dumps(run_missed_surge_audit(), ensure_ascii=False, indent=2))
