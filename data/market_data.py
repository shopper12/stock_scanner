from __future__ import annotations

import pandas as pd
from config import settings
from data import mock_data


def get_us_etf_universe() -> pd.DataFrame:
    return mock_data.us_etf_universe()


def get_us_history(ticker: str) -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.us_history(ticker)
    try:
        import yfinance as yf
        raw = yf.download(ticker, period='18mo', interval='1d', auto_adjust=True, progress=False)
        if raw.empty:
            raise ValueError('empty yfinance response')
        raw = raw.reset_index().rename(columns={'Date': 'date', 'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
        return raw[['date', 'open', 'high', 'low', 'close', 'volume']]
    except Exception:
        return mock_data.us_history(ticker)


def get_fx_history() -> pd.DataFrame:
    if settings.use_mock_data:
        return mock_data.fx_history()
    try:
        import yfinance as yf
        usdkrw = yf.download('KRW=X', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        dxy = yf.download('DX-Y.NYB', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        us10y = yf.download('^TNX', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        vix = yf.download('^VIX', period='9mo', interval='1d', auto_adjust=True, progress=False).reset_index()
        df = usdkrw[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'usdkrw'})
        df = df.merge(dxy[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'dxy'}), on='date', how='left')
        df = df.merge(us10y[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'us10y'}), on='date', how='left')
        df = df.merge(vix[['Date', 'Close']].rename(columns={'Date': 'date', 'Close': 'vix'}), on='date', how='left')
        return df.ffill().dropna()
    except Exception:
        return mock_data.fx_history()


def get_kr_retirement_etfs() -> pd.DataFrame:
    return mock_data.kr_etf_universe()


def get_kr_etf_history(code: str) -> pd.DataFrame:
    return mock_data.kr_etf_history(code)


def get_kr_stock_universe() -> pd.DataFrame:
    return mock_data.kr_stock_universe()


def get_kr_stock_history(code: str) -> pd.DataFrame:
    return mock_data.kr_stock_history(code)


def get_retirement_positions() -> pd.DataFrame:
    return mock_data.retirement_positions()
