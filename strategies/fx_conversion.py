from __future__ import annotations

from data.market_data import get_fx_history
from config import settings


def analyze_fx_conversion() -> dict:
    df = get_fx_history().copy()
    df['ma20'] = df['usdkrw'].rolling(20).mean()
    df['ma60'] = df['usdkrw'].rolling(60).mean()
    df['ma120'] = df['usdkrw'].rolling(120).mean()
    latest = df.iloc[-1]
    usdkrw = float(latest['usdkrw'])
    ma60 = float(latest['ma60'])
    gap60 = usdkrw / ma60 - 1

    if gap60 <= -0.03:
        action = '적극 선환전'
        ratio = 1.2
    elif -0.03 < gap60 <= -0.015:
        action = '선환전 검토'
        ratio = 0.8
    elif -0.015 < gap60 <= 0.01:
        action = '3~4회 분할환전'
        ratio = 0.4
    else:
        action = '최소환전 / 선환전 금지'
        ratio = 0.2

    reason = f"실데이터: 현재 {usdkrw:.2f} / 60일평균 {ma60:.2f} / 괴리 {gap60 * 100:.1f}%"

    return {
        'usdkrw': round(usdkrw, 2),
        'ma20': round(float(latest['ma20']), 2),
        'ma60': round(ma60, 2),
        'ma120': round(float(latest['ma120']), 2),
        'gap_vs_60d_pct': round(gap60 * 100, 2),
        'dxy': round(float(latest['dxy']), 2),
        'us10y': round(float(latest['us10y']), 2),
        'vix': round(float(latest['vix']), 2),
        'action': action,
        'suggested_conversion_ratio_pct': round(ratio * 100, 1),
        'suggested_conversion_krw': round(settings.us_monthly_budget_krw * ratio),
        'reason': reason,
    }