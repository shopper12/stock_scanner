from __future__ import annotations

import json
from pathlib import Path

from strategies.kr_stock_lookup import analyze_kr_stock_strategy as base_analyze
from strategies.kr_stock_lookup import resolve_kr_stock_query as base_resolve
from strategies.kr_stock_lookup import _normalise_name
from strategies.kr_short_rules import load_kr_short_rules

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / 'reports'
LATEST_PATH = REPORT_DIR / 'latest.json'

STATIC_NAME_TO_CODE = {
    '국보디자인': '066620',
    '국보': '066620',
    '한미반도체': '042700',
    '이오테크닉스': '039030',
    '테크윙': '089030',
    '피에스케이홀딩스': '031980',
    '와이씨': '232140',
    '리노공업': '058470',
    '하나마이크론': '067310',
    '주성엔지니어링': '036930',
    '심텍': '222800',
    '대덕전자': '353200',
    '효성중공업': '298040',
    'hd현대일렉트릭': '267260',
    'ls일렉트릭': '010120',
    '제룡전기': '033100',
    '현대로템': '064350',
    '한국항공우주': '047810',
    'lig넥스원': '079550',
    '한화시스템': '272210',
    '두산로보틱스': '454910',
    '레인보우로보틱스': '277810',
    '비나텍': '126340',
    '성호전자': '043260',
    '파워넷': '037030',
    '아모텍': '052710',
    '삼지전자': '037460',
    'kx하이텍': '052900',
}


def analyze_kr_stock_strategy(query: str) -> dict:
    target = resolve_kr_stock_query(query)
    result = base_analyze(target['code'])
    result['query'] = query
    result['resolved_by'] = target.get('resolved_by', result.get('resolved_by', 'enhanced'))
    if target.get('name') and (not result.get('name') or result.get('name') == result.get('code')):
        result['name'] = target['name']
    result['code'] = str(result.get('code') or target['code']).zfill(6)
    result['name'] = str(result.get('name') or target.get('name') or result['code'])
    result['display_name'] = _display_name(result)
    result['stock_label'] = result['display_name']
    result['title'] = result['display_name']
    result['scanner_exclusion_diagnosis'] = diagnose_scanner_exclusion(result)
    return result


def resolve_kr_stock_query(query: str) -> dict:
    q = str(query or '').strip()
    if not q:
        raise ValueError('query is required')
    if q.isdigit():
        resolved = base_resolve(q)
        resolved['code'] = str(resolved.get('code') or q).zfill(6)
        resolved['display_name'] = _display_name(resolved)
        return resolved
    q_norm = _normalise_name(q)
    static_code = STATIC_NAME_TO_CODE.get(q_norm)
    if static_code:
        resolved = _resolve_static(static_code, q)
        resolved['display_name'] = _display_name(resolved)
        return resolved
    try:
        resolved = base_resolve(q)
        resolved['code'] = str(resolved.get('code') or '').zfill(6)
        resolved['display_name'] = _display_name(resolved)
        return resolved
    except Exception as exc:
        cached = _resolve_by_cached_reports(q_norm)
        if cached:
            cached['display_name'] = _display_name(cached)
            return cached
        raise ValueError(f'no KR stock match for query={query}. base_error={exc}')


def diagnose_scanner_exclusion(strategy: dict) -> dict:
    code = str(strategy.get('code') or '').zfill(6)
    latest = _read_json(LATEST_PATH)
    rows = latest.get('kr_short_stocks') or []
    selected_codes = {str(row.get('code') or '').zfill(6) for row in rows}
    selected_labels = [_display_name(row) for row in rows[:20]]
    if code in selected_codes:
        return {
            'selected': True,
            'display_name': _display_name(strategy),
            'reason': f'{_display_name(strategy)} 현재 latest.json 추천 후보에 포함됨',
            'latest_count': len(rows),
            'selected_labels': selected_labels,
        }

    rules = load_kr_short_rules()
    setup = str(strategy.get('setup') or '')
    score = float(strategy.get('score') or 0.0)
    threshold = float(strategy.get('threshold') or getattr(rules, 'score_threshold', 55.0) or 55.0)
    risk_pct = float(strategy.get('risk_pct') or 0.0)
    current_price = float(strategy.get('current_price') or 0.0)
    entry = float(strategy.get('entry') or 0.0)
    metrics = strategy.get('metrics') or {}
    drawdown52w_pct = float(metrics.get('drawdown_52w_pct') or 0.0)
    trade_value_krw = float(metrics.get('trade_value_krw') or 0.0)
    value_ratio = float(metrics.get('trade_value_ratio_20d') or 0.0)
    filters: list[str] = []

    if score < threshold:
        filters.append(f'score 미달: {score:.1f} < {threshold:.1f}')
    if setup in {'breakout', 'trend_continuation'}:
        filters.append(f'런타임 차단 setup: {setup}은 백테스트 PF<1로 추천 제외')
    if setup == 'watch' and drawdown52w_pct > -3.0:
        filters.append(f'watch 눌림 부족: drawdown52w {drawdown52w_pct:.2f}% > -3.0%')
    max_risk = float(getattr(rules, 'max_risk_pct', 12.0) or 12.0)
    if setup != 'theme_repricing_breakout' and risk_pct > max_risk:
        filters.append(f'risk 초과: {risk_pct:.2f}% > {max_risk:.2f}%')
    if setup == 'theme_repricing_breakout' and risk_pct > 16.0:
        filters.append(f'theme risk 초과: {risk_pct:.2f}% > 16.0%')
    max_entry_gap = float(getattr(rules, 'max_entry_gap_pct', 3.5) or 3.5)
    if current_price > 0 and entry > 0 and entry / current_price - 1.0 > max_entry_gap / 100.0:
        filters.append(f'진입가 괴리 과다: {(entry / current_price - 1.0) * 100:.2f}%')
    if trade_value_krw and trade_value_krw < 5_000_000_000:
        filters.append(f'거래대금 부족 가능: {trade_value_krw:,.0f}원 < 5,000,000,000원')
    if value_ratio <= 0:
        filters.append('거래대금/20일 평균 비율 산출 실패 또는 0')
    if not filters and len(rows) >= 5:
        filters.append('필터는 통과 가능하나 latest 상위 N개 정렬/섹터 제한에서 밀렸을 가능성')
    if not filters:
        filters.append('스캔 시점과 수동 분석 시점의 실시간 가격/거래대금 차이 가능')

    return {
        'selected': False,
        'display_name': _display_name(strategy),
        'reason': f'{_display_name(strategy)} 제외 사유: ' + '; '.join(filters),
        'latest_count': len(rows),
        'selected_codes': list(selected_codes)[:20],
        'selected_labels': selected_labels,
        'evaluation': '100점이어도 수동 base 점수와 실제 runtime 추천 필터가 달라 제외될 수 있음',
    }


def _resolve_static(code: str, query_name: str) -> dict:
    try:
        base = base_resolve(code)
        name = base.get('name') if base.get('name') and base.get('name') != code else query_name
        return {**base, 'code': code, 'name': name, 'resolved_by': 'static_name_map'}
    except Exception:
        return {'code': code, 'name': query_name, 'market': 'UNKNOWN', 'sector': '기타', 'resolved_by': 'static_name_map'}


def _resolve_by_cached_reports(q_norm: str) -> dict | None:
    for path in (REPORT_DIR / 'latest.json', REPORT_DIR / 'recommendation_history.json', REPORT_DIR / 'chat_recommendation_history.json'):
        data = _read_json(path)
        rows = data.get('kr_short_stocks') or data.get('items') or []
        for row in rows if isinstance(rows, list) else []:
            name = str(row.get('name') or '').strip()
            code = str(row.get('code') or '').zfill(6)
            if name and code and _normalise_name(name) == q_norm:
                return {'code': code, 'name': name, 'market': row.get('market', 'CACHED'), 'sector': row.get('sector', '기타'), 'resolved_by': f'cache:{path.name}'}
    return None


def _display_name(row: dict) -> str:
    code = str(row.get('code') or '').zfill(6)
    name = str(row.get('name') or '').strip()
    if not name or name == code or name == code.lstrip('0'):
        name = code
    return f'{name}({code})'


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
