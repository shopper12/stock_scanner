from __future__ import annotations

import json
import math
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from config import settings
from data import mock_data
from data.market_data import get_kr_stock_history, _infer_sector, _recent_kr_dates
from data.realtime_price import try_kr_realtime_quote
from strategies.kr_short_rules import load_kr_short_rules
from strategies.kr_short_stock import _entry, _failure_condition, _format_date, _max_position_pct, _prepare_history, _ratio, _reason, _rsi14, _score, _setup, _stop
from strategies.metrics import momentum

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'

KR_STOCK_ALIASES = {
    '삼전': '005930',
    '삼성전자': '005930',
    '삼성전자보통주': '005930',
    '삼전우': '005935',
    '삼성전자우': '005935',
    '삼성전자우선주': '005935',
    '하닉': '000660',
    '하이닉스': '000660',
    'sk하이닉스': '000660',
    '에스케이하이닉스': '000660',
    '현차': '005380',
    '현대차': '005380',
    '현대자동차': '005380',
    '기아차': '000270',
    '기아': '000270',
    '엘지': '003550',
    'lg': '003550',
    'lg지주': '003550',
    '엘지지주': '003550',
    'lg전자': '066570',
    '엘지전자': '066570',
    'lg화학': '051910',
    '엘지화학': '051910',
    '엘화': '051910',
    'lg에너지솔루션': '373220',
    '엘지에너지솔루션': '373220',
    '엔솔': '373220',
    '네이버': '035420',
    'naver': '035420',
    '카카오': '035720',
    '포스코홀딩스': '005490',
    'posco홀딩스': '005490',
    '포홀': '005490',
    '포스코': '005490',
    '삼성바이오': '207940',
    '삼성바이오로직스': '207940',
    '셀트리온': '068270',
    '한화에어로': '012450',
    '한화에어로스페이스': '012450',
    '한에': '012450',
    '두산에너빌리티': '034020',
    '두산중공업': '034020',
    'hd현대중공업': '329180',
    '현대중공업': '329180',
    '한화오션': '042660',
    '대우조선해양': '042660',
    '삼성중공업': '010140',
    '삼중': '010140',
    'sk이노베이션': '096770',
    '에스케이이노베이션': '096770',
    'sk스퀘어': '402340',
    '에스케이스퀘어': '402340',
    'sk텔레콤': '017670',
    '에스케이텔레콤': '017670',
    'kt': '030200',
    '케이티': '030200',
    'kb금융': '105560',
    '국민은행': '105560',
    '신한지주': '055550',
    '신한금융': '055550',
    '하나금융': '086790',
    '하나금융지주': '086790',
    '우리금융': '316140',
    '우리금융지주': '316140',
    '삼성sdi': '006400',
    '삼성에스디아이': '006400',
    '에코프로비엠': '247540',
    '에코비엠': '247540',
    '에코프로': '086520',
    '알테오젠': '196170',
    '리가켐바이오': '141080',
    '레고켐바이오': '141080',
}


def analyze_kr_stock_strategy(query: str) -> dict:
    target = resolve_kr_stock_query(query)
    code = target['code']
    rules = load_kr_short_rules()
    hist = _prepare_history(get_kr_stock_history(code).copy())
    if len(hist) < 65:
        raise RuntimeError(f'insufficient history for {code}: {len(hist)} rows')

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
        raise RuntimeError(f'invalid indicator values for {code}')

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

    setup = _setup(price, float(prev['close']), float(prev['ma20']), ma20, ma60, ma120, ma200, high20, high60, drawdown60, drawdown52w, high252)
    score = _score(price, ma20, ma60, ma120, ma200, high20, high60, volume_ratio, value_ratio, trade_value, ret5, ret20, ret60, ret252, drawdown60, drawdown52w, gap_ma20, rsi14, setup, rules.max_gap_ma20_pct, 0.0, 99, 0.0, 0.0)
    threshold = float(getattr(rules, 'score_threshold', 55.0) or 55.0)

    entry = _entry(price, high20, ma20, setup, high252)
    stop = _stop(price, ma20, ma60, ma200, low10, atr14, setup)
    if stop >= min(price, entry):
        stop = min(price, entry) * 0.96
    risk_pct = (entry - stop) / entry * 100.0 if entry > 0 else 0.0
    target_base = max(entry, price)
    target1 = target_base * 1.08
    target2 = target_base * 1.16
    risk_per_share = max(entry - stop, entry * 0.01)
    risk_budget = settings.account_equity_krw * settings.risk_per_trade_pct / 100.0
    shares = math.floor(risk_budget / risk_per_share)
    position_size = min(settings.account_equity_krw * _max_position_pct(setup), max(0, shares * entry))

    action, action_reason = _action(score, threshold, setup, risk_pct, rules.min_risk_pct, rules.max_risk_pct, entry, price, rules.max_entry_gap_pct)
    history_last_date = _format_date(latest.get('date'))
    reason = _reason(target['sector'], setup, volume_ratio, value_ratio, ret20, drawdown60, drawdown52w, gap_ma20, rsi14, rules.max_gap_ma20_pct, 99, 0.0, 0.0, 0.0)

    return {
        'ok': True,
        'query': query,
        'resolved_by': target.get('resolved_by', 'unknown'),
        'created_at_kst': datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z'),
        'code': code,
        'name': target['name'],
        'market': target.get('market', 'UNKNOWN'),
        'sector': target['sector'],
        'action': action,
        'action_reason': action_reason,
        'score': round(score, 1),
        'threshold': round(threshold, 1),
        'setup': setup,
        'current_price': round(price),
        'price_basis': price_basis,
        'price_timestamp': quote.get('timestamp_kst') if quote_ok else history_last_date,
        'quote_source': quote.get('source'),
        'quote_ok': quote_ok,
        'quote_error': quote.get('error'),
        'entry': round(entry),
        'stop_loss': round(stop),
        'target1': round(target1),
        'target2': round(target2),
        'risk_pct': round(risk_pct, 2),
        'position_size_krw': round(position_size),
        'holding_period': '당일~10일',
        'reason': reason,
        'failure_condition': _failure_condition(setup),
        'data_source': data_source,
        'metrics': {
            'ma20': round(ma20),
            'ma60': round(ma60),
            'ma120': round(ma120),
            'ma200': round(ma200),
            'rsi14': round(rsi14, 1),
            'volume_ratio_20d': round(volume_ratio, 2),
            'trade_value_ratio_20d': round(value_ratio, 2),
            'trade_value_krw': round(trade_value),
            'momentum_5d_pct': round(ret5 * 100, 2),
            'momentum_20d_pct': round(ret20 * 100, 2),
            'momentum_60d_pct': round(ret60 * 100, 2),
            'drawdown_60d_pct': round(drawdown60 * 100, 2),
            'drawdown_52w_pct': round(drawdown52w * 100, 2),
            'gap_ma20_pct': round(gap_ma20 * 100, 2),
        },
    }


def resolve_kr_stock_query(query: str) -> dict:
    q = str(query or '').strip()
    if not q:
        raise ValueError('query is required')
    if q.isdigit():
        code = q.zfill(6)
        name, market = _ticker_name_market(code)
        return {'code': code, 'name': name or code, 'market': market, 'sector': _infer_sector(code, name or ''), 'resolved_by': 'code'}

    q_norm = _normalise_name(q)
    alias_code = KR_STOCK_ALIASES.get(q_norm)
    if alias_code:
        name, market = _ticker_name_market(alias_code)
        return {'code': alias_code, 'name': name or alias_code, 'market': market, 'sector': _infer_sector(alias_code, name or ''), 'resolved_by': 'alias'}

    candidates = _ticker_candidates()
    if not candidates:
        raise ValueError(f'no KR stock candidates available for query={query}')

    for item in candidates:
        item['norm_name'] = _normalise_name(item.get('name', ''))
        item['norm_code'] = str(item.get('code', '')).zfill(6)

    exact = [x for x in candidates if x['norm_name'] == q_norm]
    partial = [x for x in candidates if q_norm and q_norm in x['norm_name']]
    reverse_partial = [x for x in candidates if x['norm_name'] and x['norm_name'] in q_norm]
    fuzzy = _fuzzy_matches(q_norm, candidates) if not (exact or partial or reverse_partial) else []
    matches = exact or partial or reverse_partial or fuzzy
    if not matches:
        sample = ', '.join(x.get('name', '') for x in candidates[:8])
        raise ValueError(f'no KR stock match for query={query}. candidates_sample={sample}')

    matches = sorted(matches, key=lambda x: _match_rank(q_norm, x))
    item = dict(matches[0])
    item.pop('norm_name', None)
    item.pop('norm_code', None)
    item['sector'] = item.get('sector') or _infer_sector(item['code'], item['name'])
    item['resolved_by'] = item.get('resolved_by', 'name_match')
    return item


def _normalise_name(value: str) -> str:
    text = str(value or '').strip().lower()
    text = text.replace('㈜', '').replace('(주)', '').replace('주식회사', '')
    text = text.replace('엘지', 'lg').replace('에스케이', 'sk').replace('케이티', 'kt')
    text = text.replace('포스코', 'posco') if text.startswith('posco') else text
    text = re.sub(r'[\s\-_/.,()\[\]{}·ㆍ]+', '', text)
    text = text.replace('보통주', '').replace('우선주', '우')
    return text


def _match_rank(q_norm: str, item: dict) -> tuple[int, str, str]:
    name_norm = item.get('norm_name', '')
    market = str(item.get('market', ''))
    code = str(item.get('code', ''))
    if name_norm == q_norm:
        return (0, market, code)
    if name_norm.startswith(q_norm):
        return (1, market, code)
    if q_norm in name_norm:
        return (2, market, code)
    if name_norm in q_norm:
        return (3, market, code)
    return (4, market, code)


def _fuzzy_matches(q_norm: str, candidates: list[dict]) -> list[dict]:
    rows = []
    for item in candidates:
        name_norm = item.get('norm_name', '')
        if not name_norm:
            continue
        ratio = SequenceMatcher(None, q_norm, name_norm).ratio()
        if ratio >= 0.72:
            copied = dict(item)
            copied['resolved_by'] = f'fuzzy:{ratio:.2f}'
            rows.append((ratio, copied))
    return [item for _, item in sorted(rows, key=lambda x: x[0], reverse=True)[:8]]


def _ticker_name_market(code: str) -> tuple[str, str]:
    if settings.use_mock_data:
        for row in mock_data.kr_stock_universe().to_dict('records'):
            if str(row.get('code', '')).zfill(6) == code:
                return str(row.get('name', code)), str(row.get('market', 'MOCK'))
    try:
        from pykrx import stock
        name = stock.get_market_ticker_name(code) or code
        market = 'KRX'
        return name, market
    except Exception:
        cached = _find_cached_by_code(code)
        if cached:
            return cached.get('name', code), cached.get('market', 'UNKNOWN')
        return code, 'UNKNOWN'


def _ticker_candidates() -> list[dict]:
    rows: list[dict] = []
    rows.extend(_pykrx_candidates())
    rows.extend(_cached_report_candidates())
    rows.extend(_mock_candidates())
    return _dedupe_candidates(rows)


def _pykrx_candidates() -> list[dict]:
    if settings.use_mock_data:
        return []
    try:
        from pykrx import stock
        out: list[dict] = []
        seen = set()
        for date in _recent_kr_dates(20):
            for market in ('KOSPI', 'KOSDAQ', 'KONEX'):
                try:
                    tickers = stock.get_market_ticker_list(date, market=market)
                except Exception:
                    continue
                for code in tickers:
                    code = str(code).zfill(6)
                    if code in seen:
                        continue
                    seen.add(code)
                    name = stock.get_market_ticker_name(code) or ''
                    if name:
                        out.append({'code': code, 'name': name, 'market': market, 'sector': _infer_sector(code, name), 'resolved_by': 'pykrx_universe'})
            if out:
                return out
    except Exception:
        pass
    return []


def _cached_report_candidates() -> list[dict]:
    out: list[dict] = []
    for path in (REPORT_DIR / 'latest.json', REPORT_DIR / 'recommendation_history.json', REPORT_DIR / 'chat_recommendation_history.json'):
        data = _read_json(path)
        if not data:
            continue
        rows = data.get('kr_short_stocks') or data.get('items') or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            code = str(row.get('code', '')).zfill(6)
            name = str(row.get('name', '')).strip()
            if code and name and code != '000000':
                out.append({'code': code, 'name': name, 'market': row.get('market', 'CACHED'), 'sector': row.get('sector') or _infer_sector(code, name), 'resolved_by': f'cache:{path.name}'})
    return out


def _mock_candidates() -> list[dict]:
    return [
        {'code': str(row.get('code', '')).zfill(6), 'name': str(row.get('name', '')), 'market': str(row.get('market', 'MOCK')), 'sector': str(row.get('sector', '기타')), 'resolved_by': 'mock'}
        for row in mock_data.kr_stock_universe().to_dict('records')
    ]


def _dedupe_candidates(rows: list[dict]) -> list[dict]:
    by_code: dict[str, dict] = {}
    for row in rows:
        code = str(row.get('code', '')).zfill(6)
        name = str(row.get('name', '')).strip()
        if not code or not name or code == '000000':
            continue
        if code not in by_code or by_code[code].get('resolved_by', '').startswith(('mock', 'cache')):
            by_code[code] = {'code': code, 'name': name, 'market': row.get('market', 'UNKNOWN'), 'sector': row.get('sector') or _infer_sector(code, name), 'resolved_by': row.get('resolved_by', 'candidate')}
    return list(by_code.values())


def _find_cached_by_code(code: str) -> dict | None:
    code = str(code).zfill(6)
    for row in _cached_report_candidates() + _mock_candidates():
        if str(row.get('code', '')).zfill(6) == code:
            return row
    return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _action(score: float, threshold: float, setup: str, risk_pct: float, min_risk_pct: float, max_risk_pct: float, entry: float, price: float, max_entry_gap_pct: float) -> tuple[str, str]:
    if score < threshold:
        return '관망', f'점수 {score:.1f}가 기준 {threshold:.1f} 미만입니다.'
    if risk_pct < min_risk_pct:
        return '관망', f'손절폭 {risk_pct:.2f}%가 너무 좁아 노이즈 손절 위험이 큽니다.'
    if risk_pct > max_risk_pct:
        return '회피', f'손절폭 {risk_pct:.2f}%가 허용치 {max_risk_pct:.2f}를 초과합니다.'
    if entry / price - 1.0 > max_entry_gap_pct / 100.0:
        return '조건부 대기', '돌파 진입가가 현재가와 너무 멀어 추격매수 금지입니다.'
    if score >= threshold + 10:
        return '매수 후보', '점수와 setup이 기준을 충분히 초과합니다.'
    return '조건부 매수', '기준은 통과했지만 강한 확정 신호는 아니므로 분할/확인 진입이 맞습니다.'
