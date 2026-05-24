from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from zoneinfo import ZoneInfo
import re
from typing import Any

import requests

from config import settings


@dataclass(frozen=True)
class Quote:
    code: str
    price: float
    source: str
    timestamp_kst: str
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    trade_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_kr_realtime_quote(code: str) -> Quote:
    code = str(code).zfill(6)
    errors: list[str] = []
    for getter in (_naver_item_summary, _naver_mobile_basic, _yahoo_fast_quote):
        try:
            quote = getter(code)
            if quote.price > 0:
                return quote
        except Exception as exc:
            errors.append(f'{getter.__name__}: {exc}')
    raise RuntimeError(f'KR realtime quote fetch failed for {code}; ' + ' | '.join(errors[-3:]))


def try_kr_realtime_quote(code: str) -> dict[str, Any]:
    try:
        quote = get_kr_realtime_quote(code)
        data = quote.to_dict()
        data['ok'] = True
        return data
    except Exception as exc:
        return {
            'ok': False,
            'code': str(code).zfill(6),
            'source': 'none',
            'timestamp_kst': _now_kst(),
            'error': str(exc),
        }


def _naver_item_summary(code: str) -> Quote:
    url = f'https://api.finance.naver.com/service/itemSummary.nhn?itemcode={code}'
    data = _get_json(url)
    price = _to_float(data.get('now'))
    return Quote(
        code=code,
        price=price,
        source='naver_item_summary',
        timestamp_kst=_now_kst(),
        change=_to_optional_float(data.get('diff')),
        change_pct=_to_optional_float(data.get('rate')),
        volume=_to_optional_float(data.get('quant')),
        trade_value=_to_optional_float(data.get('amount')),
    )


def _naver_mobile_basic(code: str) -> Quote:
    url = f'https://m.stock.naver.com/api/stock/{code}/basic'
    data = _get_json(url)
    price = _to_float(data.get('closePrice'))
    return Quote(
        code=code,
        price=price,
        source='naver_mobile_basic',
        timestamp_kst=_now_kst(),
        change=_to_optional_float(data.get('compareToPreviousClosePrice')),
        change_pct=_to_optional_float(data.get('fluctuationsRatio')),
        volume=_to_optional_float(data.get('accumulatedTradingVolume')),
        trade_value=_to_optional_float(data.get('accumulatedTradingValue')),
    )


def _yahoo_fast_quote(code: str) -> Quote:
    import yfinance as yf

    last_error: Exception | None = None
    for suffix in ('.KS', '.KQ'):
        ticker = f'{code}{suffix}'
        try:
            info = yf.Ticker(ticker).fast_info
            price = _to_float(getattr(info, 'last_price', None) or info.get('last_price'))
            return Quote(code=code, price=price, source=f'yahoo_fast_info{suffix}', timestamp_kst=_now_kst())
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f'empty yahoo fast quote for {code}') from last_error


def _get_json(url: str) -> dict[str, Any]:
    response = requests.get(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json,text/plain,*/*',
            'Referer': 'https://finance.naver.com/',
        },
        timeout=8,
    )
    response.raise_for_status()
    return response.json()


def _to_float(value: Any) -> float:
    if value is None:
        raise ValueError('missing numeric value')
    text = re.sub(r'[^0-9.\-]', '', str(value))
    if text in {'', '-', '.', '-.'}:
        raise ValueError(f'invalid numeric value: {value!r}')
    return float(text)


def _to_optional_float(value: Any) -> float | None:
    try:
        return _to_float(value)
    except Exception:
        return None


def _now_kst() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
