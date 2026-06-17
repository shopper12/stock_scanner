from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from chat_picks import add_chat_recommendation, make_chat_recommendation


def load_cards_from_env() -> dict[str, Any]:
    raw = os.getenv('APP_CARDS_JSON')
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return {'items': []}
    path = os.getenv('APP_CARDS_PATH')
    if path and Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except Exception:
            return {'items': []}
    return {'items': []}


def write_cards_to_history(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get('items') or payload.get('recommendations') or payload.get('active_recommendations') or []
    saved = []
    for row in items:
        if not isinstance(row, dict):
            continue
        code = str(row.get('ticker') or row.get('code') or row.get('symbol') or '').strip()
        name = str(row.get('asset_name') or row.get('name') or row.get('asset') or code).strip()
        if not code and not name:
            continue
        entry = make_chat_recommendation(code=code or name, name=name or code, market=str(row.get('market') or 'CHAT'), sector=str(row.get('sector') or 'ChatGPT'), strategy_type='chat_card', current_price=row.get('basis_price') or row.get('current_price'), entry=row.get('entry'), stop_loss=row.get('stop') or row.get('stop_loss'), target1=row.get('target1'), target2=row.get('target2'), rationale=str(row.get('reason') or row.get('memo') or ''), risk=str(row.get('risk') or row.get('invalidation') or ''))
        add_chat_recommendation(entry, notify=False)
        saved.append(entry)
    return {'ok': True, 'saved': len(saved), 'items': saved}


def sync_cards_from_env() -> dict[str, Any]:
    return write_cards_to_history(load_cards_from_env())
