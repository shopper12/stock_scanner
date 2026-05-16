from __future__ import annotations


def position_size_by_risk(account_equity: float, entry: float, stop: float, risk_pct: float = 1.0) -> int:
    risk_amount = account_equity * risk_pct / 100
    unit_risk = max(1.0, entry - stop)
    return int(risk_amount // unit_risk)
