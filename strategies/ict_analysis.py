from __future__ import annotations

import pandas as pd


def analyze_ict_structure(history: pd.DataFrame, current_price: float | None = None) -> dict:
    required = {'open', 'high', 'low', 'close'}
    if history is None or history.empty or not required.issubset(history.columns):
        return _empty()
    frame = history.tail(160).copy().reset_index(drop=True)
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
    frame = frame.dropna(subset=list(required)).reset_index(drop=True)
    if len(frame) < 20:
        return _empty()

    highs = []
    lows = []
    for i in range(2, len(frame) - 2):
        window = frame.iloc[i - 2:i + 3]
        if float(frame.iloc[i]['high']) >= float(window['high'].max()):
            highs.append(float(frame.iloc[i]['high']))
        if float(frame.iloc[i]['low']) <= float(window['low'].min()):
            lows.append(float(frame.iloc[i]['low']))

    last = frame.iloc[-1]
    price = float(current_price or last['close'])
    last_high = highs[-1] if highs else None
    prior_high = highs[-2] if len(highs) > 1 else None
    last_low = lows[-1] if lows else None
    prior_low = lows[-2] if len(lows) > 1 else None

    bullish_structure = all(v is not None for v in (last_high, prior_high, last_low, prior_low)) and last_high > prior_high and last_low > prior_low
    bearish_structure = all(v is not None for v in (last_high, prior_high, last_low, prior_low)) and last_high < prior_high and last_low < prior_low
    structure = 'BULLISH_HH_HL' if bullish_structure else 'BEARISH_LH_LL' if bearish_structure else 'RANGE_OR_TRANSITION'

    if last_high is not None and price > last_high:
        event = 'CHOCH_UP' if bearish_structure else 'BOS_UP'
    elif last_low is not None and price < last_low:
        event = 'CHOCH_DOWN' if bullish_structure else 'BOS_DOWN'
    else:
        event = 'NO_CONFIRMED_BREAK'

    if last_low is not None and float(last['low']) < last_low and price > last_low:
        sweep = 'SELL_SIDE_SWEEP'
    elif last_high is not None and float(last['high']) > last_high and price < last_high:
        sweep = 'BUY_SIDE_SWEEP'
    else:
        sweep = 'NONE'

    fvg = _latest_fvg(frame)
    dealing = frame.tail(60)
    range_high = float(dealing['high'].max())
    range_low = float(dealing['low'].min())
    midpoint = (range_high + range_low) / 2.0
    span = max(range_high - range_low, 1e-9)
    location_ratio = (price - range_low) / span
    location = 'DISCOUNT' if location_ratio < 0.45 else 'PREMIUM' if location_ratio > 0.55 else 'EQUILIBRIUM'

    points = 0
    points += 2 if bullish_structure else -2 if bearish_structure else 0
    points += 2 if event in {'BOS_UP', 'CHOCH_UP'} else -2 if event in {'BOS_DOWN', 'CHOCH_DOWN'} else 0
    points += 2 if sweep == 'SELL_SIDE_SWEEP' else -2 if sweep == 'BUY_SIDE_SWEEP' else 0
    points += 1 if location == 'DISCOUNT' else -1 if location == 'PREMIUM' else 0
    points += 1 if fvg['direction'] == 'BULLISH' else -1 if fvg['direction'] == 'BEARISH' else 0

    bias = 'BULLISH' if points >= 3 else 'BEARISH' if points <= -3 else 'NEUTRAL'
    adjustment = 5.0 if bias == 'BULLISH' else -8.0 if bias == 'BEARISH' else 0.0
    if bias == 'BULLISH':
        entry_low, entry_high = (fvg['low'], fvg['high']) if fvg['direction'] == 'BULLISH' else (range_low + span * 0.35, midpoint)
        invalidation = last_low or range_low
    elif bias == 'BEARISH':
        entry_low, entry_high = (fvg['low'], fvg['high']) if fvg['direction'] == 'BEARISH' else (midpoint, range_low + span * 0.65)
        invalidation = last_high or range_high
    else:
        entry_low = entry_high = invalidation = None

    return {
        'bias': bias,
        'structure': structure,
        'structure_event': event,
        'liquidity_event': sweep,
        'fair_value_gap': fvg['text'],
        'dealing_range_location': location,
        'preferred_entry_low': _round(entry_low),
        'preferred_entry_high': _round(entry_high),
        'invalidation': _round(invalidation),
        'score_adjustment': adjustment,
        'summary': f'ICT {bias} | {structure} | {event} | {sweep} | {location} | FVG={fvg["text"]}',
    }


def _latest_fvg(frame: pd.DataFrame) -> dict:
    for i in range(len(frame) - 1, max(1, len(frame) - 45), -1):
        old = frame.iloc[i - 2]
        current = frame.iloc[i]
        if float(current['low']) > float(old['high']):
            low, high = float(old['high']), float(current['low'])
            return {'direction': 'BULLISH', 'low': low, 'high': high, 'text': f'BULLISH {low:.2f}~{high:.2f}'}
        if float(current['high']) < float(old['low']):
            low, high = float(current['high']), float(old['low'])
            return {'direction': 'BEARISH', 'low': low, 'high': high, 'text': f'BEARISH {low:.2f}~{high:.2f}'}
    return {'direction': 'NONE', 'low': 0.0, 'high': 0.0, 'text': 'NONE'}


def _round(value):
    return round(float(value), 2) if value is not None else None


def _empty() -> dict:
    return {
        'bias': 'UNKNOWN',
        'structure': 'INSUFFICIENT_DATA',
        'structure_event': 'NONE',
        'liquidity_event': 'NONE',
        'fair_value_gap': 'NONE',
        'dealing_range_location': 'UNKNOWN',
        'preferred_entry_low': None,
        'preferred_entry_high': None,
        'invalidation': None,
        'score_adjustment': 0.0,
        'summary': 'ICT data insufficient',
    }
