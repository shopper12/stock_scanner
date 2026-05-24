from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_PATH = REPORT_DIR / 'latest.json'
QUOTE_QUALITY_PATH = REPORT_DIR / 'quote_quality_latest.json'


def _read_json(path: Path) -> tuple[int, dict]:
    if not path.exists():
        return 404, {
            'ok': False,
            'error': 'file_not_found',
            'path': str(path.relative_to(ROOT_DIR)),
        }
    try:
        return 200, json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return 500, {
            'ok': False,
            'error': 'invalid_json',
            'message': str(exc),
            'path': str(path.relative_to(ROOT_DIR)),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = 'StockScannerAPI/1.0'

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path in {'/', '/health'}:
            self._send_json(200, {
                'ok': True,
                'service': 'stock_scanner_api',
                'endpoints': ['/api/latest', '/api/quote-quality'],
            })
            return
        if path == '/api/latest':
            status, data = _read_json(LATEST_PATH)
            self._send_json(status, data)
            return
        if path == '/api/quote-quality':
            status, data = _read_json(QUOTE_QUALITY_PATH)
            self._send_json(status, data)
            return
        self._send_json(404, {'ok': False, 'error': 'not_found', 'path': path})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

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
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

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
