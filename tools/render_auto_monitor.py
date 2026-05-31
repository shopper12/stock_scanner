from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request

DEFAULT_API_BASE_URL = 'https://stock-scanner-api-5sk6.onrender.com'
ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'
REPORT_PATH = REPORT_DIR / 'render_auto_monitor_latest.json'


def main() -> int:
    api_base_url = os.getenv('STOCK_SCANNER_API_BASE_URL', DEFAULT_API_BASE_URL).rstrip('/')
    admin_token = os.getenv('ADMIN_TOKEN', '').strip()
    if not admin_token:
        print('ADMIN_TOKEN is required to run server-side scan/backtest.', file=sys.stderr)
        return 2

    max_symbols = _int_env('KR_BACKTEST_MAX_SYMBOLS', 60)
    write_rules = _bool_env('AUTO_EVOLVE_WRITE', True)

    result: dict[str, Any] = {
        'created_at_utc': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        'api_base_url': api_base_url,
        'write_rules': write_rules,
        'max_symbols': max_symbols,
    }

    result['health'] = _api_get(api_base_url, '/health')
    result['scan'] = _api_post(api_base_url, '/api/run-scan', {}, admin_token)
    result['backtest'] = _api_post(api_base_url, '/api/run-backtest', {'max_symbols': max_symbols, 'write': write_rules}, admin_token)
    result['latest'] = _api_get(api_base_url, '/api/latest')
    result['history'] = _api_get(api_base_url, '/api/recommendation-history')
    result['backtest_report'] = _api_get(api_base_url, '/api/kr-backtest')

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    message = _build_message(result)
    print(message)
    _send_telegram_if_configured(message)
    return 0


def _api_get(api_base_url: str, path: str) -> dict[str, Any]:
    req = request.Request(f'{api_base_url}{path}', method='GET', headers={'Accept': 'application/json'})
    return _read_json(req)


def _api_post(api_base_url: str, path: str, payload: dict[str, Any], admin_token: str) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    req = request.Request(
        f'{api_base_url}{path}',
        data=body,
        method='POST',
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json; charset=utf-8',
            'X-Admin-Token': admin_token,
        },
    )
    return _read_json(req)


def _read_json(req: request.Request) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw or '{}')
    except Exception as exc:
        return {'ok': False, 'error': exc.__class__.__name__, 'message': str(exc)}


def _build_message(result: dict[str, Any]) -> str:
    latest = result.get('latest') or {}
    backtest = result.get('backtest') or {}
    rows = latest.get('kr_short_stocks') or []
    top = rows[0] if rows else {}
    best = backtest.get('best_summary') or {}
    base = backtest.get('base_summary') or {}
    lines = [
        '[Stock Scanner 자동 모니터링]',
        f"시각: {latest.get('created_at_kst') or result.get('created_at_utc')}",
        f"KR 후보: {len(rows)}개 / 상위: {top.get('name', '-')}({top.get('code', '-')}) score={top.get('score', '-')}",
        f"진입/손절/목표: {top.get('entry', '-')} / {top.get('stop_loss', '-')} / {top.get('target1', '-')}→{top.get('target2', '-')}",
        f"백테스트: accepted={backtest.get('accepted')} improvement={backtest.get('improvement')}",
        f"기준: trades={base.get('trades', '-')} avg={base.get('avg_return_pct', '-')} win={base.get('win_rate', '-') } PF={base.get('profit_factor', '-')}",
        f"최선: trades={best.get('trades', '-')} avg={best.get('avg_return_pct', '-')} win={best.get('win_rate', '-') } PF={best.get('profit_factor', '-')}",
        f"룰 자동반영: {result.get('write_rules')}",
    ]
    if not result.get('scan', {}).get('ok', False):
        lines.append(f"스캔 오류: {result.get('scan')}")
    if not backtest.get('ok', False):
        lines.append(f"백테스트 오류: {backtest}")
    return '\n'.join(lines)


def _send_telegram_if_configured(message: str) -> None:
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = parse.urlencode({'chat_id': chat_id, 'text': message}).encode('utf-8')
    req = request.Request(url, data=data, method='POST')
    try:
        with request.urlopen(req, timeout=30) as resp:
            print(resp.read().decode('utf-8'))
    except Exception as exc:
        print(f'Telegram send failed: {exc}', file=sys.stderr)


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


if __name__ == '__main__':
    raise SystemExit(main())
