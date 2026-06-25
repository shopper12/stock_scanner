from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from chat_picks import add_chat_recommendation, make_chat_recommendation

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_APP_CARDS_PATHS = [
    ROOT_DIR / 'reports' / 'app_cards_from_chatgpt.json',
    ROOT_DIR / 'reports' / 'app_cards.json',
]


def _first_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'items': data}
    except Exception:
        return {'items': []}


def load_cards_from_env() -> dict[str, Any]:
    raw = os.getenv('APP_CARDS_JSON') or os.getenv('CHATGPT_RECOMMENDATIONS_JSON')
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            return {'items': []}

    path = os.getenv('APP_CARDS_PATH') or os.getenv('CHATGPT_RECOMMENDATIONS_PATH')
    if path:
        data = _read_json_file(Path(path))
        if data is not None:
            return data

    url = os.getenv('APP_CARDS_URL') or os.getenv('CHATGPT_RECOMMENDATIONS_URL') or os.getenv('CHAT_PICKS_SOURCE_URL')
    if url:
        try:
            res = requests.get(url, timeout=5.0, headers={'User-Agent': 'stock-scanner-card-sync/1.0'})
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, dict) else {'items': data}
        except Exception:
            return {'items': []}

    for default_path in DEFAULT_APP_CARDS_PATHS:
        data = _read_json_file(default_path)
        if data is not None:
            return data
    return {'items': []}


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ['items', 'recommendations', 'active_recommendations']:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    for key in ['briefing_state', 'briefing_state_json', 'state']:
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _extract_items(nested)
            if found:
                return found
    return []


def write_cards_to_history(payload: dict[str, Any]) -> dict[str, Any]:
    saved = []
    stable_at = payload.get('briefing_datetime_kst') or payload.get('generated_at') or payload.get('timestamp_kst')
    for row in _extract_items(payload):
        code = str(row.get('ticker') or row.get('code') or row.get('symbol') or '').strip()
        name = str(row.get('asset_name') or row.get('name') or row.get('asset') or code).strip()
        if not code and not name:
            continue
        entry = make_chat_recommendation(
            code=code or name,
            name=name or code,
            market=str(row.get('market') or 'CHAT'),
            sector=str(row.get('sector') or row.get('asset_class') or 'ChatGPT'),
            strategy_type=str(row.get('strategy_type') or 'chat_card'),
            current_price=_first_number(row.get('basis_price') or row.get('current_price') or row.get('reference_price')),
            entry=_first_number(row.get('entry') or row.get('entry_range')),
            stop_loss=_first_number(row.get('stop') or row.get('stop_loss')),
            target1=_first_number(row.get('target1')),
            target2=_first_number(row.get('target2')),
            rationale=str(row.get('reason') or row.get('memo') or row.get('why_now') or row.get('trigger_condition') or ''),
            risk=str(row.get('risk') or row.get('invalidation') or ''),
            recommended_at_kst=str(row.get('recommended_at_kst') or row.get('basis_timestamp_kst') or stable_at or '').strip() or None,
            source_note=f"ChatGPT briefing {stable_at or ''}".strip(),
        )
        add_chat_recommendation(entry, notify=False)
        saved.append(entry)
    return {'ok': True, 'saved': len(saved), 'items': saved}


def sync_cards_from_env() -> dict[str, Any]:
    return write_cards_to_history(load_cards_from_env())
