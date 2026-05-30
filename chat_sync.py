from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from chat_picks import CHAT_HISTORY_PATH, COMMON_HISTORY_PATH, REPORT_DIR, _now_kst_text, _read_json, _write_upsert, make_chat_recommendation

DEFAULT_INBOX_URL = 'https://raw.githubusercontent.com/shopper12/stock_scanner/main/reports/chatgpt_picks_inbox.json'
CACHE_PATH = REPORT_DIR / 'chatgpt_picks_remote_cache.json'
STATE_PATH = REPORT_DIR / 'chatgpt_picks_sync_state.json'


def _enabled() -> bool:
    return os.getenv('CHATGPT_PICKS_AUTO_SYNC', '1').strip().lower() not in {'0', 'false', 'no', 'off'}


def _url() -> str:
    return os.getenv('CHATGPT_PICKS_REMOTE_URL', DEFAULT_INBOX_URL).strip()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _load_remote() -> dict:
    response = requests.get(_url(), headers={'User-Agent': 'stock-scanner-chat-sync'}, timeout=12)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError('remote payload must be a JSON object')
    items = payload.get('items', [])
    if not isinstance(items, list):
        raise ValueError('remote payload items must be a list')
    payload['items'] = items
    return payload


def _convert(item: dict[str, Any]) -> dict | None:
    code = str(item.get('code') or item.get('ticker') or '').strip()
    name = str(item.get('name') or '').strip()
    if not code or not name:
        return None
    entry = make_chat_recommendation(
        code=code,
        name=name,
        market=str(item.get('market') or 'KRX'),
        sector=str(item.get('sector') or '기타'),
        strategy_type=str(item.get('strategy_type') or 'chat_note'),
        current_price=item.get('current_price') or item.get('price_at_recommendation'),
        entry=item.get('entry'),
        entry_low=item.get('entry_low'),
        entry_high=item.get('entry_high'),
        stop_loss=item.get('stop_loss'),
        target1=item.get('target1'),
        target2=item.get('target2'),
        rationale=str(item.get('rationale') or item.get('reason') or ''),
        risk=str(item.get('risk') or ''),
        source_note=str(item.get('source_note') or 'remote chat inbox'),
        recommended_at_kst=item.get('recommended_at_kst'),
    )
    stable_id = str(item.get('id') or '').strip()
    if stable_id:
        entry['source_id'] = f'remote_chat:{stable_id}'
    entry['source'] = 'remote_chat_inbox'
    return entry


def sync_remote_chat_history() -> dict:
    if not _enabled():
        return {'ok': False, 'skipped': True, 'reason': 'disabled'}
    now = _now_kst_text()
    try:
        payload = _load_remote()
    except Exception as exc:
        return {'ok': False, 'skipped': False, 'reason': f'{type(exc).__name__}: {exc}', 'url': _url()}
    _write(CACHE_PATH, payload)
    before = len(_read_json(CHAT_HISTORY_PATH).get('items', []))
    valid = 0
    for raw in payload.get('items', []):
        if not isinstance(raw, dict):
            continue
        entry = _convert(raw)
        if entry is None:
            continue
        valid += 1
        _write_upsert(CHAT_HISTORY_PATH, entry, now)
        _write_upsert(COMMON_HISTORY_PATH, entry, now)
    after = len(_read_json(CHAT_HISTORY_PATH).get('items', []))
    state = {
        'ok': True,
        'skipped': False,
        'url': _url(),
        'synced_at_kst': now,
        'remote_updated_at_kst': payload.get('updated_at_kst'),
        'remote_items': len(payload.get('items', [])),
        'valid_items': valid,
        'new_local_items': max(0, after - before),
    }
    _write(STATE_PATH, state)
    return state


def read_sync_state() -> dict:
    return _read_json(STATE_PATH)


if __name__ == '__main__':
    print(json.dumps(sync_remote_chat_history(), ensure_ascii=False, indent=2, default=str))
