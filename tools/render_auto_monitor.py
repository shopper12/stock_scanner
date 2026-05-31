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
PERFORMANCE_COPY_PATH = REPORT_DIR / 'recommendation_performance_latest.json'


def main() -> int:
    api_base_url = os.getenv('STOCK_SCANNER_API_BASE_URL', DEFAULT_API_BASE_URL).rstrip('/')

    max_symbols = _int_env('KR_BACKTEST_MAX_SYMBOLS', 60)
    write_rules = _bool_env('AUTO_EVOLVE_WRITE', True)

    result: dict[str, Any] = {
        'created_at_utc': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        'api_base_url': api_base_url,
        'write_rules': write_rules,
        'max_symbols': max_symbols,
        'sequence': 'performance_before_scan -> scan -> performance_after_scan -> backtest -> fetch_reports',
    }

    result['health'] = _api_get(api_base_url, '/health')
    result['performance_before_scan'] = _api_post(api_base_url, '/api/update-recommendation-pnl', {})
    result['scan'] = _api_post(api_base_url, '/api/run-scan', {})
    result['performance_after_scan'] = _api_post(api_base_url, '/api/update-recommendation-pnl', {})
    result['backtest'] = _api_post(api_base_url, '/api/run-backtest', {'max_symbols': max_symbols, 'write': write_rules})
    result['latest'] = _api_get(api_base_url, '/api/latest')
    result['history'] = _api_get(api_base_url, '/api/recommendation-history')
    result['performance'] = _api_get(api_base_url, '/api/recommendation-performance')
    result['backtest_report'] = _api_get(api_base_url, '/api/kr-backtest')

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    if result.get('performance', {}).get('ok'):
        PERFORMANCE_COPY_PATH.write_text(json.dumps(result['performance'], ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    message = _build_message(result)
    print(message)
    _send_telegram_if_configured(message)
    return 0


def _api_get(api_base_url: str, path: str) -> dict[str, Any]:
    req = request.Request(f'{api_base_url}{path}', method='GET', headers={'Accept': 'application/json'})
    return _read_json(req)


def _api_post(api_base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode('utf-8')
    req = request.Request(
        f'{api_base_url}{path}',
        data=body,
        method='POST',
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json; charset=utf-8',
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
    performance = result.get('performance') or {}
    perf_summary = performance.get('summary') or {}
    rows = latest.get('kr_short_stocks') or []
    top = rows[0] if rows else {}
    best = backtest.get('best_summary') or {}
    base = backtest.get('base_summary') or {}
    by_strategy = perf_summary.get('by_strategy_type') or {}
    best_setup, worst_setup = _best_worst_setup(by_strategy)
    lines = [
        '[Stock Scanner 자동 모니터링]',
        f"시각: {latest.get('created_at_kst') or result.get('created_at_utc')}",
        f"KR 후보: {len(rows)}개 / 상위: {top.get('name', '-')}({top.get('code', '-')}) score={top.get('score', '-')}",
        f"진입/손절/목표: {top.get('entry', '-')} / {top.get('stop_loss', '-')} / {top.get('target1', '-')}→{top.get('target2', '-')}",
        f"추천성과: 평균 {perf_summary.get('avg_pnl_pct', '-')}% / 승률 {_pct(perf_summary.get('win_rate'))} / 손절 {_pct(perf_summary.get('hit_stop_rate'))} / 목표1 {_pct(perf_summary.get('hit_target1_rate'))} / 목표2 {_pct(perf_summary.get('hit_target2_rate'))}",
        f"setup 성과: 최고 {best_setup} / 최악 {worst_setup}",
        f"백테스트: accepted={backtest.get('accepted')} improvement={backtest.get('improvement')}",
        f"기준: trades={base.get('trades', '-')} avg={base.get('avg_return_pct', '-')} win={base.get('win_rate', '-') } PF={base.get('profit_factor', '-')}",
        f"최선: trades={best.get('trades', '-')} avg={best.get('avg_return_pct', '-')} win={best.get('win_rate', '-') } PF={best.get('profit_factor', '-')}",
        f"룰 자동반영: {result.get('write_rules')}",
    ]
    for key, label in [('performance_before_scan', '성과갱신(전)'), ('scan', '스캔'), ('performance_after_scan', '성과갱신(후)'), ('backtest', '백테스트')]:
        if not result.get(key, {}).get('ok', False):
            lines.append(f"{label} 오류: {result.get(key)}")
    return '\n'.join(lines)


def _best_worst_setup(by_strategy: dict[str, Any]) -> tuple[str, str]:
    rows = []
    for name, data in by_strategy.items():
        if not isinstance(data, dict):
            continue
        rows.append((name, float(data.get('avg_pnl_pct') or 0.0), int(data.get('measurable_count') or data.get('count') or 0)))
    rows = [row for row in rows if row[2] > 0]
    if not rows:
        return '-', '-'
    best = max(rows, key=lambda x: x[1])
    worst = min(rows, key=lambda x: x[1])
    return f'{best[0]} {best[1]:+.2f}%', f'{worst[0]} {worst[1]:+.2f}%'


def _pct(value) -> str:
    try:
        return f'{float(value) * 100:.1f}%'
    except Exception:
        return '-'


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
