from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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
