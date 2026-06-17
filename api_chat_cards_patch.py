from __future__ import annotations

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


def _attach_chat_history(api_module: Any, payload: dict) -> dict:
    status, data = _read_chat_history(api_module, auto_sync=True)
    rows = data.get('items') if status == 200 else []
    payload = dict(payload)
    payload['chatgpt_recommendations'] = rows[:20] if isinstance(rows, list) else []
    payload['chatgpt_recommendation_count'] = len(rows) if isinstance(rows, list) else 0
    payload['chatgpt_recommendations_updated_at_kst'] = data.get('updated_at_kst') if isinstance(data, dict) else None
    payload['chatgpt_recommendations_endpoint'] = '/api/chatgpt-picks'
    payload['chatgpt_recommendations_aliases'] = ['/api/recommendations', '/api/chatgpt/recommendations']
    return payload


def _save_chat_payload(data: dict) -> dict:
    from sync_bridge import write_cards_to_history
    result = write_cards_to_history(data)
    return {
        'ok': True,
        'saved_count': result.get('saved', 0),
        'items': result.get('items', [])[:20],
    }


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
        if path in {'/api/recommendations', '/api/chatgpt/recommendations', '/api/chatgpt-picks'}:
            status, data = _read_chat_history(api_module, auto_sync=True)
            self._send_json(status, data)
            return
        if path in {'/', '/health'}:
            status, data = api_module._latest_payload(auto_bootstrap=False)
            chat_count = 0
            if status == 200:
                chat_count = int(data.get('chatgpt_recommendation_count') or 0)
            self._send_json(200, {
                'ok': True,
                'service': 'stock_scanner_api',
                'version': 'chat-cards-api-v1',
                'endpoints': [
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
                'chatgpt_recommendation_count': chat_count,
                'chatgpt_recommendations_endpoint': '/api/chatgpt-picks',
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
