from __future__ import annotations

import pandas as pd
from config import settings
from data.market_data import get_kr_etf_history, get_kr_retirement_etfs, get_retirement_positions
from strategies.metrics import annualized_volatility, max_drawdown, momentum, score_clip


def scan_kr_retirement_etfs() -> tuple[pd.DataFrame, dict]:
    universe = get_kr_retirement_etfs().copy()
    positions = get_retirement_positions().copy()
    eligible = universe[(universe['retirement_eligible']) & (~universe['is_leveraged']) & (~universe['is_inverse'])].copy()
    pos_by_code = positions.set_index('code')['market_value_krw'].to_dict()
    records = []
    for row in eligible.to_dict('records'):
        hist = get_kr_etf_history(row['code']).copy()
        price = float(hist['close'].iloc[-1])
        mom_1y = momentum(hist['close'], 252)
        mom_3m = momentum(hist['close'], 63)
        vol = annualized_volatility(hist['close'])
        mdd = max_drawdown(hist['close'].tail(252))
        net_assets_score = 15
        cost_score = score_clip(15 - float(row['expense_ratio']) * 20, 0, 15)
        trend_score = score_clip((mom_1y + 0.05) * 100, 0, 30)
        stability_score = score_clip(20 - vol * 35 + mdd * 10, 0, 20)
        score = score_clip(net_assets_score + cost_score + trend_score + stability_score)
        current_value = float(pos_by_code.get(row['code'], 0.0))
        records.append({
            'code': row['code'], 'name': row['name'], 'underlying_index': row['underlying_index'],
            'asset_bucket': row['asset_bucket'], 'current_price': round(price, 2),
            'current_value_krw': round(current_value),
            'current_weight_pct': round(current_value / settings.retirement_total_krw * 100, 2),
            'score': round(score, 1), 'momentum_1y_pct': round(mom_1y * 100, 2),
            'momentum_3m_pct': round(mom_3m * 100, 2), 'mdd_1y_pct': round(mdd * 100, 2),
            'volatility_pct': round(vol * 100, 2), 'expense_ratio_pct': row['expense_ratio'],
            'recommended_weight_pct': _recommended_weight(row['asset_bucket'], row['underlying_index'], score),
        })
    result = pd.DataFrame(records).sort_values(['asset_bucket', 'score'], ascending=[True, False]).reset_index(drop=True)
    risk_report = retirement_risk_report(positions)
    result['rebalance_needed'] = result.apply(lambda r: abs(r['recommended_weight_pct'] - r['current_weight_pct']) >= 3, axis=1)
    result['additional_buy_capacity_krw'] = result.apply(lambda r: _buy_capacity(r, risk_report), axis=1)
    return result, risk_report


def _recommended_weight(asset_bucket: str, underlying: str, score: float) -> float:
    if asset_bucket == 'safe':
        return 15.0 if '채' in underlying else 10.0
    if 'S&P500' in underlying:
        return 30.0
    if 'Nasdaq' in underlying:
        return 20.0
    if '배당' in underlying:
        return 10.0
    return 5.0 if score >= 55 else 0.0


def retirement_risk_report(positions: pd.DataFrame) -> dict:
    total = float(positions['market_value_krw'].sum()) if not positions.empty else settings.retirement_total_krw
    risky = float(positions.loc[positions['asset_bucket'] == 'risky', 'market_value_krw'].sum())
    safe = float(positions.loc[positions['asset_bucket'] == 'safe', 'market_value_krw'].sum())
    risky_pct = risky / total * 100 if total else 0
    safe_pct = safe / total * 100 if total else 0
    cap = settings.retirement_risky_asset_cap_pct
    risky_room = max(0.0, total * cap / 100 - risky)
    return {
        'total_krw': round(total), 'risky_krw': round(risky), 'safe_krw': round(safe),
        'risky_pct': round(risky_pct, 2), 'safe_pct': round(safe_pct, 2),
        'risky_cap_pct': cap, 'risky_buy_room_krw': round(risky_room),
        'status': '위험자산 한도 여유' if risky_pct < cap else '위험자산 한도 초과/추가매수 금지',
    }


def _buy_capacity(row: pd.Series, risk_report: dict) -> int:
    target_value = settings.retirement_total_krw * float(row['recommended_weight_pct']) / 100
    need = max(0.0, target_value - float(row['current_value_krw']))
    if row['asset_bucket'] == 'risky':
        need = min(need, float(risk_report['risky_buy_room_krw']))
    return round(need)
