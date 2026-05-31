from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings
from data.market_data import get_kr_stock_history, get_kr_stock_universe
from strategies.kr_short_stock import scan_kr_short_stocks
from strategies.metrics import atr

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'
MISSED_SURGE_PATH = REPORT_DIR / 'missed_kr_surges_latest.json'


def audit_missed_kr_surges(write: bool = True, top_n: int = 30) -> dict:
    now = datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
    selected = scan_kr_short_stocks()
    selected_codes = set(selected.get('code', pd.Series(dtype=str)).astype(str).str.zfill(6).tolist()) if not selected.empty else set()
    universe = get_kr_stock_universe()
    rows: list[dict] = []

    for item in universe.to_dict('records'):
        code = str(item.get('code') or '').zfill(6)
        if not code or code in selected_codes:
            continue
        try:
            hist = _prepare_history(get_kr_stock_history(code).copy())
            if len(hist) < 65:
                continue
            latest = hist.iloc[-1]
            price = float(latest['close'])
            ma20 = float(latest['ma20'])
            ma60 = float(latest['ma60'])
            trade_value = float(latest.get('trade_value', price * latest['volume']))
            volume_ratio = _ratio(float(latest['volume']), float(latest['volume_ma20']))
            value_ratio = _ratio(trade_value, float(latest['trade_value_ma20']))
            ret1 = price / float(hist['close'].iloc[-2]) - 1.0 if len(hist) > 2 else 0.0
            ret5 = price / float(hist['close'].iloc[-6]) - 1.0 if len(hist) > 6 else 0.0
            ret20 = price / float(hist['close'].iloc[-21]) - 1.0 if len(hist) > 21 else 0.0
            gap_ma20 = price / ma20 - 1.0 if ma20 > 0 else 0.0
            surge_score = _surge_score(ret1, ret5, ret20, volume_ratio, value_ratio, trade_value, item)
            if surge_score < 55:
                continue
            rows.append({
                'code': code,
                'name': item.get('name', ''),
                'sector': item.get('sector', '기타'),
                'market': item.get('market', ''),
                'surge_score': round(surge_score, 1),
                'close': round(price),
                'ret_1d_pct': round(ret1 * 100, 2),
                'ret_5d_pct': round(ret5 * 100, 2),
                'ret_20d_pct': round(ret20 * 100, 2),
                'gap_ma20_pct': round(gap_ma20 * 100, 2),
                'volume_ratio_20d': round(volume_ratio, 2),
                'trade_value_ratio_20d': round(value_ratio, 2),
                'trade_value_krw': round(trade_value),
                'sector_rank': item.get('sector_rank'),
                'sector_strength_score': round(float(item.get('sector_strength_score') or 0.0), 1),
                'market_rotation_score': round(float(item.get('market_rotation_score') or 0.0), 1),
                'probable_miss_reason': _miss_reason(price, ma20, ma60, ret5, ret20, gap_ma20, volume_ratio, value_ratio),
            })
        except Exception as exc:
            continue

    rows = sorted(rows, key=lambda x: (x['surge_score'], x['trade_value_krw']), reverse=True)[:top_n]
    payload = {
        'schema_version': 1,
        'created_at_kst': now,
        'selected_count': len(selected_codes),
        'missed_surge_count': len(rows),
        'items': rows,
        'interpretation': 'These are liquid KR stocks that surged but were not selected by the final recommendation list. Use this report to tune prefilters, score penalties, and max_items.',
    }
    if write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        MISSED_SURGE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return payload


def _prepare_history(hist: pd.DataFrame) -> pd.DataFrame:
    hist = hist.sort_values('date').reset_index(drop=True)
    for window in (20, 60):
        hist[f'ma{window}'] = hist['close'].rolling(window).mean()
    hist['volume_ma20'] = hist['volume'].rolling(20).mean()
    hist['trade_value'] = hist.get('trade_value', hist['close'] * hist['volume'])
    hist['trade_value_ma20'] = hist['trade_value'].rolling(20).mean()
    hist['atr14'] = atr(hist)
    return hist.dropna().reset_index(drop=True)


def _surge_score(ret1: float, ret5: float, ret20: float, volume_ratio: float, value_ratio: float, trade_value: float, item: dict) -> float:
    sector_rank = int(item.get('sector_rank') or 99)
    market_rotation = float(item.get('market_rotation_score') or 0.0)
    score = 0.0
    score += min(max(ret1 * 100.0, 0.0), 12.0) * 2.0
    score += min(max(ret5 * 100.0, 0.0), 25.0) * 1.4
    score += min(max(ret20 * 100.0, 0.0), 40.0) * 0.8
    score += min(max(volume_ratio - 1.0, 0.0), 4.0) * 6.0
    score += min(max(value_ratio - 1.0, 0.0), 4.0) * 6.0
    score += min(trade_value / max(settings.min_kr_trade_value_krw, 1.0), 8.0) * 2.5
    if sector_rank <= 5:
        score += 8.0
    if market_rotation >= 65:
        score += 8.0
    return min(score, 100.0)


def _miss_reason(price: float, ma20: float, ma60: float, ret5: float, ret20: float, gap_ma20: float, volume_ratio: float, value_ratio: float) -> str:
    reasons = []
    if price <= ma60:
        reasons.append('MA60 아래라 추세 필터에서 약화')
    if gap_ma20 > 0.12:
        reasons.append('MA20 이격 과열 패널티 가능')
    if ret5 > 0.08 or ret20 > 0.15:
        reasons.append('이미 급등 후라 기존 눌림목 선호 점수식에서 불리')
    if volume_ratio < 1.3 and value_ratio < 1.3:
        reasons.append('거래량/거래대금 확증 부족')
    if not reasons:
        reasons.append('최종 후보 수/섹터 분산/점수 경쟁에서 탈락 가능')
    return ' / '.join(reasons)


def _ratio(num: float, den: float) -> float:
    return 0.0 if den <= 0 else num / den


if __name__ == '__main__':
    print(json.dumps(audit_missed_kr_surges(), ensure_ascii=False, indent=2, default=str))
