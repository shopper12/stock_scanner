from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlparse


def _display_code(value: Any) -> str:
    text = str(value or '').strip().upper()
    if not text:
        return '-'
    return text.zfill(6) if text.isdigit() else text


def _read_chat_history(api_module: Any, auto_sync: bool = True) -> tuple[int, dict]:
    sync_result = {'ok': True, 'saved': 0, 'source': 'not_run'}
    if auto_sync:
        try:
            from sync_bridge import sync_cards_from_env
            sync_result = sync_cards_from_env()
        except Exception as exc:
            sync_result = {'ok': False, 'error': exc.__class__.__name__, 'message': str(exc)}
    status, data = api_module._read_json(api_module.CHAT_RECOMMENDATION_HISTORY_PATH)
    if status == 200:
        data.setdefault('ok', True)
        data['auto_sync'] = sync_result
    elif sync_result.get('ok') is False:
        data = {'ok': False, 'error': 'chat_history_missing_and_sync_failed', 'auto_sync': sync_result}
        status = 503
    return status, data


def _global_cards_from_latest(api_module: Any) -> tuple[str | None, list[dict]]:
    status, data = api_module._read_json(api_module.LATEST_PATH)
    if status != 200 or not isinstance(data, dict):
        return None, []
    created_at = data.get('created_at_kst')
    rows = data.get('global_signal_watch') or []
    if not isinstance(rows, list):
        return created_at, []
    out = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        ticker = row.get('ticker') or row.get('code') or row.get('symbol')
        name = row.get('name') or ticker
        risk_parts = []
        if row.get('risk_pct') not in (None, ''):
            risk_parts.append(f"risk_pct={row.get('risk_pct')}%")
        if row.get('rsi14') not in (None, ''):
            risk_parts.append(f"RSI={row.get('rsi14')}")
        if row.get('volume_ratio_20d') not in (None, ''):
            risk_parts.append(f"volume={row.get('volume_ratio_20d')}x")
        if row.get('failure_condition'):
            risk_parts.append(str(row.get('failure_condition')))
        out.append({
            'source': 'global_signal_watch',
            'source_note': 'Global US/KR/commodity condition watch',
            'source_id': f"global:{ticker}:{row.get('timestamp_kst') or created_at or ''}",
            'code': ticker,
            'ticker': ticker,
            'name': name,
            'asset_name': name,
            'market': row.get('market') or row.get('asset_class') or 'GLOBAL',
            'sector': row.get('asset_class') or row.get('market') or 'GLOBAL',
            'direction': row.get('direction') or row.get('action') or 'LONG',
            'strategy_type': row.get('strategy_type') or 'global_signal_watch',
            'score': row.get('score'),
            'basis_price': row.get('current_price'),
            'current_price': row.get('current_price'),
            'basis_timestamp_kst': row.get('timestamp_kst') or created_at,
            'recommended_at_kst': row.get('timestamp_kst') or created_at,
            'entry': row.get('entry'),
            'stop_loss': row.get('stop_loss') or row.get('stop'),
            'target1': row.get('target1'),
            'target2': row.get('target2'),
            'reason': row.get('reason') or row.get('rationale') or '',
            'rationale': row.get('reason') or row.get('rationale') or '',
            'risk': ' / '.join(risk_parts),
            'failure_condition': row.get('failure_condition') or '',
        })
    return created_at, out


def _read_app_cards(api_module: Any, auto_sync: bool = True) -> tuple[int, dict]:
    chat_status, chat_data = _read_chat_history(api_module, auto_sync=auto_sync)
    chat_rows = chat_data.get('items') if chat_status == 200 and isinstance(chat_data, dict) else []
    if not isinstance(chat_rows, list):
        chat_rows = []
    latest_updated, global_rows = _global_cards_from_latest(api_module)
    updated = latest_updated or (chat_data.get('updated_at_kst') if isinstance(chat_data, dict) else None)
    return 200, {
        'ok': True,
        'updated_at_kst': updated,
        'global_signal_count': len(global_rows),
        'chatgpt_recommendation_count': len(chat_rows),
        'items': [*global_rows, *chat_rows][:40],
        'recommendations': [*global_rows, *chat_rows][:40],
        'global_signal_watch': global_rows,
        'chatgpt_recommendations': chat_rows[:20],
        'auto_sync': chat_data.get('auto_sync') if isinstance(chat_data, dict) else None,
    }


def _attach_chat_history(api_module: Any, payload: dict) -> dict:
    status, data = _read_chat_history(api_module, auto_sync=True)
    rows = data.get('items') if status == 200 else []
    count = len(rows) if isinstance(rows, list) else 0
    latest_updated, global_rows = _global_cards_from_latest(api_module)
    payload = dict(payload)
    payload['chatgpt_recommendations'] = rows[:20] if isinstance(rows, list) else []
    payload['chatgpt_recommendation_count'] = count
    payload['chatgpt_recommendations_updated_at_kst'] = data.get('updated_at_kst') if isinstance(data, dict) else None
    payload['global_signal_watch_cards'] = global_rows
    payload['global_signal_count'] = len(global_rows)
    payload['global_signal_updated_at_kst'] = latest_updated
    payload['chatgpt_recommendations_endpoint'] = '/api/chatgpt-picks'
    payload['chatgpt_recommendations_page'] = '/recommendations'
    payload['chatgpt_recommendations_aliases'] = ['/api/recommendations', '/api/chatgpt/recommendations']
    payload['chatgpt_recommendations_alert'] = {
        'active': count > 0 or len(global_rows) > 0,
        'title': '앱 추천종목',
        'message': f'글로벌 조건 {len(global_rows)}개 / 브리핑 추천 {count}개',
        'updated_at_kst': latest_updated or payload.get('chatgpt_recommendations_updated_at_kst'),
        'page': '/recommendations',
    }
    return payload


def _save_chat_payload(data: dict) -> dict:
    from sync_bridge import write_cards_to_history
    result = write_cards_to_history(data)
    return {
        'ok': True,
        'saved_count': result.get('saved', 0),
        'items': result.get('items', [])[:20],
        'page': '/recommendations',
    }


def _send_html(handler: Any, status: int, body: str) -> None:
    raw = body.encode('utf-8')
    handler.send_response(status)
    handler._send_cors_headers()
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Content-Length', str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _fmt(value: Any) -> str:
    if value is None or value == '':
        return '-'
    return html.escape(str(value))


def _recommendations_html(data: dict) -> str:
    rows = data.get('items') or []
    updated = _fmt(data.get('updated_at_kst') or '-')
    cards = []
    for row in rows[:40]:
        name = _fmt(row.get('name') or row.get('asset_name') or '-')
        code = _fmt(_display_code(row.get('code') or row.get('ticker')))
        strategy = _fmt(row.get('strategy_type') or row.get('direction') or '-')
        market = _fmt(row.get('market') or '-')
        entry = _fmt(row.get('entry') or row.get('entry_price'))
        stop = _fmt(row.get('stop_loss') or row.get('stop'))
        target1 = _fmt(row.get('target1'))
        target2 = _fmt(row.get('target2'))
        reason = _fmt(row.get('reason') or row.get('rationale') or '')
        risk = _fmt(row.get('risk') or row.get('failure_condition') or '')
        source = _fmt(row.get('source') or row.get('source_note') or '')
        cards.append(f'''
        <article class="card">
          <div class="badge">{market} · {strategy} · {source}</div>
          <h2>{name} <span>{code}</span></h2>
          <div class="grid">
            <div><b>진입</b><p>{entry}</p></div>
            <div><b>손절</b><p>{stop}</p></div>
            <div><b>목표1</b><p>{target1}</p></div>
            <div><b>목표2</b><p>{target2}</p></div>
          </div>
          <p class="reason"><b>근거</b><br>{reason}</p>
          <p class="risk"><b>리스크</b><br>{risk}</p>
        </article>
        ''')
    empty = '<section class="empty">표시할 앱 추천종목이 없습니다.</section>' if not cards else ''
    return f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>앱 추천종목</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:#0f1115; color:#f3f4f6; }}
    header {{ padding:20px 16px 8px; position:sticky; top:0; background:#0f1115; border-bottom:1px solid #242833; }}
    h1 {{ font-size:22px; margin:0 0 6px; }}
    .meta {{ color:#9ca3af; font-size:13px; }}
    main {{ padding:14px; max-width:920px; margin:0 auto; }}
    .card {{ background:#171a21; border:1px solid #2a2f3a; border-radius:14px; padding:15px; margin:12px 0; }}
    .badge {{ display:inline-block; font-size:12px; color:#cbd5e1; background:#273142; padding:4px 8px; border-radius:999px; margin-bottom:8px; }}
    h2 {{ font-size:18px; margin:4px 0 12px; }}
    h2 span {{ color:#93c5fd; font-size:14px; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
    .grid div {{ background:#10131a; border-radius:10px; padding:10px; }}
    b {{ color:#d1d5db; }}
    p {{ margin:6px 0; line-height:1.45; }}
    .reason, .risk {{ color:#d1d5db; font-size:14px; }}
    .empty {{ padding:30px 16px; color:#9ca3af; text-align:center; }}
    a {{ color:#93c5fd; }}
  </style>
</head>
<body>
  <header>
    <h1>앱 추천종목</h1>
    <div class="meta">업데이트: {updated} · <a href="/api/recommendations">JSON 보기</a></div>
  </header>
  <main>{empty}{''.join(cards)}</main>
</body>
</html>'''


def apply(api_module: Any) -> Any:
    if getattr(api_module, '_chat_cards_patch_applied', False):
        return api_module
    api_module._chat_cards_patch_applied = True

    original_latest_payload = api_module._latest_payload
    original_do_get = api_module.Handler.do_GET
    original_do_post = api_module.Handler.do_POST

    def patched_latest_payload(auto_bootstrap: bool = True):
        status, data = original_latest_payload(auto_bootstrap=auto_bootstrap)
        if status == 200 and isinstance(data, dict):
            data = _attach_chat_history(api_module, data)
        return status, data

    def patched_chatgpt_picks_payload(data: dict) -> dict:
        return _save_chat_payload(data)

    def patched_format_pick_lines(row: dict) -> list[str]:
        name = row.get('name') or row.get('asset_name') or '-'
        code = _display_code(row.get('code') or row.get('ticker'))
        score = row.get('score') or row.get('score_at_recommendation') or '-'
        entry = row.get('entry') or row.get('entry_price') or '-'
        stop = row.get('stop_loss') or row.get('stop_price') or row.get('stop') or '-'
        target1 = row.get('target1') or '-'
        target2 = row.get('target2') or '-'
        reason = row.get('reason') or row.get('rationale') or ''
        return [
            f"{name}({code}) score={score}",
            f"진입 {entry} / 손절 {stop} / 목표 {target1}→{target2}",
            f"근거: {str(reason)[:80]}",
            '',
        ]

    def patched_do_get(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        if path in {'/recommendations', '/chatgpt-recommendations', '/app-recommendations'}:
            status, data = _read_app_cards(api_module, auto_sync=True)
            _send_html(self, status, _recommendations_html(data if isinstance(data, dict) else {}))
            return
        if path in {'/api/recommendations', '/api/chatgpt/recommendations'}:
            status, data = _read_app_cards(api_module, auto_sync=True)
            self._send_json(status, data)
            return
        if path == '/api/chatgpt-picks':
            status, data = _read_chat_history(api_module, auto_sync=True)
            self._send_json(status, data)
            return
        if path in {'/', '/health'}:
            status, data = api_module._latest_payload(auto_bootstrap=False)
            chat_count = 0
            global_count = 0
            updated = None
            if status == 200:
                chat_count = int(data.get('chatgpt_recommendation_count') or 0)
                global_count = int(data.get('global_signal_count') or 0)
                updated = data.get('global_signal_updated_at_kst') or data.get('chatgpt_recommendations_updated_at_kst')
            self._send_json(200, {
                'ok': True,
                'service': 'stock_scanner_api',
                'version': 'app-cards-global-v1',
                'endpoints': [
                    '/recommendations',
                    '/api/latest',
                    '/api/recommendations',
                    '/api/chatgpt/recommendations',
                    '/api/chatgpt-picks',
                    '/api/recommendation-history',
                    '/api/recommendation-performance',
                    '/api/run-scan',
                    '/api/kr-stock-strategy',
                    '/api/kr-stock-chart',
                    '/api/kakao-skill',
                ],
                'global_signal_count': global_count,
                'chatgpt_recommendation_count': chat_count,
                'recommendations_updated_at_kst': updated,
                'recommendations_endpoint': '/api/recommendations',
                'recommendations_page': '/recommendations',
                'write_enabled': api_module._write_enabled(),
                'latest_report_exists': api_module.LATEST_PATH.exists(),
                'recommendation_history_exists': api_module.RECOMMENDATION_HISTORY_PATH.exists(),
                'chat_recommendation_history_exists': api_module.CHAT_RECOMMENDATION_HISTORY_PATH.exists(),
            })
            return
        return original_do_get(self)

    def patched_do_post(self):
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path in {'/api/recommendations', '/api/chatgpt/recommendations', '/api/chatgpt-picks'}:
            try:
                body = self._read_body_json()
                self._send_json(200, _save_chat_payload(body))
            except Exception as exc:
                self._send_json(400, {'ok': False, 'error': exc.__class__.__name__, 'message': str(exc)})
            return
        return original_do_post(self)

    api_module._latest_payload = patched_latest_payload
    api_module._chatgpt_picks_payload = patched_chatgpt_picks_payload
    api_module._format_pick_lines = patched_format_pick_lines
    api_module.Handler.do_GET = patched_do_get
    api_module.Handler.do_POST = patched_do_post
    return api_module
