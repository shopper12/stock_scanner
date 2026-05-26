from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings
from data.realtime_price import try_kr_realtime_quote
from data.trade_history_schema import read_trade_history, write_trade_history

CRYPTO_BINANCE_SYMBOLS = {
    'BTC': 'BTCUSDT',
    'ETH': 'ETHUSDT',
    'SOL': 'SOLUSDT',
}


def _now_kst() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')


def _num(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(str(value).replace(',', '').strip())
    except Exception:
        return None


def fetch_price(asset_type: str, ticker: str) -> tuple[float | None, str]:
    asset_type = str(asset_type or '').strip().lower()
    ticker = str(ticker or '').strip().upper()
    if not ticker:
        return None, 'missing_ticker'
    if asset_type in {'kr_stock', 'kr_etf'}:
        quote = try_kr_realtime_quote(ticker)
        if quote.get('ok') and quote.get('price'):
            return float(quote['price']), str(quote.get('source') or 'kr_realtime_quote')
        return None, str(quote.get('error') or 'kr_quote_failed')
    if asset_type in {'us_equity', 'us_etf'}:
        return _fetch_yfinance_price(ticker)
    if asset_type == 'crypto':
        return _fetch_crypto_price(ticker)
    return None, f'unsupported_asset_type:{asset_type}'


def _fetch_yfinance_price(ticker: str) -> tuple[float | None, str]:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, 'last_price', None) or info.get('last_price')
        if price:
            return float(price), 'yfinance_fast_info'
    except Exception as exc:
        last_error = str(exc)
    else:
        last_error = 'empty_fast_info'
    try:
        import yfinance as yf
        raw = yf.download(ticker, period='5d', interval='1d', auto_adjust=True, progress=False)
        if raw is not None and not raw.empty:
            return float(raw['Close'].dropna().iloc[-1]), 'yfinance_daily_close'
    except Exception as exc:
        last_error = f'{last_error} | {exc}'
    return None, last_error


def _fetch_crypto_price(ticker: str) -> tuple[float | None, str]:
    symbol = CRYPTO_BINANCE_SYMBOLS.get(ticker)
    if symbol:
        try:
            resp = requests.get('https://api.binance.com/api/v3/ticker/price', params={'symbol': symbol}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            price = data.get('price')
            if price:
                return float(price), 'binance_spot'
        except Exception as exc:
            return None, f'binance_failed:{exc}'
    return None, f'unsupported_crypto:{ticker}'


def recalc_row(row: dict[str, Any]) -> dict[str, Any]:
    price = _num(row.get('current_price'))
    entry = _num(row.get('entry_mid'))
    target = _num(row.get('target1'))
    stop = _num(row.get('stop_loss'))
    if price is not None and entry:
        row['pnl_vs_entry_mid_pct'] = round((price / entry - 1.0) * 100, 2)
    if price is not None and target and price:
        row['distance_to_target1_pct'] = round((target / price - 1.0) * 100, 2)
    if price is not None and stop and price:
        row['distance_to_stop_pct'] = round((price / stop - 1.0) * 100, 2)
    if price is not None and target and price >= target:
        row['status'] = 'target1_hit'
    elif price is not None and stop and price <= stop:
        row['status'] = 'stop_hit'
    elif not row.get('status'):
        row['status'] = 'open'
    return row


def update_prices(include_closed: bool = False) -> pd.DataFrame:
    df = read_trade_history().copy()
    if df.empty:
        return df
    rows = []
    now = _now_kst()
    for raw in df.to_dict('records'):
        row = dict(raw)
        status = str(row.get('status') or 'open')
        if include_closed or status == 'open':
            price, source = fetch_price(str(row.get('asset_type')), str(row.get('ticker')))
            if price is not None:
                row['current_price'] = round(float(price), 6)
                row['current_price_time'] = now
                row['current_price_source'] = source
            else:
                row['current_price_source'] = source
        rows.append(recalc_row(row))
    out = pd.DataFrame(rows)
    write_trade_history(out)
    return out


def _git_push(message: str) -> None:
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], cwd=ROOT_DIR, check=False)
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], cwd=ROOT_DIR, check=False)
    subprocess.run(['git', 'add', 'reports/conversation_trade_history.json'], cwd=ROOT_DIR, check=True)
    diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT_DIR)
    if diff.returncode == 0:
        print('no_changes')
        return
    subprocess.run(['git', 'commit', '-m', message], cwd=ROOT_DIR, check=True)
    subprocess.run(['git', 'push'], cwd=ROOT_DIR, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description='Update current prices for ChatGPT conversation trade history.')
    parser.add_argument('--include-closed', action='store_true')
    parser.add_argument('--git-push', action='store_true')
    args = parser.parse_args()
    out = update_prices(include_closed=args.include_closed)
    print(out.to_string(index=False) if not out.empty else 'empty_history')
    if args.git_push:
        _git_push('Update chat recommendation prices')


if __name__ == '__main__':
    main()
