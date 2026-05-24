from __future__ import annotations

import math

import pandas as pd
from config import settings
from data.market_data import get_kr_stock_history, get_kr_stock_universe
from data.realtime_price import try_kr_realtime_quote
from strategies.kr_short_rules import load_kr_short_rules
from strategies.metrics import atr, momentum, score_clip


COLUMNS = [
    'code', 'name', 'sector', 'current_price', 'price_basis', 'price_timestamp', 'history_last_date',
    'quote_source', 'quote_ok', 'quote_error', 'score', 'entry', 'stop_loss', 'target1', 'target2',
    'risk_pct', 'position_size_krw', 'holding_period', 'strategy_type', 'volume_ratio_20d',
    'trade_value_ratio_20d', 'trade_value_krw', 'momentum_5d_pct', 'momentum_20d_pct',
    'momentum_60d_pct', 'drawdown_60d_pct', 'reason', 'failure_condition', 'data_source'
]


def scan_kr_short_stocks() -> pd.DataFrame:
    rules = load_kr_short_rules()
    universe = get_kr_stock_universe()
    records: list[dict] = []

    for row in universe.to_dict('records'):
        try:
            code = str(row['code']).zfill(6)
            hist = _prepare_history(get_kr_stock_history(code).copy())
            if len(hist) < 65:
                continue

            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            daily_close = float(latest['close'])
            quote = try_kr_realtime_quote(code)
            quote_ok = bool(quote.get('ok'))
            price = float(quote['price']) if quote_ok and quote.get('price') else daily_close
            ma20 = float(latest['ma20'])
            ma60 = float(latest['ma60'])
            ma120 = float(latest['ma120'])
            atr14 = float(latest['atr14'])
            if min(price, ma20, ma60, atr14) <= 0:
                continue

            trade_value = float(latest.get('trade_value', daily_close * latest['volume']))
            if quote_ok and quote.get('trade_value'):
                trade_value = float(quote['trade_value'])
            volume_ratio = _ratio(float(latest['volume']), float(latest['volume_ma20']))
            value_ratio = _ratio(trade_value, float(latest['trade_value_ma20']))
            high20 = float(hist['high'].iloc[-21:-1].max())
            high60 = float(hist['high'].iloc[-61:-1].max())
            low10 = float(hist['low'].tail(10).min())
            drawdown60 = price / high60 - 1.0 if high60 else 0.0
            gap_ma20 = price / ma20 - 1.0
            ret5 = price / float(hist['close'].iloc[-6]) - 1.0 if len(hist) > 6 else momentum(hist['close'], 5)
            ret20 = price / float(hist['close'].iloc[-21]) - 1.0 if len(hist) > 21 else momentum(hist['close'], 20)
            ret60 = price / float(hist['close'].iloc[-61]) - 1.0 if len(hist) > 61 else momentum(hist['close'], 60)

            setup = _setup(price, float(prev['close']), float(prev['ma20']), ma20, ma60, ma120, high20, high60, drawdown60)
            score = _score(price, ma20, ma60, ma120, high20, high60, volume_ratio, value_ratio, trade_value, ret5, ret20, ret60, drawdown60, gap_ma20, setup, rules.max_gap_ma20_pct)
            if score < rules.score_threshold:
                continue

            stop = _stop(price, ma20, ma60, low10, atr14)
            if stop >= price:
                stop = price * 0.96
            risk_pct = (price - stop) / price * 100.0
            if risk_pct < rules.min_risk_pct or risk_pct > rules.max_risk_pct:
                continue

            entry = _entry(price, high20, ma20, setup)
            if entry / price - 1.0 > rules.max_entry_gap_pct / 100.0:
                continue

            risk_per_share = max(entry - stop, price * 0.01)
            risk_budget = settings.account_equity_krw * settings.risk_per_trade_pct / 100.0
            shares = math.floor(risk_budget / risk_per_share)
            position_size = min(settings.account_equity_krw * 0.25, max(0, shares * entry))
            target1 = entry + risk_per_share * 2.0
            target2 = entry + risk_per_share * 3.2
            history_last_date = _format_date(latest.get('date'))

            records.append({
                'code': code,
                'name': row['name'],
                'sector': row.get('sector', '기타'),
                'current_price': round(price),
                'price_basis': 'realtime_quote' if quote_ok else 'last_daily_close',
                'price_timestamp': quote.get('timestamp_kst') if quote_ok else history_last_date,
                'history_last_date': history_last_date,
                'quote_source': quote.get('source'),
                'quote_ok': quote_ok,
                'quote_error': quote.get('error'),
                'score': round(score, 1),
                'entry': round(entry),
                'stop_loss': round(stop),
                'target1': round(target1),
                'target2': round(target2),
                'risk_pct': round(risk_pct, 2),
                'position_size_krw': round(position_size),
                'holding_period': '당일~10일',
                'strategy_type': setup,
                'volume_ratio_20d': round(volume_ratio, 2),
                'trade_value_ratio_20d': round(value_ratio, 2),
                'trade_value_krw': round(trade_value),
                'momentum_5d_pct': round(ret5 * 100, 2),
                'momentum_20d_pct': round(ret20 * 100, 2),
                'momentum_60d_pct': round(ret60 * 100, 2),
                'drawdown_60d_pct': round(drawdown60 * 100, 2),
                'reason': _reason(setup, volume_ratio, value_ratio, ret20, drawdown60, gap_ma20, rules.max_gap_ma20_pct),
                'failure_condition': _failure_condition(setup),
                'data_source': 'yahoo_daily_plus_quote' if quote_ok else 'yahoo_ks_kq_daily',
            })
        except Exception:
            continue

    if not records:
        return pd.DataFrame(columns=COLUMNS)
    ranked = pd.DataFrame(records).sort_values(['score', 'trade_value_krw'], ascending=[False, False]).reset_index(drop=True)
    return _select_diversified(ranked, max_items=5)


def _prepare_history(hist: pd.DataFrame) -> pd.DataFrame:
    hist = hist.sort_values('date').reset_index(drop=True)
    for window in (5, 20, 60, 120):
        hist[f'ma{window}'] = hist['close'].rolling(window).mean()
    hist['volume_ma20'] = hist['volume'].rolling(20).mean()
    hist['trade_value'] = hist.get('trade_value', hist['close'] * hist['volume'])
    hist['trade_value_ma20'] = hist['trade_value'].rolling(20).mean()
    hist['atr14'] = atr(hist)
    return hist.dropna().reset_index(drop=True)


def _setup(price: float, prev_close: float, prev_ma20: float, ma20: float, ma60: float, ma120: float, high20: float, high60: float, drawdown60: float) -> str:
    aligned = price > ma20 > ma60 > ma120
    if aligned and price >= high20 * 0.995 and price >= high60 * 0.985:
        return 'breakout'
    if prev_close <= prev_ma20 and price > ma20 and price > ma60 and -0.18 <= drawdown60 <= -0.035:
        return 'pullback_reversal'
    if aligned and price > high20 * 0.97:
        return 'trend_continuation'
    return 'watch'


def _score(price: float, ma20: float, ma60: float, ma120: float, high20: float, high60: float, volume_ratio: float, value_ratio: float, trade_value: float, ret5: float, ret20: float, ret60: float, drawdown60: float, gap_ma20: float, setup: str, max_gap_ma20_pct: float) -> float:
    liquidity = score_clip((trade_value / settings.min_kr_trade_value_krw) * 12, 0, 18)
    volume = score_clip((volume_ratio - 1.0) * 18, 0, 24) + score_clip((value_ratio - 1.0) * 8, 0, 10)
    trend = (8 if price > ma20 else 0) + (8 if price > ma60 else 0) + (7 if ma20 > ma60 else 0) + (5 if ma60 > ma120 else 0)
    breakout = score_clip((price / high20 - 0.97) * 500, 0, 18) + score_clip((price / high60 - 0.95) * 300, 0, 14)
    strength = score_clip(ret5 * 160, -8, 12) + score_clip(ret20 * 100, -10, 18) + score_clip(ret60 * 55, -8, 14)
    setup_bonus = {'breakout': 12, 'pullback_reversal': 10, 'trend_continuation': 7, 'watch': 0}[setup]
    penalty = 0.0
    if gap_ma20 > max_gap_ma20_pct / 100:
        penalty += 18
    if price < ma60:
        penalty += 14
    if ret5 < -0.06:
        penalty += 8
    if drawdown60 < -0.25:
        penalty += 10
    return score_clip(35 + liquidity + volume + trend + breakout + strength + setup_bonus - penalty)


def _entry(price: float, high20: float, ma20: float, setup: str) -> float:
    if setup == 'breakout':
        return max(price, high20 * 1.002)
    if setup == 'pullback_reversal':
        return max(price, ma20 * 1.005)
    return price


def _stop(price: float, ma20: float, ma60: float, low10: float, atr14: float) -> float:
    atr_line = price - atr14 * 1.45
    structure_line = min(low10 * 0.99, ma20 * 0.97)
    trend_line = ma60 * 0.965 if price > ma60 else price * 0.94
    return max(min(atr_line, structure_line), trend_line)


def _select_diversified(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    selected = []
    used_sectors = set()
    for _, row in ranked.iterrows():
        if row['sector'] not in used_sectors:
            selected.append(row)
            used_sectors.add(row['sector'])
        if len(selected) >= max_items:
            break
    if len(selected) < max_items:
        selected_codes = {x['code'] for x in selected}
        for _, row in ranked.iterrows():
            if row['code'] not in selected_codes:
                selected.append(row)
                selected_codes.add(row['code'])
            if len(selected) >= max_items:
                break
    return pd.DataFrame(selected).reset_index(drop=True)


def _ratio(num: float, den: float) -> float:
    return 0.0 if den <= 0 else num / den


def _format_date(value) -> str:
    if value is None:
        return 'unknown'
    if hasattr(value, 'date'):
        return str(value.date())
    return str(value)


def _reason(setup: str, volume_ratio: float, value_ratio: float, ret20: float, drawdown60: float, gap_ma20: float, max_gap_ma20_pct: float) -> str:
    flags = []
    if setup == 'breakout':
        flags.append('20/60일 고점권 돌파')
    elif setup == 'pullback_reversal':
        flags.append('눌림 후 MA20 회복')
    elif setup == 'trend_continuation':
        flags.append('정배열 추세 지속')
    if volume_ratio >= 1.6:
        flags.append('거래량 증가')
    if value_ratio >= 1.4:
        flags.append('거래대금 증가')
    if ret20 >= 0.08:
        flags.append('20일 상대강도 양호')
    if -0.18 <= drawdown60 <= -0.035:
        flags.append('고점 대비 건전한 조정')
    if gap_ma20 > max_gap_ma20_pct / 100:
        flags.append('단기 과열 주의')
    return ' + '.join(flags) if flags else '점수 기준 통과'


def _failure_condition(setup: str) -> str:
    if setup == 'breakout':
        return '돌파 실패 후 전고점 아래 재이탈 또는 stop_loss 이탈'
    if setup == 'pullback_reversal':
        return 'MA20 재이탈 또는 반등 거래량 소멸'
    if setup == 'trend_continuation':
        return 'MA20 또는 최근 저점 이탈'
    return '점수 하락 또는 stop_loss 이탈'
