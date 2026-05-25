from __future__ import annotations

import pandas as pd
from data.market_data import get_us_etf_universe, get_us_history
from strategies.metrics import annualized_volatility, max_drawdown, momentum, score_clip
from config import settings


def _fmt_price(value: float) -> str:
    return f'{value:,.2f}'


def _dca_plan(price: float, ma20: float, ma60: float, ma200: float, drawdown_52w: float, fx_signal: str) -> tuple[float, float, str]:
    buy_pct = 40.0
    triggers = [f'월 기본매수 40%: 현재가 {_fmt_price(price)}, MA20 {_fmt_price(ma20)}, MA60 {_fmt_price(ma60)}, MA200 {_fmt_price(ma200)}']
    if price <= ma20 * 1.01:
        buy_pct += 20
        triggers.append(f'20일선({_fmt_price(ma20)}) 부근 추가 20%')
    if price <= ma60 * 1.015:
        buy_pct += 20
        triggers.append(f'60일선({_fmt_price(ma60)}) 부근 추가 20%')
    if price <= ma200 * 1.03 or drawdown_52w <= -0.10:
        buy_pct += 20
        triggers.append(f'200일선({_fmt_price(ma200)})/고점대비 -10% 조정 추가 20%')
    if '최소환전' in fx_signal or '선환전 금지' in fx_signal:
        buy_pct = min(buy_pct, 40.0)
        triggers.append('고환율 구간: ETF 매수보다 환전 리스크 관리 우선')
    buy_pct = min(buy_pct, 100.0)
    return buy_pct, 100.0 - buy_pct, ' / '.join(triggers)


def scan_us_long_etfs(fx_signal: str = '분할환전') -> pd.DataFrame:
    universe = get_us_etf_universe()
    records = []
    for row in universe.to_dict('records'):
        hist = get_us_history(row['ticker']).copy()
        hist['ma20'] = hist['close'].rolling(20).mean()
        hist['ma60'] = hist['close'].rolling(60).mean()
        hist['ma200'] = hist['close'].rolling(200).mean()
        hist = hist.dropna(subset=['close', 'ma20', 'ma60', 'ma200']).reset_index(drop=True)
        if hist.empty:
            continue
        price = float(hist['close'].iloc[-1])
        ma20 = float(hist['ma20'].iloc[-1])
        ma60 = float(hist['ma60'].iloc[-1])
        ma200 = float(hist['ma200'].iloc[-1])
        high_52w = float(hist['close'].tail(252).max())
        drawdown_52w = price / high_52w - 1
        data_range_days = len(hist)
        momentum_window_days = min(252, max(1, data_range_days - 1))
        mom_12m = momentum(hist['close'], momentum_window_days)
        vol = annualized_volatility(hist['close'])
        mdd = max_drawdown(hist['close'].tail(252))

        trend_score = 25 if price > ma200 else 10
        ma20_score = 5 if price > ma20 else -3
        if data_range_days >= 220:
            mom_coef = 45.0
        elif data_range_days >= 100:
            mom_coef = 30.0
        else:
            mom_coef = 20.0
        mom_score = score_clip(10 + mom_12m * mom_coef, 0, 25)
        cost_score = score_clip(15 - float(row['expense_ratio']) * 20, 0, 15)
        dd_score = score_clip(15 + drawdown_52w * 70, 0, 15)
        vol_score = score_clip(10 - vol * 20, 0, 10)
        score = score_clip(trend_score + ma20_score + mom_score + cost_score + dd_score + vol_score)
        buy_pct, wait_pct, triggers = _dca_plan(price, ma20, ma60, ma200, drawdown_52w, fx_signal)
        records.append({
            'ticker': row['ticker'], 'name': row['name'], 'asset_class': row['asset_class'],
            'current_price': round(price, 2), 'score': round(score, 1),
            'momentum_12m_pct': round(mom_12m * 100, 2), 'momentum_window_days': momentum_window_days,
            'above_20d': bool(price > ma20), 'above_200d': bool(price > ma200),
            'drawdown_52w_pct': round(drawdown_52w * 100, 2), 'mdd_1y_pct': round(mdd * 100, 2),
            'volatility_pct': round(vol * 100, 2), 'expense_ratio_pct': row['expense_ratio'],
            'this_month_buy_pct': round(buy_pct, 1),
            'this_month_buy_krw': round(settings.us_monthly_budget_krw * buy_pct / 100),
            'cash_wait_pct': round(wait_pct, 1), 'additional_buy_condition': triggers,
            'risk_summary': _risk_summary(row['asset_class'], price, ma20, ma200, drawdown_52w, vol),
        })
    return pd.DataFrame(records).sort_values(['score', 'this_month_buy_pct'], ascending=False).reset_index(drop=True)


def _risk_summary(asset_class: str, price: float, ma20: float, ma200: float, drawdown_52w: float, vol: float) -> str:
    risks = []
    if price < ma20:
        risks.append(f'MA20({_fmt_price(ma20)}) 아래: 단기 약세, 분할매수 속도 조절')
    if price < ma200:
        risks.append(f'MA200({_fmt_price(ma200)}) 이탈: 리밸런싱 검토')
    if drawdown_52w > -0.03:
        risks.append('52주 고점 근접: 추격매수 위험')
    if vol > 0.25:
        risks.append('변동성 높음')
    if asset_class in {'Semiconductor', 'AI', 'Nasdaq100'}:
        risks.append('기술주 밸류에이션/금리 민감')
    return ', '.join(risks) if risks else f'장기 분할매수 가능 구간: MA200({_fmt_price(ma200)}) 위 유지'
