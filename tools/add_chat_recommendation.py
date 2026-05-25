from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT_DIR / 'reports' / 'conversation_trade_history.json'
TIMEZONE = os.getenv('TIMEZONE', 'Asia/Seoul')

COLUMNS = [
    'id', 'date', 'session', 'asset_type', 'ticker', 'name', 'currency',
    'entry_low', 'entry_high', 'entry_mid', 'stop_loss', 'target1', 'target2',
    'current_price', 'current_price_time', 'current_price_source',
    'pnl_vs_entry_mid_pct', 'distance_to_target1_pct', 'distance_to_stop_pct',
    'status', 'source_status', 'memo',
]


def _now_kst() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime('%Y-%m-%d %H:%M:%S %Z')


def _today() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime('%Y-%m-%d')


def _num(value: Any) -> float | None:
    if value in (None, ''):
        return None
    return float(str(value).replace(',', '').strip())


def _read() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        payload = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))
        return list(payload.get('items', []))
    except Exception:
        return []


def _write(items: list[dict[str, Any]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {'schema_version': 1, 'updated_at_kst': _now_kst(), 'items': items}
    HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    row = {col: raw.get(col) for col in COLUMNS}
    row['date'] = row.get('date') or _today()
    row['session'] = row.get('session') or 'chat'
    row['asset_type'] = row.get('asset_type') or 'unknown'
    row['ticker'] = str(row.get('ticker') or '').strip().upper()
    row['name'] = row.get('name') or row['ticker']
    row['currency'] = row.get('currency') or ('KRW' if row['asset_type'] in {'kr_stock', 'kr_etf'} else 'USD')
    row['entry_low'] = _num(row.get('entry_low'))
    row['entry_high'] = _num(row.get('entry_high'))
    row['stop_loss'] = _num(row.get('stop_loss'))
    row['target1'] = _num(row.get('target1'))
    row['target2'] = _num(row.get('target2'))
    row['current_price'] = _num(row.get('current_price'))
    if row.get('entry_mid') in (None, ''):
        if row['entry_low'] is not None and row['entry_high'] is not None:
            row['entry_mid'] = round((row['entry_low'] + row['entry_high']) / 2, 6)
        else:
            row['entry_mid'] = _num(row.get('entry_low'))
    else:
        row['entry_mid'] = _num(row.get('entry_mid'))
    row['source_status'] = row.get('source_status') or 'conversation_recommended'
    row['status'] = row.get('status') or 'open'
    row['memo'] = row.get('memo') or 'added_from_chat'
    row['current_price_time'] = row.get('current_price_time') or None
    row['current_price_source'] = row.get('current_price_source') or None
    if not row['ticker']:
        raise ValueError('ticker is required')
    if not row.get('id'):
        ticker_part = row['ticker'].replace('.', '').replace('-', '')
        row['id'] = f"{row['date']}-{row['session']}-{ticker_part}"
    return _recalc(row)


def _recalc(row: dict[str, Any]) -> dict[str, Any]:
    price = _num(row.get('current_price'))
    entry = _num(row.get('entry_mid'))
    target = _num(row.get('target1'))
    stop = _num(row.get('stop_loss'))
    if price and entry:
        row['pnl_vs_entry_mid_pct'] = round((price / entry - 1.0) * 100, 2)
    if price and target:
        row['distance_to_target1_pct'] = round((target / price - 1.0) * 100, 2)
    if price and stop:
        row['distance_to_stop_pct'] = round((price / stop - 1.0) * 100, 2)
    if price and target and price >= target:
        row['status'] = 'target1_hit'
    elif price and stop and price <= stop:
        row['status'] = 'stop_hit'
    return row


def _payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload_env:
        return json.loads(os.environ[args.payload_env])
    if args.payload_file:
        return json.loads(Path(args.payload_file).read_text(encoding='utf-8'))
    if args.payload:
        return json.loads(args.payload)
    return {k: v for k, v in vars(args).items() if k not in {'payload', 'payload_file', 'payload_env', 'git_push'} and v is not None}


def _git_push(message: str) -> None:
    subprocess.run(['git', 'add', str(HISTORY_PATH.relative_to(ROOT_DIR))], cwd=ROOT_DIR, check=True)
    diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT_DIR)
    if diff.returncode == 0:
        print('no_changes')
        return
    subprocess.run(['git', 'commit', '-m', message], cwd=ROOT_DIR, check=True)
    subprocess.run(['git', 'push'], cwd=ROOT_DIR, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description='Append a ChatGPT conversation trade recommendation to reports/conversation_trade_history.json')
    parser.add_argument('--payload', help='JSON object string')
    parser.add_argument('--payload-file')
    parser.add_argument('--payload-env')
    parser.add_argument('--git-push', action='store_true')
    parser.add_argument('--id')
    parser.add_argument('--date')
    parser.add_argument('--session')
    parser.add_argument('--asset-type', dest='asset_type')
    parser.add_argument('--ticker')
    parser.add_argument('--name')
    parser.add_argument('--currency')
    parser.add_argument('--entry-low', dest='entry_low')
    parser.add_argument('--entry-high', dest='entry_high')
    parser.add_argument('--entry-mid', dest='entry_mid')
    parser.add_argument('--stop-loss', dest='stop_loss')
    parser.add_argument('--target1')
    parser.add_argument('--target2')
    parser.add_argument('--current-price', dest='current_price')
    parser.add_argument('--source-status', dest='source_status')
    parser.add_argument('--memo')
    args = parser.parse_args()

    row = _normalise(_payload_from_args(args))
    items = _read()
    items = [x for x in items if x.get('id') != row['id']]
    items.insert(0, row)
    _write(items)
    print(json.dumps(row, ensure_ascii=False, indent=2, default=str))
    if args.git_push:
        _git_push(f"Add chat recommendation {row['ticker']}")


if __name__ == '__main__':
    main()
