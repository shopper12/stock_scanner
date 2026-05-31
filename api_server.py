from __future__ import annotations

from dataclasses import asdict
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from strategies.kr_short_rules import KrShortRules, load_kr_short_rules, save_kr_short_rules

ROOT_DIR = Path(__file__).resolve().parent
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_PATH = REPORT_DIR / 'latest.json'
QUOTE_QUALITY_PATH = REPORT_DIR / 'quote_quality_latest.json'
RECOMMENDATION_HISTORY_PATH = REPORT_DIR / 'recommendation_history.json'
RECOMMENDATION_PERFORMANCE_PATH = REPORT_DIR / 'recommendation_performance_latest.json'
BACKTEST_REPORT_PATH = REPORT_DIR / 'kr_short_evolution_latest.json'

RULE_DESCRIPTIONS = {
    'score_threshold': '한국 단기 후보 최소 점수. 이 값보다 낮으면 후보에서 제외됩니다.',
    'min_risk_pct': '진입가 대비 최소 손절폭. 너무 작으면 노이즈에 손절될 수 있습니다.',
    'max_risk_pct': '진입가 대비 최대 손절폭. 너무 크면 손실 위험이 커집니다.',
    'max_entry_gap_pct': '현재가 대비 허용 진입가 괴리율. 돌파 진입가가 너무 멀면 제외합니다.',
    'max_gap_ma20_pct': 'MA20 대비 과열 허용 한도. 이보다 멀면 점수 패널티가 붙습니다.',
    'surge_threshold_pct': '전략 검증용 급등 기준 수익률입니다.',
    'surge_lookahead_days': '급등 여부를 확인할 미래 관찰 일수입니다.',
    'hold_days': '단기 전략의 기본 보유 일수입니다.',
    'min_backtest_trades': '규칙 자동개선/검증 시 필요한 최소 거래 수입니다.',
    'min_surge_precision': '급등 포착 전략의 최소 정밀도 기준입니다.',
    'min_avg_return_pct': '전략 채택에 필요한 최소 평균 수익률입니다.',
    'min_profit_factor': '전략 채택에 필요한 최소 profit factor입니다.',
    'min_win_rate': '전략 채택에 필요한 최소 승률입니다.',
    'min_improvement_score': '자동 규칙 개선안 채택을 위한 최소 개선 점수입니다.',
}

EDITABLE_RULE_FIELDS = {
    'score_threshold': float,
    'min_risk_pct': float,
    'max_risk_pct': float,
    'max_entry_gap_pct': float,
    'max_gap_ma20_pct': float,
    'surge_threshold_pct': float,
    'surge_lookahead_days': int,
    'hold_days': int,
    'min_backtest_trades': int,
    'min_surge_precision': float,
    'min_avg_return_pct': float,
    'min_profit_factor': float,
    'min_win_rate': float,
    'min_improvement_score': float,
}

RULE_BOUNDS = {
    'score_threshold': (0.0, 100.0),
    'min_risk_pct': (0.0, 20.0),
    'max_risk_pct': (0.0, 40.0),
    'max_entry_gap_pct': (0.0, 20.0),
    'max_gap_ma20_pct': (0.0, 40.0),
    'surge_threshold_pct': (1.0, 100.0),
    'surge_lookahead_days': (1, 120),
    'hold_days': (1, 60),
    'min_backtest_trades': (1, 500),
    'min_surge_precision': (0.0, 1.0),
    'min_avg_return_pct': (-20.0, 50.0),
    'min_profit_factor': (0.0, 10.0),
    'min_win_rate': (0.0, 1.0),
    'min_improvement_score': (0.0, 10.0),
}


def _read_json(path: Path) -> tuple[int, dict]:
    if not path.exists():
        return 404, {'ok': False, 'error': 'file_not_found', 'path': str(path.relative_to(ROOT_DIR))}
    try:
        return 200, json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return 500, {'ok': False, 'error': 'invalid_json', 'message': str(exc), 'path': str(path.relative_to(ROOT_DIR))}


def _latest_payload() -> tuple[int, dict]:
    status, data = _read_json(LATEST_PATH)
    if status == 200:
        data.setdefault('kr_sector_snapshot', _sector_snapshot_from_latest(data))
    return status, data


def _sector_snapshot_from_latest(data: dict) -> list[dict]:
    rows = data.get('kr_short_stocks') or []
    sectors: dict[str, dict] = {}
    for row in rows:
        sector = str(row.get('sector') or '기타')
        bucket = sectors.setdefault(sector, {
            'sector': sector,
            'selected_count': 0,
            'sector_rank': row.get('sector_rank'),
            'sector_strength_score': row.get('sector_strength_score'),
            'market_rotation_score': 0.0,
            'trade_value_krw': 0.0,
            'avg_change_pct_today': 0.0,
            'top_stock': '',
            'top_stock_code': '',
            'top_score': 0.0,
        })
        bucket['selected_count'] += 1
        bucket['trade_value_krw'] += float(row.get('trade_value_krw') or 0)
        bucket['avg_change_pct_today'] += float(row.get('change_pct_today') or 0)
        bucket['market_rotation_score'] = max(bucket['market_rotation_score'], float(row.get('market_rotation_score') or 0))
        score = float(row.get('score') or 0)
        if score >= float(bucket.get('top_score') or 0):
            bucket['top_score'] = score
            bucket['top_stock'] = row.get('name', '')
            bucket['top_stock_code'] = str(row.get('code', '')).zfill(6)
        rank = row.get('sector_rank')
        if rank is not None and (bucket.get('sector_rank') is None or int(rank) < int(bucket['sector_rank'])):
            bucket['sector_rank'] = rank
        strength = row.get('sector_strength_score')
        if strength is not None and float(strength) > float(bucket.get('sector_strength_score') or 0):
            bucket['sector_strength_score'] = strength
    out = []
    for bucket in sectors.values():
        count = max(int(bucket['selected_count']), 1)
        bucket['avg_change_pct_today'] = round(bucket['avg_change_pct_today'] / count, 2)
        bucket['trade_value_krw'] = round(bucket['trade_value_krw'])
        bucket['market_rotation_score'] = round(bucket['market_rotation_score'], 1)
        bucket['sector_strength_score'] = round(float(bucket.get('sector_strength_score') or 0), 1)
        bucket['top_score'] = round(float(bucket.get('top_score') or 0), 1)
        out.append(bucket)
    return sorted(out, key=lambda x: (x.get('sector_rank') or 999, -x.get('sector_strength_score', 0), -x.get('trade_value_krw', 0)))[:12]


def _rules_payload() -> dict:
    rules = asdict(load_kr_short_rules())
    return {
        'ok': True,
        'rules': rules,
        'editable_fields': list(EDITABLE_RULE_FIELDS.keys()),
        'descriptions_ko': RULE_DESCRIPTIONS,
        'bounds': {key: list(value) for key, value in RULE_BOUNDS.items()},
        'persistence': {
            'runtime_file': str((ROOT_DIR / 'rules' / 'kr_short_rules.json').relative_to(ROOT_DIR)),
            'note': 'Render filesystem changes apply to this running backend. They can be lost on redeploy/restart unless committed or stored externally.',
        },
    }


def _backtest_payload() -> tuple[int, dict]:
    status, data = _read_json(BACKTEST_REPORT_PATH)
    if status == 200:
        data.setdefault('ok', True)
    return status, data


def _performance_payload() -> tuple[int, dict]:
    status, data = _read_json(RECOMMENDATION_PERFORMANCE_PATH)
    if status == 200:
        data.setdefault('ok', True)
    return status, data

def _write_enabled() -> bool:
    return True

def _coerce_rule_value(key: str, raw):
    target_type = EDITABLE_RULE_FIELDS[key]
    value = int(raw) if target_type is int else float(raw)
    lower, upper = RULE_BOUNDS[key]
    if value < lower or value > upper:
        raise ValueError(f'{key}={value} outside allowed range [{lower}, {upper}]')
    return value


def _update_rules(data: dict) -> dict:
    current = asdict(load_kr_short_rules())
    updates = data.get('rules', data)
    if not isinstance(updates, dict):
        raise ValueError('request body must be a JSON object or {"rules": {...}}')
    changed = {}
    for key, raw in updates.items():
        if key not in EDITABLE_RULE_FIELDS:
            continue
        changed[key] = _coerce_rule_value(key, raw)
    if 'min_risk_pct' in changed or 'max_risk_pct' in changed:
        min_risk = float(changed.get('min_risk_pct', current['min_risk_pct']))
        max_risk = float(changed.get('max_risk_pct', current['max_risk_pct']))
        if min_risk > max_risk:
            raise ValueError('min_risk_pct must be <= max_risk_pct')
    if not changed:
        raise ValueError('no editable rule fields supplied')
    current.update(changed)
    current['version'] = int(current.get('version', 1)) + 1
    rules = KrShortRules(**{k: v for k, v in current.items() if k in KrShortRules.__dataclass_fields__})
    save_kr_short_rules(rules)
    return {'ok': True, 'changed': changed, 'rules': asdict(rules)}


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'StockScannerAPI/1.6'

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path in {'/', '/health'}:
            self._send_json(200, {
                'ok': True,
                'service': 'stock_scanner_api',
                'endpoints': ['/api/latest', '/api/quote-quality', '/api/kr-short-rules', '/api/run-scan', '/api/recommendation-history', '/api/recommendation-performance', '/api/update-recommendation-pnl', '/api/kr-sector-snapshot', '/api/kr-backtest', '/api/kr-stock-strategy'],
                'write_enabled': _write_enabled(),
                'latest_report_exists': LATEST_PATH.exists(),
                'quote_quality_report_exists': QUOTE_QUALITY_PATH.exists(),
                'recommendation_history_exists': RECOMMENDATION_HISTORY_PATH.exists(),
                'recommendation_performance_exists': RECOMMENDATION_PERFORMANCE_PATH.exists(),
                'backtest_report_exists': BACKTEST_REPORT_PATH.exists(),
            })
            return
        if path == '/api/latest':
            status, data = _latest_payload()
            self._send_json(status, data)
            return
        if path == '/api/kr-sector-snapshot':
            status, data = _latest_payload()
            if status == 200:
                data = {
                    'ok': True,
                    'created_at_kst': data.get('created_at_kst'),
                    'mode': data.get('mode'),
                    'kr_sector_snapshot': data.get('kr_sector_snapshot', []),
                }
            self._send_json(status, data)
            return
        if path == '/api/quote-quality':
            status, data = _read_json(QUOTE_QUALITY_PATH)
            self._send_json(status, data)
            return
        if path == '/api/kr-short-rules':
            self._send_json(200, _rules_payload())
            return
        if path == '/api/kr-backtest':
            status, data = _backtest_payload()
            self._send_json(status, data)
            return
        if path == '/api/recommendation-history':
            status, data = _read_json(RECOMMENDATION_HISTORY_PATH)
            self._send_json(status, data)
            return
        if path == '/api/recommendation-performance':
            status, data = _performance_payload()
            self._send_json(status, data)
            return
        self._send_json(404, {'ok': False, 'error': 'not_found', 'path': path})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path not in {'/api/kr-short-rules', '/api/run-scan', '/api/run-backtest', '/api/kr-stock-strategy', '/api/update-recommendation-pnl'}:
            self._send_json(404, {'ok': False, 'error': 'not_found', 'path': path})
            return
        if not _write_enabled():
            self._send_json(503, {'ok': False, 'error': 'write_disabled', 'message': 'Set ADMIN_TOKEN on the backend to enable write APIs.'})
            return
        if not _auth_ok(self):
            self._send_json(401, {'ok': False, 'error': 'unauthorized', 'message': 'Missing or invalid X-Admin-Token.'})
            return
        try:
            if path == '/api/kr-short-rules':
                payload = self._read_body_json()
                self._send_json(200, _update_rules(payload))
                return
            if path == '/api/run-scan':
                from scan_once import run_full_scan
                payload = run_full_scan(notify=False, write_report=True)
                self._send_json(200, {
                    'ok': True,
                    'created_at_kst': payload.get('created_at_kst'),
                    'mode': payload.get('mode'),
                    'kr_short_count': len(payload.get('kr_short_stocks', [])),
                    'data_quality': payload.get('data_quality', {}),
                })
                return
            if path == '/api/update-recommendation-pnl':
                from tools.update_recommendation_pnl import update_recommendation_pnl
                result = update_recommendation_pnl()
                self._send_json(200, {'ok': True, **result})
                return
            if path == '/api/run-backtest':
                from backtest.kr_short_evolution import evolve_kr_short_rules
                body = self._read_body_json()
                max_symbols = int(body.get('max_symbols') or os.getenv('KR_BACKTEST_MAX_SYMBOLS', '30'))
                result = evolve_kr_short_rules(write=_bool_value(body.get('write', False)), max_symbols=max_symbols, ai_review=False)
                self._send_json(200, {'ok': True, **result})
                return
            if path == '/api/kr-stock-strategy':
                from strategies.kr_stock_lookup import analyze_kr_stock_strategy
                body = self._read_body_json()
                query = str(body.get('query') or body.get('code') or body.get('name') or '').strip()
                self._send_json(200, analyze_kr_stock_strategy(query))
                return
        except Exception as exc:
            self._send_json(400, {'ok': False, 'error': exc.__class__.__name__, 'message': str(exc)})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _read_body_json(self) -> dict:
        length = int(self.headers.get('Content-Length', '0') or '0')
        raw = self.rfile.read(length).decode('utf-8') if length else '{}'
        return json.loads(raw or '{}')

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self._send_cors_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Admin-Token')

    def log_message(self, fmt: str, *args) -> None:
        print(f'{self.address_string()} - {fmt % args}')


def main() -> None:
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '8000'))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'Stock Scanner API listening on http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    main()
