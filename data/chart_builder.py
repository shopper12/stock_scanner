from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings
from data.market_data import get_kr_stock_history
from strategies.kr_short_stock import _prepare_history, _rsi14

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_PATH = REPORT_DIR / 'latest.json'
TRADES_PATH = REPORT_DIR / 'kr_short_trades_latest.json'


def build_chart_payload(
    code: str,
    days: int = 120,
    strategy_row: dict | None = None,
    backtest_trades: list[dict] | None = None,
) -> dict:
    code = str(code or '').zfill(6)
    days = max(20, min(int(days or 120), 252))
    hist = _prepare_history(get_kr_stock_history(code).copy())
    if hist.empty:
        raise RuntimeError(f'no history for {code}')
    hist = _ensure_chart_columns(hist)
    sliced = hist.tail(days).copy()
    name = _resolve_name(code, strategy_row)
    return {
        'ok': True,
        'code': code,
        'name': name,
        'days': int(days),
        'candles': [_candle(row) for _, row in sliced.iterrows()],
        'indicators': {
            'ma20': [_nullable_round(v) for v in sliced.get('ma20', pd.Series(dtype=float)).tolist()],
            'ma60': [_nullable_round(v) for v in sliced.get('ma60', pd.Series(dtype=float)).tolist()],
            'ma200': [_nullable_round(v) for v in sliced.get('ma200', pd.Series(dtype=float)).tolist()],
            'volume_ma20': [_nullable_round(v) for v in sliced.get('volume_ma20', pd.Series(dtype=float)).tolist()],
            'rsi14': [_nullable_round(v) for v in sliced.get('rsi14', pd.Series(dtype=float)).tolist()],
        },
        'strategy': _strategy_payload(strategy_row),
        'backtest_trades': _normalise_backtest_trades(code, backtest_trades or get_backtest_trades_for_code(code)),
    }


def get_backtest_trades_for_code(code: str) -> list[dict]:
    code = str(code or '').zfill(6)
    if not TRADES_PATH.exists():
        return []
    try:
        data = json.loads(TRADES_PATH.read_text(encoding='utf-8'))
        rows = data.get('trades') or []
        return [row for row in rows if str(row.get('code', '')).zfill(6) == code]
    except Exception:
        return []


def save_backtest_trades(trades: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'schema_version': 1,
        'created_at_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'trades': trades,
    }
    TRADES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def find_latest_strategy_row(code: str) -> dict | None:
    code = str(code or '').zfill(6)
    if not LATEST_PATH.exists():
        return None
    try:
        data = json.loads(LATEST_PATH.read_text(encoding='utf-8'))
        for row in data.get('kr_short_stocks') or []:
            if str(row.get('code', '')).zfill(6) == code:
                copied = dict(row)
                copied.setdefault('scan_time', data.get('created_at_kst'))
                return copied
    except Exception:
        return None
    return None


def _ensure_chart_columns(hist: pd.DataFrame) -> pd.DataFrame:
    out = hist.copy()
    if 'trade_value' not in out.columns:
        out['trade_value'] = pd.to_numeric(out.get('close'), errors='coerce').fillna(0) * pd.to_numeric(out.get('volume'), errors='coerce').fillna(0)
    if 'volume_ma20' not in out.columns:
        out['volume_ma20'] = pd.to_numeric(out.get('volume'), errors='coerce').rolling(20).mean()
    if 'rsi14' not in out.columns:
        close = pd.to_numeric(out.get('close'), errors='coerce')
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        out['rsi14'] = 100 - (100 / (1 + rs))
        if out['rsi14'].isna().all() and len(close) >= 15:
            out.loc[out.index[-1], 'rsi14'] = _rsi14(close)
    return out


def _candle(row: pd.Series) -> dict:
    return {
        'date': _date_text(row.get('date', row.name)),
        'open': _nullable_round(row.get('open')),
        'high': _nullable_round(row.get('high')),
        'low': _nullable_round(row.get('low')),
        'close': _nullable_round(row.get('close')),
        'volume': int(float(row.get('volume') or 0)),
        'trade_value': int(float(row.get('trade_value') or 0)),
    }


def _strategy_payload(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        'score': _nullable_round(row.get('score')),
        'setup': row.get('strategy_type') or row.get('setup'),
        'entry': _nullable_round(row.get('entry') or row.get('entry_price')),
        'stop_loss': _nullable_round(row.get('stop_loss') or row.get('stop_price')),
        'target1': _nullable_round(row.get('target1')),
        'target2': _nullable_round(row.get('target2')),
        'reason': row.get('reason') or row.get('rationale') or '',
        'scan_time': row.get('scan_time') or row.get('recommended_at_kst'),
    }


def _normalise_backtest_trades(code: str, rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        out.append({
            'code': str(row.get('code', code)).zfill(6),
            'date': _date_text(row.get('date') or row.get('entry_date') or row.get('scan_date')),
            'setup': str(row.get('setup') or row.get('strategy_type') or ''),
            'score': _nullable_round(row.get('score')) or 0.0,
            'entry': _nullable_round(row.get('entry') or row.get('entry_price')) or 0.0,
            'stop': _nullable_round(row.get('stop') or row.get('stop_loss') or row.get('stop_price')) or 0.0,
            'trade_return_pct': _nullable_round(row.get('trade_return_pct') or row.get('return_pct') or row.get('pnl_pct')) or 0.0,
            'exit_reason': str(row.get('exit_reason') or row.get('status') or ''),
            'caught_surge': bool(row.get('caught_surge') or row.get('hit_target1') or row.get('hit_target2')),
        })
    return out


def _resolve_name(code: str, strategy_row: dict | None) -> str:
    if strategy_row and strategy_row.get('name') and str(strategy_row.get('name')) != code:
        return str(strategy_row['name'])
    try:
        from pykrx import stock
        name = stock.get_market_ticker_name(code)
        if name:
            return str(name)
    except Exception:
        pass
    return code


def _nullable_round(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return round(number, 2)
    except Exception:
        return None


def _date_text(value: Any) -> str:
    if value is None:
        return ''
    try:
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d')
    except Exception:
        pass
    text = str(value)
    return text[:10]
