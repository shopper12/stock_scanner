from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import sqlite3
from pathlib import Path
import pandas as pd
from config import BASE_DIR, settings


def _db_path() -> Path:
    if settings.database_url.startswith('sqlite:///'):
        raw = settings.database_url.replace('sqlite:///', '', 1)
        path = Path(raw)
        return path if path.is_absolute() else BASE_DIR / path
    return BASE_DIR / 'stock_scanner.db'


def init_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                run_type TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        ''')
        conn.commit()


def save_payload(run_type: str, payload: dict[str, Any]) -> None:
    init_db()
    clean_payload = _to_jsonable(payload)
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            'INSERT INTO scan_runs (created_at, run_type, payload) VALUES (?, ?, ?)',
            (datetime.now().isoformat(timespec='seconds'), run_type, json.dumps(clean_payload, ensure_ascii=False)),
        )
        conn.commit()


def latest_payload(run_type: str = 'full_scan') -> dict[str, Any] | None:
    init_db()
    with sqlite3.connect(_db_path()) as conn:
        row = conn.execute(
            'SELECT payload FROM scan_runs WHERE run_type=? ORDER BY id DESC LIMIT 1',
            (run_type,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict('records')
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value
