from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.dca import simple_dca_backtest
from config import settings
from database.db import save_payload
from strategies.fx_conversion import analyze_fx_conversion
from strategies.kr_retirement_etf import scan_kr_retirement_etfs
from strategies.kr_short_stock_pure_runtime import scan_kr_short_stocks
from strategies.us_long_etf import scan_us_long_etfs

ROOT_DIR = Path(__file__).resolve().parent
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_REPORT_PATH = REPORT_DIR / 'latest.json'
HISTORY_REPORT_PATH = REPORT_DIR / 'recommendation_history.json'


def run_full_scan(notify: bool = False, write_report: bool = True) -> dict:
    fx = analyze_fx_conversion()
    us = scan_us_long_etfs(fx_signal=fx['action'])
    retirement, risk_report = scan_kr_retirement_etfs()
    kr_short = scan_kr_short_stocks()
    dca = simple_dca_backtest('VOO', settings.us_monthly_budget_krw, months=24)
    created_at = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
    kr_short_rows = kr_short.to_dict('records')
    payload = {
        'schema_version': 1,
        'created_at_kst': created_at,
        'mode': 'mock' if settings.use_mock_data else 'live',
        'data_quality': _data_quality(kr_short_rows),
        'fx': fx,
        'us_long_etfs': us.to_dict('records'),
        'kr_retirement_etfs': retirement.to_dict('records'),
        'retirement_risk_report': risk_report,
        'kr_short_stocks': kr_short_rows,
        'dca_backtest': dca,
    }
    save_payload('full_scan', payload)
    if write_report:
        write_latest_report(payload)
        update_recommendation_history(created_at, kr_short_rows)
    if notify:
        _send_scan_notification(payload)
    return payload


def write_latest_report(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def update_recommendation_history(created_at_kst: str, kr_short_rows: list[dict]) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    current = _read_history()
    items = current.get('items', [])
    by_key = {_history_key(item): item for item in items if _history_key(item)}
    scan_date = created_at_kst.split(' ')[0] if created_at_kst else 'unknown'
    for row in kr_short_rows:
        code = str(row.get('code', '')).zfill(6)
        if not code:
            continue
        entry = float(row.get('entry') or row.get('current_price') or 0)
        current_price = float(row.get('current_price') or 0)
        key = f'{scan_date}:{code}'
        by_key[key] = {
            'scan_date': scan_date,
            'recommended_at_kst': created_at_kst,
            'code': code,
            'name': row.get('name', ''),
            'sector': row.get('sector', '기타'),
            'strategy_type': row.get('strategy_type', ''),
            'entry': round(entry),
            'stop_loss': row.get('stop_loss'),
            'target1': row.get('target1'),
            'target2': row.get('target2'),
            'score_at_recommendation': row.get('score'),
            'price_at_recommendation': round(current_price),
            'latest_price': round(current_price),
            'latest_price_basis': row.get('price_basis'),
            'latest_price_timestamp': row.get('price_timestamp'),
            'pnl_pct': round((current_price / entry - 1.0) * 100, 2) if entry > 0 and current_price > 0 else None,
            'pnl_krw_per_share': round(current_price - entry) if entry > 0 and current_price > 0 else None,
            'reason': row.get('reason', ''),
            'failure_condition': row.get('failure_condition', ''),
        }
        _save_recommendation_for_tracking(scan_date, row, code)
    merged = sorted(by_key.values(), key=lambda x: (x.get('scan_date', ''), x.get('score_at_recommendation') or 0), reverse=True)
    out = {
        'schema_version': 1,
        'updated_at_kst': created_at_kst,
        'items': merged[:300],
    }
    HISTORY_REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return out


def _send_scan_notification(payload: dict) -> None:
    try:
        from notifier import build_mobile_summary, send_telegram_message
        send_telegram_message(build_mobile_summary(payload))
    except Exception as exc:
        print(f'[scan_once] telegram notification skipped: {exc}')


def _save_recommendation_for_tracking(scan_date: str, row: dict, code: str) -> None:
    try:
        from database.recommendation_tracker import save_recommendation
        save_recommendation({
            'scan_date': scan_date,
            'code': code,
            'name': row.get('name', ''),
            'sector': row.get('sector', '기타'),
            'setup': row.get('strategy_type', ''),
            'score': row.get('score'),
            'entry_price': float(row.get('entry') or 0),
            'stop_price': float(row.get('stop_loss') or 0),
            'target1': float(row.get('target1') or 0),
            'target2': float(row.get('target2') or 0),
            'hold_days': 10,
            'snapshot': row,
        })
    except Exception as exc:
        print(f'[scan_once] recommendation tracker save skipped: {exc}')


def _read_history() -> dict:
    if not HISTORY_REPORT_PATH.exists():
        return {'schema_version': 1, 'items': []}
    try:
        return json.loads(HISTORY_REPORT_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'schema_version': 1, 'items': []}


def _history_key(item: dict) -> str:
    scan_date = item.get('scan_date')
    code = item.get('code')
    if not scan_date or not code:
        return ''
    return f'{scan_date}:{str(code).zfill(6)}'


def _data_quality(kr_short_rows: list[dict]) -> dict:
    total = len(kr_short_rows)
    quote_ok = sum(1 for row in kr_short_rows if row.get('quote_ok'))
    realtime = sum(1 for row in kr_short_rows if row.get('price_basis') == 'realtime_quote')
    return {
        'kr_short_total': total,
        'kr_short_quote_ok': quote_ok,
        'kr_short_quote_ok_rate': round(quote_ok / total, 4) if total else 0.0,
        'kr_short_realtime_price_count': realtime,
        'kr_short_daily_close_fallback_count': total - realtime,
    }


def _mobile_summary(payload: dict) -> str:
    rows = payload.get('kr_short_stocks', [])
    top = rows[0] if rows else {}
    return '\n'.join([
        f"created_at={payload.get('created_at_kst')}",
        f"mode={payload.get('mode')}",
        f"kr_short_count={len(rows)}",
        f"top={top.get('name', '-') }({top.get('code', '-')}) score={top.get('score', '-')}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description='Run stock scanner once.')
    parser.add_argument('--notify', action='store_true', help='Send Telegram summary when configured.')
    parser.add_argument('--no-report', action='store_true', help='Do not write reports/latest.json.')
    args = parser.parse_args()
    payload = run_full_scan(notify=args.notify, write_report=not args.no_report)
    print(_mobile_summary(payload))
    print(f"latest_report={LATEST_REPORT_PATH}")
    print(f"history_report={HISTORY_REPORT_PATH}")


if __name__ == '__main__':
    main()
