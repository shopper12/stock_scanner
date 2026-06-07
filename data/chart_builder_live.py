from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings
from data.chart_builder import build_chart_payload as build_base_chart_payload


def build_live_chart_payload(code: str, days: int = 120, strategy_row: dict | None = None, backtest_trades: list[dict] | None = None) -> dict:
    payload = build_base_chart_payload(code=code, days=days, strategy_row=strategy_row, backtest_trades=backtest_trades)
    quote = _realtime_quote(str(code).zfill(6))
    payload['realtime_quote'] = quote
    payload['last_updated_kst'] = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
    payload['chart_mode'] = 'daily_plus_realtime_quote'
    if quote.get('ok') and quote.get('price'):
        payload['candles'] = _merge_quote_into_candles(payload.get('candles') or [], quote)
    return payload


def _realtime_quote(code: str) -> dict:
    try:
        from data.realtime_price import try_kr_realtime_quote
        quote = try_kr_realtime_quote(code)
        return {
            'ok': bool(quote.get('ok')),
            'code': str(quote.get('code') or code).zfill(6),
            'price': _round_or_none(quote.get('price')),
            'source': quote.get('source') or 'none',
            'timestamp_kst': quote.get('timestamp_kst') or _now_kst(),
            'change': _round_or_none(quote.get('change')),
            'change_pct': _round_or_none(quote.get('change_pct')),
            'volume': _round_or_none(quote.get('volume')),
            'trade_value': _round_or_none(quote.get('trade_value')),
            'error': quote.get('error'),
        }
    except Exception as exc:
        return {
            'ok': False,
            'code': code,
            'price': None,
            'source': 'none',
            'timestamp_kst': _now_kst(),
            'change': None,
            'change_pct': None,
            'volume': None,
            'trade_value': None,
            'error': f'{exc.__class__.__name__}: {str(exc)[:160]}',
        }


def _merge_quote_into_candles(candles: list[dict], quote: dict) -> list[dict]:
    if not candles:
        return candles
    price = float(quote.get('price') or 0.0)
    if price <= 0:
        return candles
    out = [dict(c) for c in candles]
    today = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d')
    last = out[-1]
    last_date = str(last.get('date') or '')[:10]
    volume = _round_or_none(quote.get('volume')) or float(last.get('volume') or 0.0)
    trade_value = _round_or_none(quote.get('trade_value')) or float(last.get('trade_value') or 0.0)
    if last_date == today:
        last['close'] = price
        last['high'] = max(float(last.get('high') or price), price)
        last['low'] = min(float(last.get('low') or price), price)
        last['volume'] = max(float(last.get('volume') or 0.0), volume)
        last['trade_value'] = max(float(last.get('trade_value') or 0.0), trade_value)
    else:
        prev_close = float(last.get('close') or price)
        out.append({
            'date': today,
            'open': prev_close,
            'high': max(prev_close, price),
            'low': min(prev_close, price),
            'close': price,
            'volume': volume,
            'trade_value': trade_value,
        })
    return out


def _round_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except Exception:
        return None


def _now_kst() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
