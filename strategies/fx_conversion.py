from __future__ import annotations

from data.market_data import get_fx_history
from config import settings


def analyze_fx_conversion() -> dict:
    try:
        df = get_fx_history().copy()
        df['ma20'] = df['usdkrw'].rolling(20).mean()
        df['ma60'] = df['usdkrw'].rolling(60).mean()
        df['ma120'] = df['usdkrw'].rolling(120).mean()
        df = df.ffill().dropna().reset_index(drop=True)
        if df.empty:
            raise ValueError('empty FX frame after moving averages')
        latest = df.iloc[-1]
        usdkrw = float(latest['usdkrw'])
        ma60 = float(latest['ma60'])
        gap60 = usdkrw / ma60 - 1
    except Exception as exc:
        # [FIX-FX] yfinance KRW=X rate limit must not block KR stock scanning.
        return _neutral_fx_payload(exc)

    if gap60 <= -0.035:
        action = '적극 선환전'
        suggested_conversion_krw = min(settings.us_monthly_budget_krw, 1_500_000)
        reason = f'현재 {usdkrw:.1f} / 60일 평균 {ma60:.1f} / 괴리 {gap60 * 100:.1f}% — 적극 환전 구간'
    elif -0.035 < gap60 <= -0.015:
        action = '선환전 검토'
        suggested_conversion_krw = min(settings.us_monthly_budget_krw, 900_000)
        reason = f'현재 {usdkrw:.1f} / 60일 평균 {ma60:.1f} / 괴리 {gap60 * 100:.1f}% — 선환전 유리'
    elif -0.015 < gap60 <= 0.01:
        action = '3~4회 분할환전'
        suggested_conversion_krw = min(settings.us_monthly_budget_krw, 400_000)
        reason = f'현재 {usdkrw:.1f} / 60일 평균 {ma60:.1f} / 괴리 {gap60 * 100:.1f}% — 평균 수준'
    else:
        action = '최소환전 / 선환전 금지'
        suggested_conversion_krw = min(settings.us_monthly_budget_krw, 150_000)
        reason = f'현재 {usdkrw:.1f} / 60일 평균 {ma60:.1f} / 괴리 {gap60 * 100:.1f}% — 환전 비용 발생'

    ratio = suggested_conversion_krw / settings.us_monthly_budget_krw if settings.us_monthly_budget_krw else 0.0

    return {
        'usdkrw': round(usdkrw, 2),
        'ma20': round(float(latest['ma20']), 2),
        'ma60': round(ma60, 2),
        'ma120': round(float(latest['ma120']), 2),
        'gap_vs_60d_pct': round(gap60 * 100, 2),
        'dxy': round(float(latest.get('dxy', 0.0) or 0.0), 2),
        'us10y': round(float(latest.get('us10y', 0.0) or 0.0), 2),
        'vix': round(float(latest.get('vix', 0.0) or 0.0), 2),
        'action': action,
        'suggested_conversion_ratio_pct': round(ratio * 100, 1),
        'suggested_conversion_krw': round(suggested_conversion_krw),
        'reason': reason,
        'data_quality': 'live_fx',
    }


def _neutral_fx_payload(exc: Exception) -> dict:
    suggested_conversion_krw = min(settings.us_monthly_budget_krw, 300_000)
    ratio = suggested_conversion_krw / settings.us_monthly_budget_krw if settings.us_monthly_budget_krw else 0.0
    return {
        'usdkrw': 0.0,
        'ma20': 0.0,
        'ma60': 0.0,
        'ma120': 0.0,
        'gap_vs_60d_pct': 0.0,
        'dxy': 0.0,
        'us10y': 0.0,
        'vix': 0.0,
        'action': '환율 데이터 실패: 중립 처리',
        'suggested_conversion_ratio_pct': round(ratio * 100, 1),
        'suggested_conversion_krw': round(suggested_conversion_krw),
        'reason': f'FX 데이터 오류로 환율 판단은 건너뜀. 한국 종목 스캔은 계속 실행. error={exc.__class__.__name__}: {str(exc)[:160]}',
        'data_quality': 'fx_error_neutral_fallback',
    }
