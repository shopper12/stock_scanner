from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings
from database.db import _db_path, init_db


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def _now_text() -> str:
    return _now_kst().strftime('%Y-%m-%d %H:%M:%S %Z')


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    snapshot = out.get('snapshot')
    if snapshot:
        try:
            out['snapshot'] = json.loads(snapshot)
        except Exception:
            pass
    return out


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except Exception:
        return default


def save_recommendation(rec: dict) -> str | None:
    """Save one recommendation for outcome tracking.

    Returns None when the same code is already open. This prevents duplicate DB rows
    while keeping the scanner output itself unchanged.
    """
    init_db()
    code = str(rec.get('code') or '').zfill(6)
    if not code:
        return None
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM recommendations WHERE code=? AND status='open' ORDER BY created_at DESC LIMIT 1",
            (code,),
        ).fetchone()
        if existing:
            return None
        rid = str(uuid4())
        created_at = _now_text()
        scan_date = str(rec.get('scan_date') or created_at.split(' ')[0])
        conn.execute(
            '''
            INSERT INTO recommendations (
                id, created_at, scan_date, code, name, sector, setup, score,
                entry_price, stop_price, target1, target2, hold_days, snapshot, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            ''',
            (
                rid,
                created_at,
                scan_date,
                code,
                rec.get('name', ''),
                rec.get('sector', ''),
                rec.get('setup', ''),
                _num(rec.get('score')),
                _num(rec.get('entry_price')),
                _num(rec.get('stop_price')),
                _num(rec.get('target1')),
                _num(rec.get('target2')),
                int(_num(rec.get('hold_days'), 10)),
                json.dumps(rec.get('snapshot') or {}, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
    return rid


def load_open_recommendations() -> list[dict]:
    init_db()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE status='open' ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def is_cooldown_active(code: str, cooldown_days: int = 10) -> bool:
    code = str(code or '').zfill(6)
    if not code:
        return False
    init_db()
    cutoff = _now_kst() - timedelta(days=cooldown_days)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        open_row = conn.execute(
            "SELECT id FROM recommendations WHERE code=? AND status='open' LIMIT 1",
            (code,),
        ).fetchone()
        if open_row:
            return True
        closed = conn.execute(
            '''
            SELECT o.closed_at
            FROM recommendation_outcomes o
            JOIN recommendations r ON r.id=o.id
            WHERE r.code=?
            ORDER BY o.closed_at DESC
            LIMIT 1
            ''',
            (code,),
        ).fetchone()
    if not closed or not closed['closed_at']:
        return False
    try:
        text = str(closed['closed_at']).replace(' KST', '').strip()
        closed_at = datetime.fromisoformat(text)
        if closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=ZoneInfo(settings.timezone))
        return closed_at >= cutoff
    except Exception:
        return False


def update_all_open_recommendations() -> list[dict]:
    closed_rows: list[dict] = []
    for rec in load_open_recommendations():
        outcome = _evaluate_recommendation(rec)
        if not outcome:
            continue
        _close_recommendation(rec, outcome)
        closed = {**rec, **outcome}
        closed_rows.append(closed)
    return closed_rows


def _evaluate_recommendation(rec: dict) -> dict | None:
    entry = _num(rec.get('entry_price'))
    stop = _num(rec.get('stop_price'))
    target1 = _num(rec.get('target1'))
    target2 = _num(rec.get('target2'))
    hold_days = int(_num(rec.get('hold_days'), 10))
    if entry <= 0:
        return None
    bars = _fetch_recent_bars(str(rec.get('code') or '').zfill(6), max(hold_days + 5, 15))
    if bars.empty:
        return None
    high = float(bars['High'].max())
    low = float(bars['Low'].min())
    last_close = float(bars['Close'].dropna().iloc[-1])
    entered = high >= entry
    if not entered:
        return None
    days_held = min(len(bars), hold_days)
    mfe_pct = (high / entry - 1.0) * 100.0
    mae_pct = (low / entry - 1.0) * 100.0
    exit_reason = None
    close_price = last_close
    if stop > 0 and low <= stop:
        exit_reason = 'stop'
        close_price = stop
    elif target2 > 0 and high >= target2:
        exit_reason = 'target2'
        close_price = target2
    elif target1 > 0 and high >= target1:
        exit_reason = 'target1'
        close_price = target1
    elif days_held >= hold_days:
        exit_reason = 'time_exit'
        close_price = last_close
    if not exit_reason:
        return None
    return {
        'closed_at': _now_text(),
        'close_price': round(close_price, 2),
        'exit_reason': exit_reason,
        'realized_return_pct': round((close_price / entry - 1.0) * 100.0, 2),
        'mfe_pct': round(mfe_pct, 2),
        'mae_pct': round(mae_pct, 2),
        'days_held': int(days_held),
    }


def _fetch_recent_bars(code: str, days: int) -> pd.DataFrame:
    try:
        import yfinance as yf
        ticker = f'{code.zfill(6)}.KS'
        bars = yf.download(ticker, period=f'{max(days, 5)}d', interval='1d', auto_adjust=True, progress=False)
        if bars is not None and not bars.empty:
            return bars.dropna(how='all')
    except Exception:
        pass
    return pd.DataFrame()


def _close_recommendation(rec: dict, outcome: dict) -> None:
    init_db()
    rid = str(rec.get('id') or '')
    if not rid:
        return
    with sqlite3.connect(_db_path()) as conn:
        conn.execute(
            '''
            INSERT OR REPLACE INTO recommendation_outcomes (
                id, closed_at, close_price, exit_reason, realized_return_pct,
                mfe_pct, mae_pct, days_held
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                rid,
                outcome.get('closed_at'),
                outcome.get('close_price'),
                outcome.get('exit_reason'),
                outcome.get('realized_return_pct'),
                outcome.get('mfe_pct'),
                outcome.get('mae_pct'),
                outcome.get('days_held'),
            ),
        )
        conn.execute("UPDATE recommendations SET status='closed' WHERE id=?", (rid,))
        conn.commit()


def summarise_live_performance() -> dict:
    init_db()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute('SELECT COUNT(*) AS n FROM recommendations').fetchone()['n']
        open_count = conn.execute("SELECT COUNT(*) AS n FROM recommendations WHERE status='open'").fetchone()['n']
        rows = conn.execute(
            '''
            SELECT r.code, r.name, r.sector, r.setup, r.score, o.*
            FROM recommendation_outcomes o
            JOIN recommendations r ON r.id=o.id
            ORDER BY o.closed_at DESC
            '''
        ).fetchall()
    closed = [_row_to_dict(row) for row in rows]
    closed_count = len(closed)
    if not closed:
        return {
            'total_recommendations': int(total),
            'open_count': int(open_count),
            'closed_count': 0,
            'avg_realized_return_pct': 0.0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_mfe_pct': 0.0,
            'avg_mae_pct': 0.0,
            'exit_reason_breakdown': {},
            'by_setup': {},
        }
    df = pd.DataFrame(closed)
    returns = pd.to_numeric(df['realized_return_pct'], errors='coerce').fillna(0.0)
    gains = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    profit_factor = float(gains / losses) if losses else (999.0 if gains > 0 else 0.0)
    by_setup = {}
    for setup, group in df.groupby('setup'):
        r = pd.to_numeric(group['realized_return_pct'], errors='coerce').fillna(0.0)
        by_setup[str(setup or 'unknown')] = {
            'avg_return': round(float(r.mean()), 2),
            'win_rate': round(float((r > 0).mean()), 4),
            'count': int(len(group)),
        }
    return {
        'total_recommendations': int(total),
        'open_count': int(open_count),
        'closed_count': int(closed_count),
        'avg_realized_return_pct': round(float(returns.mean()), 2),
        'win_rate': round(float((returns > 0).mean()), 4),
        'profit_factor': round(profit_factor, 4),
        'avg_mfe_pct': round(float(pd.to_numeric(df['mfe_pct'], errors='coerce').fillna(0.0).mean()), 2),
        'avg_mae_pct': round(float(pd.to_numeric(df['mae_pct'], errors='coerce').fillna(0.0).mean()), 2),
        'exit_reason_breakdown': df['exit_reason'].value_counts().to_dict(),
        'by_setup': by_setup,
    }
