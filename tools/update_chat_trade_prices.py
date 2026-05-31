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

COINGECKO_IDS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'SOL': 'solana',
    'BNB': 'binancecoin',
    'XRP': 'ripple',
    'ADA': 'cardano',
    'DOGE': 'dogecoin',
    'AVAX': 'avalanche-2',
    'DOT': 'polkadot',
    'LINK': 'chainlink',
    'MATIC': 'matic-network',
    'POL': 'polygon-ecosystem-token',
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


def fetch_price(asset_type: str, ticker: str, entry_mid: float | None = None) -> tuple[float | None, str, str | None]:
    asset_type = str(asset_type or '').strip().lower()
    ticker = str(ticker or '').strip().upper()
    if not ticker:
        return None, 'missing_ticker', None
    if asset_type in {'kr_stock', 'kr_etf'}:
        quote = try_kr_realtime_quote(ticker)
        if quote.get('ok') and quote.get('price'):
            price = float(quote['price'])
            return price, str(quote.get('source') or 'kr_realtime_quote'), _split_suspicion_note(price, entry_mid)
        return None, str(quote.get('error') or 'kr_quote_failed'), None
    if asset_type in {'us_equity', 'us_etf'}:
        price, source = _fetch_yfinance_price(ticker)
        return price, source, _split_suspicion_note(price, entry_mid)
    if asset_type == 'crypto':
        price, source = _fetch_crypto_price(ticker)
        return price, source, None
    return None, f'unsupported_asset_type:{asset_type}', None


def _fetch_yfinance_price(ticker: str) -> tuple[float | None, str]:
    last_error = 'not_started'
    try:
        import yfinance as yf
        raw = yf.download(ticker, period='5d', interval='1d', auto_adjust=True, progress=False)
        if raw is not None and not raw.empty:
            close = raw['Close'].dropna()
            if not close.empty:
                return float(close.iloc[-1]), 'yfinance_auto_adjust_close'
        last_error = 'empty_auto_adjust_history'
    except Exception as exc:
        last_error = f'yfinance_auto_adjust_failed:{exc}'
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, 'last_price', None) or info.get('last_price')
        if price:
            return float(price), 'yfinance_fast_info'
    except Exception as exc:
        last_error = f'{last_error} | fast_info_failed:{exc}'
    return None, last_error


def _fetch_crypto_price(ticker: str) -> tuple[float | None, str]:
    symbol = _crypto_symbol(ticker)
    coin_id = _coin_gecko_id(symbol)
    try:
        resp = requests.get(
            'https://api.coingecko.com/api/v3/simple/price',
            params={'ids': coin_id, 'vs_currencies': 'usd'},
            headers={'User-Agent': 'stock-scanner'},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            price = data.get(coin_id, {}).get('usd')
            if price:
                return float(price), 'coingecko_simple_price'
    except Exception as exc:
        last_error = f'coingecko_failed:{exc}'
    else:
        last_error = f'coingecko_http:{resp.status_code}'

    try:
        import yfinance as yf
        info = yf.Ticker(f'{symbol}-USD').fast_info
        price = getattr(info, 'last_price', None) or info.get('last_price')
        if price:
            return float(price), 'yfinance_crypto_fast_info'
    except Exception as exc:
        last_error = f'{last_error} | yfinance_crypto_failed:{exc}'

    try:
        resp = requests.get(
            'https://api.upbit.com/v1/ticker',
            params={'markets': f'USDT-{symbol}'},
            headers={'User-Agent': 'stock-scanner'},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data and data[0].get('trade_price'):
                return float(data[0]['trade_price']), 'upbit_usdt_ticker'
    except Exception as exc:
        last_error = f'{last_error} | upbit_failed:{exc}'
    else:
        last_error = f'{last_error} | upbit_http:{resp.status_code}'

    return None, last_error


def _crypto_symbol(ticker: str) -> str:
    value = str(ticker or '').strip().upper()
    for suffix in ('-USD', 'USDT', 'USD'):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    return value


def _coin_gecko_id(symbol: str) -> str:
    return COINGECKO_IDS.get(symbol.upper(), symbol.lower())


def _split_suspicion_note(price: float | None, entry_mid: float | None) -> str | None:
    if price is None or not entry_mid or entry_mid <= 0:
        return None
    ratio = price / entry_mid
    if ratio >= 5.0 or ratio <= 0.2:
        return f'주식분할/병합 의심: current/entry ratio={ratio:.2f}. adjusted price 기준 수동 확인 필요'
    return None


def _append_note(row: dict[str, Any], note: str | None) -> None:
    if not note:
        return
    existing = str(row.get('data_note') or '').strip()
    if note in existing:
        return
    row['data_note'] = f'{existing} | {note}' if existing else note


def recalc_row(row: dict[str, Any]) -> dict[str, Any]:
    price = _num(row.get('current_price'))
    entry = _num(row.get('entry_mid'))
    target = _num(row.get('target1'))
    stop = _num(row.get('stop_loss'))
    split_note = _split_suspicion_note(price, entry)
    _append_note(row, split_note)

    pnl_pct = None
    if price is not None and entry:
        pnl_pct = round((price / entry - 1.0) * 100, 2)
        row['pnl_vs_entry_mid_pct'] = pnl_pct
        if abs(pnl_pct) > 200:
            _append_note(row, '주식분할 의심 — 수동 확인 필요')
    if price is not None and target and price:
        row['distance_to_target1_pct'] = round((target / price - 1.0) * 100, 2)
    if price is not None and stop and price:
        row['distance_to_stop_pct'] = round((price / stop - 1.0) * 100, 2)

    split_suspected = bool(row.get('data_note') and '주식분할' in str(row.get('data_note')))
    if not split_suspected:
        if price is not None and target and price >= target:
            row['status'] = 'target1_hit'
        elif price is not None and stop and price <= stop:
            row['status'] = 'stop_hit'
        elif not row.get('status'):
            row['status'] = 'open'
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
        entry = _num(row.get('entry_mid'))
        if include_closed or status == 'open':
            price, source, note = fetch_price(str(row.get('asset_type')), str(row.get('ticker')), entry)
            if price is not None:
                row['current_price'] = round(float(price), 6)
                row['current_price_time'] = now
                row['current_price_source'] = source
                _append_note(row, note)
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
