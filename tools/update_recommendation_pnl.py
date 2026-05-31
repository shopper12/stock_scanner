from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from config import settings
from data.market_data import get_kr_stock_history
from data.realtime_price import try_kr_realtime_quote

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'
HISTORY_PATH = REPORT_DIR / 'recommendation_history.json'
PERFORMANCE_PATH = REPORT_DIR / 'recommendation_performance_latest.json'

HOLD_DAYS_FOR_TIME_EXIT = 10


def update_recommendation_pnl(history_path: Path = HISTORY_PATH, performance_path: Path = PERFORMANCE_PATH) -> dict:
    history = _read_json(history_path, {'schema_version': 1, 'items': []})
    items = history.get('items', [])
    updated_items = []
    for item in items:
        updated_items.append(_update_item(dict(item)))

    summary = _build_summary(updated_items)
    now = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
    updated_history = {
        **history,
        'updated_at_kst': now,
        'items': updated_items,
    }
    performance = {
        'schema_version': 1,
        'created_at_kst': now,
        'source_history': str(history_path.relative_to(ROOT_DIR)) if history_path.is_absolute() or str(history_path).startswith(str(ROOT_DIR)) else str(history_path),
        'summary': summary,
        'items': updated_items[:300],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(updated_history, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    performance_path.write_text(json.dumps(performance, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return performance


def _update_item(item: dict) -> dict:
    code = str(item.get('code') or '').zfill(6)
    entry = _float(item.get('entry') or item.get('price_at_recommendation'))
    stop = _float(item.get('stop_loss'))
    target1 = _float(item.get('target1'))
    target2 = _float(item.get('target2'))
    scan_date = str(item.get('scan_date') or '')[:10]

    latest_price = _float(item.get('latest_price'))
    latest_basis = item.get('latest_price_basis') or 'unknown'
    latest_timestamp = item.get('latest_price_timestamp') or 'unknown'
    max_high = latest_price
    min_low = latest_price
    holding_days = _holding_days(scan_date)
    status = 'open'
    status_detail = ''

    if code and code != '000000':
        try:
            hist = get_kr_stock_history(code).copy()
            if scan_date and 'date' in hist.columns:
                hist['date_str'] = hist['date'].astype(str).str[:10]
                hist = hist[hist['date_str'] >= scan_date]
            if not hist.empty:
                latest_close = _float(hist['close'].iloc[-1])
                latest_price = latest_close or latest_price
                max_high = max(_float(hist['high'].max()), latest_price)
                min_low = min(_float(hist['low'].min()), latest_price) if latest_price else _float(hist['low'].min())
                latest_basis = 'daily_history'
                latest_timestamp = str(hist['date'].iloc[-1])[:10]
                status, status_detail = _status_from_path(hist, entry, stop, target1, target2, holding_days)
        except Exception as exc:
            status_detail = f'history_update_failed: {exc.__class__.__name__}'

        quote = try_kr_realtime_quote(code)
        if quote.get('ok') and quote.get('price'):
            latest_price = _float(quote.get('price'))
            latest_basis = 'realtime_quote'
            latest_timestamp = quote.get('timestamp_kst') or latest_timestamp
            if status == 'open':
                status, quote_detail = _status_from_latest(latest_price, stop, target1, target2, holding_days)
                status_detail = status_detail or quote_detail

    pnl_pct = round((latest_price / entry - 1.0) * 100, 2) if entry > 0 and latest_price > 0 else None
    pnl_krw = round(latest_price - entry) if entry > 0 and latest_price > 0 else None

    item.update({
        'latest_price': round(latest_price) if latest_price else item.get('latest_price'),
        'latest_price_basis': latest_basis,
        'latest_price_timestamp': latest_timestamp,
        'pnl_pct': pnl_pct,
        'pnl_krw_per_share': pnl_krw,
        'status': status,
        'status_detail': status_detail,
        'holding_days': holding_days,
        'max_high_since_recommendation': round(max_high) if max_high else None,
        'min_low_since_recommendation': round(min_low) if min_low else None,
    })
    return item


def _status_from_path(hist, entry: float, stop: float, target1: float, target2: float, holding_days: int) -> tuple[str, str]:
    for _, row in hist.iterrows():
        low = _float(row.get('low'))
        high = _float(row.get('high'))
        day = str(row.get('date'))[:10]
        hit_stop = stop > 0 and low > 0 and low <= stop
        hit_t2 = target2 > 0 and high >= target2
        hit_t1 = target1 > 0 and high >= target1
        if hit_stop and (hit_t1 or hit_t2):
            return 'hit_stop', f'{day}: stop and target touched in same candle; conservative stop status'
        if hit_stop:
            return 'hit_stop', f'{day}: low <= stop_loss'
        if hit_t2:
            return 'hit_target2', f'{day}: high >= target2'
        if hit_t1:
            return 'hit_target1', f'{day}: high >= target1'
    if holding_days >= HOLD_DAYS_FOR_TIME_EXIT:
        return 'time_exit_candidate', f'holding_days >= {HOLD_DAYS_FOR_TIME_EXIT}'
    return 'open', ''


def _status_from_latest(latest_price: float, stop: float, target1: float, target2: float, holding_days: int) -> tuple[str, str]:
    if stop > 0 and latest_price <= stop:
        return 'hit_stop', 'latest_price <= stop_loss'
    if target2 > 0 and latest_price >= target2:
        return 'hit_target2', 'latest_price >= target2'
    if target1 > 0 and latest_price >= target1:
        return 'hit_target1', 'latest_price >= target1'
    if holding_days >= HOLD_DAYS_FOR_TIME_EXIT:
        return 'time_exit_candidate', f'holding_days >= {HOLD_DAYS_FOR_TIME_EXIT}'
    return 'open', ''


def _build_summary(items: list[dict]) -> dict:
    measurable = [x for x in items if x.get('pnl_pct') is not None]
    wins = [x for x in measurable if _float(x.get('pnl_pct')) > 0]
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get('status') or 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        'total_recommendations': len(items),
        'measurable_count': len(measurable),
        'avg_pnl_pct': _round(mean([_float(x.get('pnl_pct')) for x in measurable])) if measurable else 0.0,
        'median_pnl_pct': _median([_float(x.get('pnl_pct')) for x in measurable]) if measurable else 0.0,
        'win_rate': _round(len(wins) / len(measurable)) if measurable else 0.0,
        'hit_stop_rate': _status_rate(items, 'hit_stop'),
        'hit_target1_rate': _status_rate(items, 'hit_target1'),
        'hit_target2_rate': _status_rate(items, 'hit_target2'),
        'status_counts': status_counts,
        'by_strategy_type': _group_summary(items, 'strategy_type'),
        'by_score_band': _score_band_summary(items),
    }


def _group_summary(items: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(str(item.get(key) or 'unknown'), []).append(item)
    return {name: _mini_summary(rows) for name, rows in sorted(groups.items())}


def _score_band_summary(items: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for item in items:
        score = _float(item.get('score_at_recommendation'))
        if score >= 80:
            band = '80+'
        elif score >= 70:
            band = '70-79'
        elif score >= 60:
            band = '60-69'
        elif score >= 50:
            band = '50-59'
        else:
            band = '<50'
        groups.setdefault(band, []).append(item)
    return {name: _mini_summary(rows) for name, rows in sorted(groups.items())}


def _mini_summary(rows: list[dict]) -> dict:
    measurable = [x for x in rows if x.get('pnl_pct') is not None]
    pnl = [_float(x.get('pnl_pct')) for x in measurable]
    return {
        'count': len(rows),
        'measurable_count': len(measurable),
        'avg_pnl_pct': _round(mean(pnl)) if pnl else 0.0,
        'win_rate': _round(sum(1 for x in pnl if x > 0) / len(pnl)) if pnl else 0.0,
        'hit_stop_rate': _status_rate(rows, 'hit_stop'),
        'hit_target1_rate': _status_rate(rows, 'hit_target1'),
        'hit_target2_rate': _status_rate(rows, 'hit_target2'),
    }


def _status_rate(items: list[dict], status: str) -> float:
    if not items:
        return 0.0
    return _round(sum(1 for x in items if x.get('status') == status) / len(items))


def _holding_days(scan_date: str) -> int:
    try:
        start = datetime.strptime(scan_date[:10], '%Y-%m-%d').date()
        today = datetime.now(ZoneInfo(settings.timezone)).date()
        return max(0, (today - start).days)
    except Exception:
        return 0


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _float(value) -> float:
    try:
        if value is None:
            return 0.0
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return 0.0
        return out
    except Exception:
        return 0.0


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return _round(ordered[mid])
    return _round((ordered[mid - 1] + ordered[mid]) / 2.0)


if __name__ == '__main__':
    result = update_recommendation_pnl()
    print(json.dumps(result.get('summary', {}), ensure_ascii=False, indent=2))
