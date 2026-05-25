from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.kr_short_evolution import run_kr_short_backtest
from data.market_data import get_kr_sector_snapshot
from scan_once import run_full_scan
from strategies.kr_short_rules import load_kr_short_rules

REPORT_DIR = ROOT_DIR / 'reports'
QUOTE_REPORT_PATH = REPORT_DIR / 'quote_quality_latest.json'


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

    sector_snapshot = payload.get('kr_sector_snapshot') or get_kr_sector_snapshot()
    quote_report = _build_quote_report(payload, sector_snapshot)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    QUOTE_REPORT_PATH.write_text(json.dumps(quote_report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    rules = load_kr_short_rules()
    backtest = run_kr_short_backtest(rules=rules, max_symbols=3)
    if 'trades' not in backtest or 'avg_return_pct' not in backtest:
        raise AssertionError('backtest summary missing required keys')

    print('SMOKE_SCAN_OK')
    print(f"mode={payload.get('mode')}")
    print(f"us_long_etfs={len(payload['us_long_etfs'])}")
    print(f"kr_retirement_etfs={len(payload['kr_retirement_etfs'])}")
    print(f"kr_short_stocks={len(payload['kr_short_stocks'])}")
    print(f"sector_snapshot={len(sector_snapshot)}")
    print(f"quote_checked={quote_report['total']}")
    print(f"quote_ok={quote_report['quote_ok']}")
    print(f"quote_ok_rate={quote_report['quote_ok_rate']}")
    print(f"backtest_trades={backtest.get('trades')}")
    print(f"backtest_avg_return_pct={backtest.get('avg_return_pct')}")
    if sector_snapshot:
        top_sector = sector_snapshot[0]
        print(f"top_sector={top_sector.get('sector')} rank={top_sector.get('sector_rank')} strength={top_sector.get('sector_strength_score')}")
    if payload['kr_short_stocks']:
        top = payload['kr_short_stocks'][0]
        print(f"top_kr_short={top.get('name')}({top.get('code')}) score={top.get('score')} setup={top.get('strategy_type')}")
        print(f"top_sector_rank={top.get('sector_rank')} sector_strength={top.get('sector_strength_score')} rotation={top.get('market_rotation_score')}")
        print(f"top_price_basis={top.get('price_basis')} source={top.get('quote_source') or top.get('data_source')} ts={top.get('price_timestamp')}")
    return 0


def _build_quote_report(payload: dict, sector_snapshot: list[dict] | None = None) -> dict:
    rows = payload.get('kr_short_stocks', []) or []
    total = len(rows)
    ok = sum(1 for x in rows if x.get('quote_ok'))
    by_source: dict[str, int] = {}
    by_basis: dict[str, int] = {}
    failures = []
    for x in rows:
        source = str(x.get('quote_source') or x.get('data_source') or 'unknown')
        basis = str(x.get('price_basis') or 'unknown')
        by_source[source] = by_source.get(source, 0) + 1
        by_basis[basis] = by_basis.get(basis, 0) + 1
        if not x.get('quote_ok'):
            failures.append({
                'code': x.get('code'),
                'name': x.get('name'),
                'error': x.get('quote_error'),
                'fallback_basis': basis,
            })
    return {
        'created_at_kst': payload.get('created_at_kst'),
        'mode': payload.get('mode'),
        'total': total,
        'quote_ok': ok,
        'quote_failed': total - ok,
        'quote_ok_rate': round(ok / total, 4) if total else 0.0,
        'by_source': by_source,
        'by_price_basis': by_basis,
        'sector_snapshot_count': len(sector_snapshot or []),
        'top_sectors': (sector_snapshot or [])[:10],
        'failures': failures[:20],
    }


if __name__ == '__main__':
    raise SystemExit(main())
