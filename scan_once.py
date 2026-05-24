from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import json

from config import settings
from database.db import save_payload
from notifier import build_mobile_summary, send_telegram_message
from strategies.fx_conversion import analyze_fx_conversion
from strategies.kr_retirement_etf import scan_kr_retirement_etfs
from strategies.kr_short_stock import scan_kr_short_stocks
from strategies.us_long_etf import scan_us_long_etfs
from backtest.dca import simple_dca_backtest

ROOT_DIR = Path(__file__).resolve().parent
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_REPORT_PATH = REPORT_DIR / 'latest.json'


def run_full_scan(notify: bool = False, write_report: bool = True) -> dict:
    fx = analyze_fx_conversion()
    us = scan_us_long_etfs(fx_signal=fx['action'])
    retirement, risk_report = scan_kr_retirement_etfs()
    kr_short = scan_kr_short_stocks()
    dca = simple_dca_backtest('VOO', settings.us_monthly_budget_krw, months=24)
    payload = {
        'schema_version': 1,
        'created_at_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'mode': 'mock' if settings.use_mock_data else 'live',
        'data_quality': _data_quality(kr_short.to_dict('records')),
        'fx': fx,
        'us_long_etfs': us.to_dict('records'),
        'kr_retirement_etfs': retirement.to_dict('records'),
        'retirement_risk_report': risk_report,
        'kr_short_stocks': kr_short.to_dict('records'),
        'dca_backtest': dca,
    }
    save_payload('full_scan', payload)
    if write_report:
        write_latest_report(payload)
    if notify:
        send_telegram_message(build_mobile_summary(payload))
    return payload


def write_latest_report(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


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


def main() -> None:
    parser = argparse.ArgumentParser(description='Run stock scanner once.')
    parser.add_argument('--notify', action='store_true', help='Send Telegram summary if configured.')
    parser.add_argument('--no-report', action='store_true', help='Do not write reports/latest.json.')
    args = parser.parse_args()
    payload = run_full_scan(notify=args.notify, write_report=not args.no_report)
    print(build_mobile_summary(payload))
    print(f"latest_report={LATEST_REPORT_PATH}")


if __name__ == '__main__':
    main()
