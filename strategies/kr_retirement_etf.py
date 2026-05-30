from __future__ import annotations

import pandas as pd
from config import settings
from data.market_data import get_kr_etf_history, get_kr_retirement_etfs, get_retirement_positions
from strategies.metrics import annualized_volatility, max_drawdown, momentum, score_clip


def scan_kr_retirement_etfs() -> tuple[pd.DataFrame, dict]:
    """퇴직연금용 ETF를 ETF 자체 매력도 기준으로 추천한다.

    사용자 지침: 한도/보유금액은 추천 판단에 반영하지 않는다.
    - retirement_eligible, leveraged/inverse 제외만 적용
    - 현재 보유비중/위험자산 한도/추가매수 가능금액은 참고용 risk_report에만 남긴다
    - 최종 정렬은 score 단일 기준
    """
    universe = get_kr_retirement_etfs().copy()
    positions = get_retirement_positions().copy()
    eligible = universe[(universe['retirement_eligible']) & (~universe['is_leveraged']) & (~universe['is_inverse'])].copy()
    pos_by_code = positions.set_index('code')['market_value_krw'].to_dict() if not positions.empty else {}
    records = []
    for row in eligible.to_dict('records'):
        hist = get_kr_etf_history(row['code']).copy()
        price = float(hist['close'].iloc[-1])
        mom_1y = momentum(hist['close'], 252)
        mom_6m = momentum(hist['close'], 126)
        mom_3m = momentum(hist['close'], 63)
        mom_1m = momentum(hist['close'], 21)
        vol = annualized_volatility(hist['close'])
        mdd = max_drawdown(hist['close'].tail(252))
        cost = float(row['expense_ratio'])
        score = _etf_score(str(row['asset_bucket']), str(row['underlying_index']), mom_1y, mom_6m, mom_3m, mom_1m, vol, mdd, cost)
        current_value = float(pos_by_code.get(row['code'], 0.0))
        records.append({
            'code': row['code'],
            'name': row['name'],
            'underlying_index': row['underlying_index'],
            'asset_bucket': row['asset_bucket'],
            'current_price': round(price, 2),
            'current_value_krw': round(current_value),
            'current_weight_pct': round(current_value / settings.retirement_total_krw * 100, 2) if settings.retirement_total_krw else 0.0,
            'score': round(score, 1),
            'rank_reason': _rank_reason(str(row['underlying_index']), mom_1y, mom_6m, mom_3m, vol, mdd, cost),
            'momentum_1y_pct': round(mom_1y * 100, 2),
            'momentum_6m_pct': round(mom_6m * 100, 2),
            'momentum_3m_pct': round(mom_3m * 100, 2),
            'momentum_1m_pct': round(mom_1m * 100, 2),
            'mdd_1y_pct': round(mdd * 100, 2),
            'volatility_pct': round(vol * 100, 2),
            'expense_ratio_pct': cost,
            'recommended_weight_pct': 0.0,
            'rebalance_needed': False,
            'additional_buy_capacity_krw': 0,
        })
    result = pd.DataFrame(records).sort_values(['score', 'momentum_6m_pct', 'momentum_3m_pct'], ascending=[False, False, False]).reset_index(drop=True)
    result['rank'] = result.index + 1
    return result, retirement_risk_report(positions)


def _etf_score(asset_bucket: str, underlying: str, mom_1y: float, mom_6m: float, mom_3m: float, mom_1m: float, vol: float, mdd: float, cost: float) -> float:
    trend_score = score_clip((mom_1y * 35.0) + (mom_6m * 45.0) + (mom_3m * 35.0) + (mom_1m * 15.0), -20.0, 45.0)
    risk_score = score_clip(25.0 - vol * 35.0 + mdd * 12.0, 0.0, 25.0)
    cost_score = score_clip(15.0 - cost * 25.0, 0.0, 15.0)
    liquidity_quality_score = _structural_quality_score(asset_bucket, underlying)
    return score_clip(35.0 + trend_score + risk_score + cost_score + liquidity_quality_score, 0.0, 100.0)


def _structural_quality_score(asset_bucket: str, underlying: str) -> float:
    u = underlying.upper()
    score = 0.0
    if 'S&P500' in u or 'S&P 500' in u:
        score += 10.0
    if 'NASDAQ' in u or '나스닥' in underlying:
        score += 8.0
    if '미국' in underlying or 'US' in u:
        score += 4.0
    if '배당' in underlying:
        score += 4.0
    if asset_bucket == 'safe' or '채' in underlying:
        score += 2.0
    return score_clip(score, 0.0, 12.0)


def _rank_reason(underlying: str, mom_1y: float, mom_6m: float, mom_3m: float, vol: float, mdd: float, cost: float) -> str:
    return (
        f'{underlying}: 1Y {mom_1y * 100:.1f}%, 6M {mom_6m * 100:.1f}%, '
        f'3M {mom_3m * 100:.1f}%, 변동성 {vol * 100:.1f}%, '
        f'MDD {mdd * 100:.1f}%, 비용 {cost:.2f}% 기준 ETF 자체 점수'
    )


def retirement_risk_report(positions: pd.DataFrame) -> dict:
    total = float(positions['market_value_krw'].sum()) if not positions.empty else settings.retirement_total_krw
    risky = float(positions.loc[positions['asset_bucket'] == 'risky', 'market_value_krw'].sum()) if not positions.empty else 0.0
    safe = float(positions.loc[positions['asset_bucket'] == 'safe', 'market_value_krw'].sum()) if not positions.empty else 0.0
    risky_pct = risky / total * 100 if total else 0
    safe_pct = safe / total * 100 if total else 0
    cap = settings.retirement_risky_asset_cap_pct
    risky_room = max(0.0, total * cap / 100 - risky)
    return {
        'total_krw': round(total),
        'risky_krw': round(risky),
        'safe_krw': round(safe),
        'risky_pct': round(risky_pct, 2),
        'safe_pct': round(safe_pct, 2),
        'risky_cap_pct': cap,
        'risky_buy_room_krw': round(risky_room),
        'status': '참고용: ETF 추천 순위에는 위험자산 한도/보유금액을 반영하지 않음',
    }
