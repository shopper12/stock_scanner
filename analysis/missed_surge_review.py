from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings
from data.market_data_fast import get_kr_stock_universe_fast
from data.market_data import get_kr_stock_history
from strategies.kr_short_stock import _prepare_history, _rsi14

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_PATH = REPORT_DIR / 'latest.json'
MISSED_SURGE_PATH = REPORT_DIR / 'missed_surge_latest.json'


def build_missed_surge_review(limit: int = 30) -> dict:
    universe = get_kr_stock_universe_fast()
    latest = _read_json(LATEST_PATH, {})
    picked_codes = {str(row.get('code', '')).zfill(6) for row in latest.get('kr_short_stocks', [])}
    candidates = []
    for row in universe.to_dict('records'):
        code = str(row.get('code', '')).zfill(6)
        if not code or code in picked_codes:
            continue
        change_today = _float(row.get('change_pct_today'))
        trade_value = _float(row.get('trade_value_today'))
        if change_today < 4.0 and trade_value < settings.min_kr_trade_value_krw * 8.0:
            continue
        try:
            hist = _prepare_history(get_kr_stock_history(code).copy())
            if len(hist) < 65:
                reason = 'history_too_short'
                metrics = {}
            else:
                latest_bar = hist.iloc[-1]
                price = _float(latest_bar.get('close'))
                ma20 = _float(latest_bar.get('ma20'))
                ma60 = _float(latest_bar.get('ma60'))
                high20 = _float(hist['high'].iloc[-21:-1].max())
                high60 = _float(hist['high'].iloc[-61:-1].max())
                high252 = _float(hist['high'].tail(252).max()) if len(hist) >= 252 else _float(hist['high'].max())
                volume_ratio = _ratio(_float(latest_bar.get('volume')), _float(latest_bar.get('volume_ma20')))
                value_ratio = _ratio(_float(latest_bar.get('trade_value')), _float(latest_bar.get('trade_value_ma20')))
                ret5 = _ratio(price, _float(hist['close'].iloc[-6])) - 1.0 if len(hist) > 6 else 0.0
                ret20 = _ratio(price, _float(hist['close'].iloc[-21])) - 1.0 if len(hist) > 21 else 0.0
                gap_ma20 = _ratio(price, ma20) - 1.0 if ma20 else 0.0
                rsi14 = _rsi14(hist['close'])
                metrics = {
                    'price': round(price),
                    'ma20': round(ma20),
                    'ma60': round(ma60),
                    'high20': round(high20),
                    'high60': round(high60),
                    'high252': round(high252),
                    'ret5_pct': round(ret5 * 100, 2),
                    'ret20_pct': round(ret20 * 100, 2),
                    'gap_ma20_pct': round(gap_ma20 * 100, 2),
                    'volume_ratio_20d': round(volume_ratio, 2),
                    'trade_value_ratio_20d': round(value_ratio, 2),
                    'rsi14': round(rsi14, 1),
                }
                reason = _miss_reason(price, ma20, ma60, high20, high60, high252, ret5, ret20, gap_ma20, volume_ratio, value_ratio, rsi14, change_today, trade_value)
        except Exception as exc:
            reason = f'analysis_error:{exc.__class__.__name__}'
            metrics = {}
        candidates.append({
            'code': code,
            'name': row.get('name', ''),
            'sector': row.get('sector', '기타'),
            'market': row.get('market', 'UNKNOWN'),
            'change_pct_today': round(change_today, 2),
            'trade_value_krw': round(trade_value),
            'fast_rank_score': round(_float(row.get('fast_rank_score')), 2),
            'miss_reason': reason,
            'metrics': metrics,
        })
    candidates = sorted(candidates, key=lambda x: (x['change_pct_today'], x['trade_value_krw']), reverse=True)[:limit]
    out = {
        'schema_version': 1,
        'created_at_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'picked_count': len(picked_codes),
        'review_count': len(candidates),
        'note': 'Strong movers not selected by the main scanner. Used to diagnose missed surges like LG-type repricing moves.',
        'missed_surge_candidates': candidates,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    MISSED_SURGE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return out


def _miss_reason(price: float, ma20: float, ma60: float, high20: float, high60: float, high252: float, ret5: float, ret20: float, gap_ma20: float, volume_ratio: float, value_ratio: float, rsi14: float, change_today: float, trade_value: float) -> str:
    reasons = []
    if ret20 < 0.075:
        reasons.append('ret20_not_enough_for_theme_repricing')
    if ret5 < 0.045:
        reasons.append('ret5_not_enough')
    if volume_ratio < 1.35 and value_ratio < 1.35:
        reasons.append('volume_value_ratio_not_enough')
    if ma20 > 0 and price / ma20 - 1.0 > 0.22:
        reasons.append('too_far_above_ma20')
    if rsi14 > 84:
        reasons.append('rsi_too_hot')
    if price < ma20 or price < ma60:
        reasons.append('below_ma20_or_ma60')
    if high20 > 0 and price < high20 * 0.995:
        reasons.append('not_high20_breakout')
    if change_today >= 4.0 and trade_value >= settings.min_kr_trade_value_krw * 8.0 and ret20 < 0.075:
        reasons.append('single_day_surge_needs_early_repricing_rule')
    return ','.join(reasons) if reasons else 'passed_surge_filters_but_lost_score_sort_or_risk_filter'


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _float(value) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _ratio(num: float, den: float) -> float:
    return 0.0 if den <= 0 else num / den


if __name__ == '__main__':
    print(json.dumps(build_missed_surge_review().get('missed_surge_candidates', [])[:10], ensure_ascii=False, indent=2))
