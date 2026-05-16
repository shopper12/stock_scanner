from __future__ import annotations

from data.market_data import get_fx_history
from config import settings


def analyze_fx_conversion() -> dict:
    df = get_fx_history().copy()
    df['ma20'] = df['usdkrw'].rolling(20).mean()
    df['ma60'] = df['usdkrw'].rolling(60).mean()
    df['ma120'] = df['usdkrw'].rolling(120).mean()
    latest = df.iloc[-1]
    prev20 = df.iloc[-20] if len(df) >= 20 else df.iloc[0]
    usdkrw = float(latest['usdkrw'])
    ma60 = float(latest['ma60'])
    gap60 = usdkrw / ma60 - 1
    dxy_down = float(latest['dxy']) < float(prev20['dxy'])
    us10y_down = float(latest['us10y']) < float(prev20['us10y'])

    if gap60 <= -0.015 and dxy_down and us10y_down:
        action = '선환전 검토'
        ratio = 0.6
        reason = 'USD/KRW가 60일 평균보다 낮고 DXY·미국금리 하락 방향'
    elif gap60 >= 0.02 and not dxy_down:
        action = '최소환전 / 선환전 금지'
        ratio = 0.2
        reason = 'USD/KRW가 60일 평균보다 높고 달러 강세 부담'
    elif abs(gap60) < 0.015:
        action = '3~4회 분할환전'
        ratio = 0.35
        reason = 'USD/KRW가 60일 평균권이라 환율 방향 우위가 약함'
    else:
        action = '부분환전'
        ratio = 0.4
        reason = '환율 우위가 명확하지 않아 매수 예정분만 분할 처리'

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
