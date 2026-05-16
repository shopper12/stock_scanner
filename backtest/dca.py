from __future__ import annotations

from data.market_data import get_us_history


def simple_dca_backtest(ticker: str = 'VOO', monthly_amount: float = 1_000_000, months: int = 24) -> dict:
    hist = get_us_history(ticker).copy().tail(months * 22)
    hist['month'] = hist['date'].dt.to_period('M')
    buys = hist.groupby('month').first().reset_index()
    units = (monthly_amount / buys['close']).sum()
    invested = monthly_amount * len(buys)
    final_value = units * float(hist['close'].iloc[-1])
    return {
        'ticker': ticker,
        'months': int(len(buys)),
        'invested_krw_proxy': round(invested),
        'final_value_krw_proxy': round(final_value),
        'return_pct': round((final_value / invested - 1) * 100, 2) if invested else 0,
    }
