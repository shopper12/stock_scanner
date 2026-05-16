from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
from config import settings
from database.db import save_payload
from notifier import build_mobile_summary, send_telegram_message
from strategies.fx_conversion import analyze_fx_conversion
from strategies.kr_retirement_etf import scan_kr_retirement_etfs
from strategies.kr_short_stock import scan_kr_short_stocks
from strategies.us_long_etf import scan_us_long_etfs
from backtest.dca import simple_dca_backtest


def run_full_scan(notify: bool = False) -> dict:
    fx = analyze_fx_conversion()
    us = scan_us_long_etfs(fx_signal=fx['action'])
    retirement, risk_report = scan_kr_retirement_etfs()
    kr_short = scan_kr_short_stocks()
    dca = simple_dca_backtest('VOO', settings.us_monthly_budget_krw, months=24)
    payload = {
        'created_at_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'mode': 'mock' if settings.use_mock_data else 'live_or_fallback',
        'fx': fx,
        'us_long_etfs': us.to_dict('records'),
        'kr_retirement_etfs': retirement.to_dict('records'),
        'retirement_risk_report': risk_report,
        'kr_short_stocks': kr_short.to_dict('records'),
        'dca_backtest': dca,
    }
    save_payload('full_scan', payload)
    if notify:
        send_telegram_message(build_mobile_summary(payload))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description='Run stock scanner once.')
    parser.add_argument('--notify', action='store_true', help='Send Telegram summary if configured.')
    args = parser.parse_args()
    payload = run_full_scan(notify=args.notify)
    print(build_mobile_summary(payload))


if __name__ == '__main__':
    main()
