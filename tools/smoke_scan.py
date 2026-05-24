from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scan_once import run_full_scan


def main() -> int:
    payload = run_full_scan(notify=False)
    required = ['created_at_kst', 'mode', 'fx', 'us_long_etfs', 'kr_retirement_etfs', 'retirement_risk_report', 'kr_short_stocks', 'dca_backtest']
    missing = [key for key in required if key not in payload]
    if missing:
        raise AssertionError(f'missing payload keys: {missing}')

    if not isinstance(payload['us_long_etfs'], list):
        raise AssertionError('us_long_etfs must be a list')
    if not isinstance(payload['kr_retirement_etfs'], list):
        raise AssertionError('kr_retirement_etfs must be a list')
    if not isinstance(payload['kr_short_stocks'], list):
        raise AssertionError('kr_short_stocks must be a list')

    print('SMOKE_SCAN_OK')
    print(f"mode={payload.get('mode')}")
    print(f"us_long_etfs={len(payload['us_long_etfs'])}")
    print(f"kr_retirement_etfs={len(payload['kr_retirement_etfs'])}")
    print(f"kr_short_stocks={len(payload['kr_short_stocks'])}")
    if payload['kr_short_stocks']:
        top = payload['kr_short_stocks'][0]
        print(f"top_kr_short={top.get('name')}({top.get('code')}) score={top.get('score')} setup={top.get('strategy_type')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
