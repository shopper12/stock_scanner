from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
TRADE_HISTORY_PATH = ROOT_DIR / 'reports' / 'conversation_trade_history.json'

HISTORY_COLUMNS = [
    'id', 'date', 'session', 'asset_type', 'ticker', 'name', 'currency',
    'entry_low', 'entry_high', 'entry_mid', 'stop_loss', 'target1', 'target2',
    'current_price', 'current_price_time', 'current_price_source',
    'pnl_vs_entry_mid_pct', 'distance_to_target1_pct', 'distance_to_stop_pct',
    'status', 'source_status', 'memo',
]


def empty_trade_history() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORY_COLUMNS)


def read_trade_history() -> pd.DataFrame:
    if not TRADE_HISTORY_PATH.exists():
        return empty_trade_history()
    try:
        payload = json.loads(TRADE_HISTORY_PATH.read_text(encoding='utf-8'))
        df = pd.DataFrame(payload.get('items', []))
        for col in HISTORY_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[HISTORY_COLUMNS]
    except Exception:
        return empty_trade_history()


def write_trade_history(df: pd.DataFrame) -> None:
    TRADE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in HISTORY_COLUMNS:
        if col not in out.columns:
            out[col] = None
    payload = {'schema_version': 1, 'items': out[HISTORY_COLUMNS].to_dict('records')}
    TRADE_HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
