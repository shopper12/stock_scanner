from __future__ import annotations

import math

import pandas as pd
from config import settings
from data.market_data import get_kr_stock_history, get_kr_stock_universe
from data.realtime_price import try_kr_realtime_quote
from strategies.kr_short_rules import load_kr_short_rules
from strategies.metrics import atr, momentum, score_clip


COLUMNS = [
    'code', 'name', 'sector', 'market', 'sector_rank', 'sector_strength_score', 'market_rotation_score',
    'current_price', 'price_basis', 'price_timestamp', 'history_last_date', 'quote_source', 'quote_ok',
    'quote_error', 'score', 'entry', 'stop_loss', 'target1', 'target2', 'risk_pct', 'position_size_krw',
    'holding_period', 'strategy_type', 'volume_ratio_20d', 'trade_value_ratio_20d', 'trade_value_krw',
    'change_pct_today', 'momentum_5d_pct', 'momentum_20d_pct', 'momentum_60d_pct', 'drawdown_60d_pct',
    'drawdown_52w_pct', 'rsi14', 'reason', 'failure_condition', 'data_source'
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
            if quote_ok and quote.get('price'):
                price = float(quote['price'])
                price_basis = 'realtime_quote'
                data_source = 'pykrx_daily_plus_quote'
            else:
                price = daily_close
                price_basis = 'last_daily_close'
                data_source = 'pykrx_daily'
            ma20 = float(latest['ma20'])
            ma60 = float(latest['ma60'])
            ma120 = float(latest['ma120'])
            ma200 = float(latest['ma200'])
            atr14 = float(latest['atr14'])
            rsi14 = _rsi14(hist['close'])
            if min(price, ma20, ma60, ma120, ma200, atr14) <= 0:
                continue

            trade_value = float(latest.get('trade_value', daily_close * latest['volume']))
            if quote_ok and quote.get('trade_value'):
                trade_value = float(quote['trade_value'])
            volume_ratio = _ratio(float(latest['volume']), float(latest['volume_ma20']))
            value_ratio = _ratio(trade_value, float(latest['trade_value_ma20']))
            high20 = float(hist['high'].iloc[-21:-1].max())
            high60 = float(hist['high'].iloc[-61:-1].max())
            high252 = float(hist['high'].tail(252).max()) if len(hist) >= 252 else float(hist['high'].max())
            low10 = float(hist['low'].tail(10).min())
            drawdown60 = price / high60 - 1.0 if high60 else 0.0
            drawdown52w = price / high252 - 1.0 if high252 else 0.0
            gap_ma20 = price / ma20 - 1.0
            ret5 = price / float(hist['close'].iloc[-6]) - 1.0 if len(hist) > 6 else momentum(hist['close'], 5)
            ret20 = price / float(hist['close'].iloc[-21]) - 1.0 if len(hist) > 21 else momentum(hist['close'], 20)
            ret60 = price / float(hist['close'].iloc[-61]) - 1.0 if len(hist) > 61 else momentum(hist['close'], 60)
            ret252 = price / float(hist['close'].iloc[-252]) - 1.0 if len(hist) > 252 else momentum(hist['close'], min(252, len(hist) - 1))

            sector_strength = float(row.get('sector_strength_score') or 0.0)
            sector_rank = int(row.get('sector_rank') or 99)
            market_rotation = float(row.get('market_rotation_score') or 0.0)
            change_today = float(row.get('change_pct_today') or 0.0)

            setup = _setup(price, float(prev['close']), float(prev['ma20']), ma20, ma60, ma120, ma200, high20, high60, drawdown60, drawdown52w, high252, ret5, ret20, volume_ratio, value_ratio, trade_value, sector_rank, market_rotation, change_today)
            score = _score(price, ma20, ma60, ma120, ma200, high20, high60, volume_ratio, value_ratio, trade_value, ret5, ret20, ret60, ret252, drawdown60, drawdown52w, gap_ma20, rsi14, setup, rules.max_gap_ma20_pct, sector_strength, sector_rank, market_rotation, change_today)
            threshold = max(58.0 if settings.bull_market_mode else 55.0, rules.score_threshold + (3.0 if settings.bull_market_mode else 0.0))
            if setup == 'theme_repricing_breakout':
                threshold = min(threshold, 54.0)
            if score < threshold:
                continue

            entry = _entry(price, high20, ma20, setup, high252)
            if entry / price - 1.0 > rules.max_entry_gap_pct / 100.0:
                continue

            stop = _stop(price, ma20, ma60, ma200, low10, atr14, setup)
            if stop >= min(price, entry):
                stop = min(price, entry) * 0.96
            risk_pct = (entry - stop) / entry * 100.0
            if setup == 'theme_repricing_breakout' and risk_pct <= 15.0:
                pass
            elif risk_pct < rules.min_risk_pct or risk_pct > rules.max_risk_pct:
                continue

            risk_per_share = max(entry - stop, entry * 0.01)
            risk_budget = settings.account_equity_krw * settings.risk_per_trade_pct / 100.0
            shares = math.floor(risk_budget / risk_per_share)
            position_size = min(settings.account_equity_krw * _max_position_pct(setup), max(0, shares * entry))
            target_base = max(entry, price)
            target1 = target_base * (1.06 if setup == 'theme_repricing_breakout' else 1.08)
            target2 = target_base * (1.13 if setup == 'theme_repricing_breakout' else 1.16)
            history_last_date = _format_date(latest.get('date'))

            records.append({
                'code': code,
                'name': row['name'],
                'sector': row.get('sector', '기타'),
                'market': row.get('market', 'UNKNOWN'),
                'sector_rank': sector_rank,
                'sector_strength_score': round(sector_strength, 1),
                'market_rotation_score': round(market_rotation, 1),
                'current_price': round(price),
                'price_basis': price_basis,
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
                'change_pct_today': round(change_today, 2),
                'momentum_5d_pct': round(ret5 * 100, 2),
                'momentum_20d_pct': round(ret20 * 100, 2),
                'momentum_60d_pct': round(ret60 * 100, 2),
                'drawdown_60d_pct': round(drawdown60 * 100, 2),
                'drawdown_52w_pct': round(drawdown52w * 100, 2),
                'rsi14': round(rsi14, 1),
                'reason': _reason(row.get('sector', '기타'), setup, volume_ratio, value_ratio, ret20, drawdown60, drawdown52w, gap_ma20, rsi14, rules.max_gap_ma20_pct, sector_rank, sector_strength, market_rotation, change_today),
                'failure_condition': _failure_condition(setup),
                'data_source': data_source,
            })
        except Exception:
            continue

    if not records:
        return pd.DataFrame(columns=COLUMNS)
    ranked = pd.DataFrame(records).sort_values(['score', 'market_rotation_score', 'trade_value_krw'], ascending=[False, False, False]).reset_index(drop=True)
    return _select_diversified(ranked, max_items=8)


def _prepare_history(hist: pd.DataFrame) -> pd.DataFrame:
    hist = hist.sort_values('date').reset_index(drop=True)
    for window in (5, 20, 60, 120, 200):
        hist[f'ma{window}'] = hist['close'].rolling(window).mean()
    hist['volume_ma20'] = hist['volume'].rolling(20).mean()
    hist['trade_value'] = hist.get('trade_value', hist['close'] * hist['volume'])
    hist['trade_value_ma20'] = hist['trade_value'].rolling(20).mean()
    hist['atr14'] = atr(hist)
    return hist.dropna().reset_index(drop=True)


def _rsi14(close: pd.Series) -> float:
    if len(close) < 15:
        return 50.0
    changes = close.astype(float).diff().dropna().tail(14)
    gains = changes.clip(lower=0).mean()
    losses = (-changes.clip(upper=0)).mean()
    if losses <= 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return float(100.0 - (100.0 / (1.0 + rs)))


def _setup(price: float, prev_close: float, prev_ma20: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, high60: float, drawdown60: float, drawdown52w: float, high252: float | None = None, ret5: float = 0.0, ret20: float = 0.0, volume_ratio: float = 0.0, value_ratio: float = 0.0, trade_value: float = 0.0, sector_rank: int = 99, market_rotation: float = 0.0, change_today: float = 0.0) -> str:
    aligned = price > ma20 > ma60 > ma120 and price > ma200
    theme_repricing = (
        price > ma20
        and price > ma60
        and ret5 >= 0.045
        and ret20 >= 0.075
        and (volume_ratio >= 1.35 or value_ratio >= 1.35)
        and trade_value >= settings.min_kr_trade_value_krw * 5.0
        and (change_today >= 2.0 or market_rotation >= 65.0 or sector_rank <= 5)
        and gap_ma20_safe(price, ma20, limit=0.22)
    )
    if theme_repricing:
        return 'theme_repricing_breakout'
    if high252 and price >= high252 * 0.999 and price > ma20 and price > ma60 and price > ma200:
        return 'new_52w_high_breakout'
    if -0.08 <= drawdown52w <= -0.03 and price > ma20:
        return 'first_pullback_after_high'
    if aligned and price >= high20 * 0.995 and price >= high60 * 0.985:
        return 'breakout'
    if prev_close <= prev_ma20 and price > ma20 and price > ma60 and price > ma200 and -0.18 <= drawdown60 <= -0.035:
        return 'pullback_reversal'
    if aligned and price > high20 * 0.97:
        return 'trend_continuation'
    return 'watch'


def gap_ma20_safe(price: float, ma20: float, limit: float) -> bool:
    return ma20 > 0 and price / ma20 - 1.0 <= limit


def _score(price: float, ma20: float, ma60: float, ma120: float, ma200: float, high20: float, high60: float, volume_ratio: float, value_ratio: float, trade_value: float, ret5: float, ret20: float, ret60: float, ret252: float, drawdown60: float, drawdown52w: float, gap_ma20: float, rsi14: float, setup: str, max_gap_ma20_pct: float, sector_strength: float, sector_rank: int, market_rotation: float, change_today: float) -> float:
    score = 50.0

    score += 6.0 if price > ma200 else -8.0
    score += 4.0 if price > ma60 else -3.0
    score += 4.0 if price > ma20 else -2.0
    score += 3.0 if ma20 > ma60 else -1.5
    score += 3.0 if ma60 > ma120 else -1.5

    score += score_clip(ret252 * 15.0, -8.0, 10.0)
    score += score_clip(ret20 * 30.0, -5.0, 8.0)
    score += score_clip(ret60 * 18.0, -5.0, 6.0)
    score += score_clip(ret5 * 18.0, -3.0, 3.0)

    if setup == 'theme_repricing_breakout':
        score += 10.0
        score += score_clip((ret5 - 0.04) * 80.0, 0.0, 6.0)
        score += score_clip((ret20 - 0.07) * 45.0, 0.0, 6.0)
        score += score_clip((value_ratio - 1.3) * 5.0, 0.0, 5.0)

    if -0.18 <= drawdown60 <= -0.05 and price > ma60:
        score += 5.0
    if -0.15 <= drawdown52w <= -0.05 and price > ma20:
        score += 6.0
    if drawdown52w > -0.03 and setup not in {'new_52w_high_breakout', 'theme_repricing_breakout'}:
        score -= 8.0
    score += score_clip(drawdown52w * 15.0, -8.0, 0.0)

    if 45 <= rsi14 <= 62:
        score += 6.0
    elif setup == 'theme_repricing_breakout' and 72 < rsi14 <= 84:
        score -= 2.0
    elif rsi14 > 80:
        score -= 15.0
    elif rsi14 > 72:
        score -= 7.0
    elif rsi14 < 35:
        score -= 5.0

    liquidity = score_clip((trade_value / settings.min_kr_trade_value_krw) * 5.0, 0.0, 8.0)
    volume = score_clip((volume_ratio - 1.0) * 6.0, 0.0, 6.0)
    value = score_clip((value_ratio - 1.0) * 5.0, 0.0, 6.0)
    score += liquidity + volume + value

    if sector_strength > 0:
        score += score_clip(sector_strength / 100.0 * 8.0, 0.0, 8.0)
    if market_rotation > 0:
        score += score_clip(market_rotation / 100.0 * 5.0, 0.0, 5.0)
    if sector_rank <= 3:
        score += 3.0
    elif sector_rank <= 7:
        score += 1.5
    if change_today >= 3.0:
        score += 2.0
    elif change_today < -1.0:
        score -= 3.0

    if setup == 'theme_repricing_breakout':
        score += 6.0
    elif setup == 'new_52w_high_breakout':
        score += 3.0
    elif setup == 'first_pullback_after_high':
        score += 8.0
    elif setup == 'pullback_reversal':
        score += 7.0
    elif setup == 'breakout':
        score -= 3.0
    elif setup == 'trend_continuation':
        score -= 2.0

    if gap_ma20 > max_gap_ma20_pct / 100.0 and setup != 'theme_repricing_breakout':
        score -= 10.0
    elif setup == 'theme_repricing_breakout' and gap_ma20 > 0.22:
        score -= 8.0
    if ret5 < -0.06:
        score -= 6.0
    if drawdown60 < -0.25:
        score -= 8.0
    return score_clip(score, 0.0, 100.0)


def _entry(price: float, high20: float, ma20: float, setup: str, high252: float | None = None) -> float:
    if setup == 'new_52w_high_breakout' and high252:
        return max(price, high252 * 1.001)
    if setup == 'theme_repricing_breakout':
        return price
    if setup == 'breakout':
        return max(price * 1.005, high20 * 1.003)
    if setup in {'pullback_reversal', 'first_pullback_after_high'}:
        return max(price, ma20 * 1.003)
    return price


def _stop(price: float, ma20: float, ma60: float, ma200: float, low10: float, atr14: float, setup: str = '') -> float:
    atr_multiple = 2.1 if setup == 'theme_repricing_breakout' else 1.8 if setup in {'new_52w_high_breakout', 'trend_continuation'} else 1.45
    atr_line = price - atr14 * atr_multiple
    structure_line = min(low10 * 0.99, ma20 * (0.955 if setup == 'theme_repricing_breakout' else 0.97))
    trend_line = ma60 * 0.955 if setup == 'theme_repricing_breakout' and price > ma60 else ma60 * 0.965 if price > ma60 else price * 0.94
    long_trend_line = ma200 * 0.97 if price > ma200 else price * 0.92
    return max(min(atr_line, structure_line), trend_line, long_trend_line)


def _max_position_pct(setup: str) -> float:
    base = {
        'theme_repricing_breakout': 0.24,
        'new_52w_high_breakout': 0.32,
        'first_pullback_after_high': 0.30,
        'breakout': 0.28,
        'pullback_reversal': 0.25,
        'trend_continuation': 0.22,
    }.get(setup, 0.20)
    if settings.bull_market_mode:
        return min(base + 0.05, 0.40)
    return base


def _select_diversified(ranked: pd.DataFrame, max_items: int) -> pd.DataFrame:
    selected = []
    selected_codes = set()
    priority = ranked[ranked['strategy_type'].isin(['theme_repricing_breakout', 'new_52w_high_breakout'])]
    for _, row in priority.head(3).iterrows():
        selected.append(row)
        selected_codes.add(row['code'])
        if len(selected) >= max_items:
            return pd.DataFrame(selected).reset_index(drop=True)

    used_sectors = {row['sector'] for row in selected}
    for _, row in ranked.iterrows():
        if row['code'] in selected_codes:
            continue
        if row['sector'] not in used_sectors:
            selected.append(row)
            selected_codes.add(row['code'])
            used_sectors.add(row['sector'])
        if len(selected) >= max_items:
            break
    if len(selected) < max_items:
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


def _reason(sector: str, setup: str, volume_ratio: float, value_ratio: float, ret20: float, drawdown60: float, drawdown52w: float, gap_ma20: float, rsi14: float, max_gap_ma20_pct: float, sector_rank: int, sector_strength: float, market_rotation: float, change_today: float) -> str:
    flags = [f'{sector}(섹터 {sector_rank}위/{sector_strength:.0f}, 종목당일 {change_today:.1f}%, RSI {rsi14:.0f})']
    if market_rotation >= 70:
        flags.append('시장 자금 유입 상위')
    if setup == 'theme_repricing_breakout':
        flags.append('대형주/테마 재평가 급등 감지')
    elif setup == 'new_52w_high_breakout':
        flags.append('52주 신고가 돌파')
    elif setup == 'breakout':
        flags.append('20/60일 고점권 돌파')
    elif setup == 'pullback_reversal':
        flags.append('눌림 후 MA20 회복')
    elif setup == 'first_pullback_after_high':
        flags.append('신고가 후 3~8% 첫 눌림 재상승')
    elif setup == 'trend_continuation':
        flags.append('MA200 위 정배열 추세 지속')
    if volume_ratio >= 1.6:
        flags.append('거래량 증가')
    if value_ratio >= 1.4:
        flags.append('거래대금 증가')
    if ret20 >= 0.08:
        flags.append('20일 상대강도 양호')
    if -0.18 <= drawdown60 <= -0.035:
        flags.append('고점 대비 건전한 조정')
    if drawdown52w > -0.03 and setup not in {'new_52w_high_breakout', 'theme_repricing_breakout'}:
        flags.append('52주 고점 근접: 저항 주의')
    if gap_ma20 > max_gap_ma20_pct / 100:
        flags.append('단기 과열 주의')
    return ' + '.join(flags)


def _failure_condition(setup: str) -> str:
    if setup == 'theme_repricing_breakout':
        return '급등일 저가 또는 MA20 이탈, 거래대금 급감 시 무효'
    if setup == 'new_52w_high_breakout':
        return '신고가 아래로 재이탈 또는 stop_loss 이탈'
    if setup == 'breakout':
        return '돌파 실패 후 전고점 아래 재이탈 또는 stop_loss 이탈'
    if setup == 'pullback_reversal':
        return 'MA20 재이탈 또는 반등 거래량 소멸'
    if setup == 'first_pullback_after_high':
        return 'MA20 재이탈 또는 신고가 재돌파 실패'
    if setup == 'trend_continuation':
        return 'MA20 또는 최근 저점 이탈'
    return '점수 하락 또는 stop_loss 이탈'
