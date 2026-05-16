from __future__ import annotations

import pandas as pd
from config import settings
from data.market_data import get_kr_stock_history, get_kr_stock_universe
from strategies.metrics import atr, score_clip


def scan_kr_short_stocks() -> pd.DataFrame:
    universe = get_kr_stock_universe()
    records = []
    for row in universe.to_dict('records'):
        hist = get_kr_stock_history(row['code']).copy()
        hist['ma5'] = hist['close'].rolling(5).mean()
        hist['ma20'] = hist['close'].rolling(20).mean()
        hist['volume_ma20'] = hist['volume'].rolling(20).mean()
        hist['atr14'] = atr(hist)
        latest = hist.iloc[-1]
        prev_high_20 = float(hist['high'].iloc[-21:-1].max())
        current_price = float(latest['close'])
        trade_value = float(latest.get('trade_value', current_price * latest['volume']))
        volume_ratio = float(latest['volume'] / latest['volume_ma20']) if latest['volume_ma20'] else 0
        breakout_gap = current_price / prev_high_20 - 1
        trend_ok = current_price > latest['ma5'] > latest['ma20']
        volume_score = score_clip(volume_ratio * 18, 0, 35)
        breakout_score = score_clip((breakout_gap + 0.03) * 500, 0, 30)
        liquidity_score = 20 if trade_value >= settings.min_kr_trade_value_krw else 8
        trend_score = 15 if trend_ok else 5
        score = score_clip(volume_score + breakout_score + liquidity_score + trend_score)
        stop = min(current_price - float(latest['atr14']) * 1.5, float(hist['low'].tail(5).min()))
        target1 = current_price + (current_price - stop) * 1.8
        target2 = current_price + (current_price - stop) * 2.8
        if score >= 55:
            records.append({
                'code': row['code'], 'name': row['name'], 'current_price': round(current_price),
                'score': round(score, 1), 'entry': round(max(current_price, prev_high_20)),
                'stop_loss': round(stop), 'target1': round(target1), 'target2': round(target2),
                'holding_period': '당일~10일', 'volume_ratio_20d': round(volume_ratio, 2),
                'trade_value_krw': round(trade_value), 'reason': _reason(volume_ratio, breakout_gap, trend_ok),
                'failure_condition': '전고점 돌파 실패 후 5일 저점/ATR 손절가 이탈',
            })
    if not records:
        return pd.DataFrame(columns=['code', 'name', 'current_price', 'score', 'entry', 'stop_loss', 'target1', 'target2', 'holding_period', 'reason', 'failure_condition'])
    return pd.DataFrame(records).sort_values('score', ascending=False).reset_index(drop=True)


def _reason(volume_ratio: float, breakout_gap: float, trend_ok: bool) -> str:
    flags = []
    if volume_ratio >= 2:
        flags.append('거래량 20일 평균 2배 이상')
    if breakout_gap >= -0.01:
        flags.append('20일 고점 돌파/근접')
    if trend_ok:
        flags.append('5일선>20일선 상승 구조')
    return ' + '.join(flags) if flags else '점수 기준 통과'
