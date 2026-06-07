from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from config import settings


PERPLEXITY_URL = 'https://api.perplexity.ai/chat/completions'
DEFAULT_MODEL = 'sonar-pro'


def verify_kr_short_strategy(rows: list[dict], created_at_kst: str | None = None) -> dict:
    """Optional Perplexity/Sonar external verification for scanned KR short-term stock candidates.

    This verifier is deliberately non-blocking. If the API key is missing, disabled,
    rate-limited, or the model returns malformed JSON, the scanner still returns the
    original strategy output.
    """
    enabled = str(os.getenv('PERPLEXITY_VERIFY_ENABLED', '')).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}
    api_key = os.getenv('PERPLEXITY_API_KEY', '').strip()
    if not enabled:
        return _skipped('disabled', 'Set PERPLEXITY_VERIFY_ENABLED=true to enable external verification.')
    if not api_key:
        return _skipped('missing_api_key', 'Set PERPLEXITY_API_KEY in Render environment variables.')
    if not rows:
        return _skipped('no_candidates', 'No KR candidates to verify.')

    top_n = _int_env('PERPLEXITY_VERIFY_TOP_N', 3, 1, 8)
    selected = rows[:top_n]
    model = os.getenv('PERPLEXITY_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL
    prompt = _build_prompt(selected, created_at_kst)
    try:
        response = requests.post(
            PERPLEXITY_URL,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            json={
                'model': model,
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a strict external market-news verifier for Korean short-term stock strategies. Use current web evidence. Do not invent facts. Return Korean JSON only.',
                    },
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.1,
                'max_tokens': 1800,
            },
            timeout=_int_env('PERPLEXITY_TIMEOUT_SECONDS', 45, 10, 120),
        )
        if response.status_code >= 400:
            return _error('http_error', f'HTTP {response.status_code}: {response.text[:500]}', model=model)
        raw = response.json()
        content = _extract_content(raw)
        parsed = _parse_json_content(content)
        return {
            'ok': True,
            'status': 'verified',
            'model': model,
            'created_at_kst': _now_kst(),
            'scan_created_at_kst': created_at_kst,
            'requested_count': len(selected),
            'raw_content': content[:4000],
            'citations': raw.get('citations') or raw.get('search_results') or [],
            'result': parsed,
        }
    except Exception as exc:
        return _error(exc.__class__.__name__, str(exc)[:500], model=model)


def _build_prompt(rows: list[dict], created_at_kst: str | None) -> str:
    compact_rows = []
    for row in rows:
        compact_rows.append({
            'code': str(row.get('code', '')).zfill(6),
            'name': row.get('name'),
            'sector': row.get('sector'),
            'setup': row.get('strategy_type'),
            'score': row.get('score'),
            'current_price': row.get('current_price'),
            'price_basis': row.get('price_basis'),
            'price_timestamp': row.get('price_timestamp'),
            'entry': row.get('entry'),
            'stop_loss': row.get('stop_loss'),
            'target1': row.get('target1'),
            'target2': row.get('target2'),
            'risk_pct': row.get('risk_pct'),
            'volume_ratio_20d': row.get('volume_ratio_20d'),
            'trade_value_krw': row.get('trade_value_krw'),
            'momentum_5d_pct': row.get('momentum_5d_pct'),
            'momentum_20d_pct': row.get('momentum_20d_pct'),
            'drawdown_52w_pct': row.get('drawdown_52w_pct'),
            'rsi14': row.get('rsi14'),
            'scanner_reason': row.get('reason'),
            'failure_condition': row.get('failure_condition'),
        })
    return f'''
검증 기준시각: {created_at_kst or _now_kst()}

아래는 내부 stock_scanner가 산출한 한국 단기 매매 후보입니다. 너의 역할은 매매 추천을 새로 만드는 것이 아니라, 외부 웹/뉴스/공시/시장 자료로 "내부 전략의 전제"를 검증하는 것입니다.

검증 원칙:
1. 차트 수치와 진입/손절/목표가는 내부 시스템 값으로 보고 임의 변경하지 말 것.
2. 외부에서 확인할 것은 최근 뉴스, 공시, 실적/수주/정책/섹터 모멘텀, 악재, 거래정지/관리종목/CB·유증·감자 등 리스크다.
3. 근거가 부족하면 PASS 금지. WARN 또는 REJECT로 표시.
4. 오래된 뉴스와 오늘/전일 뉴스 구분.
5. 결과는 반드시 JSON 객체 하나만 반환. 마크다운 금지.

출력 JSON 스키마:
{{
  "overall_verdict": "PASS|WARN|REJECT",
  "summary": "전체 요약",
  "items": [
    {{
      "code": "005930",
      "name": "종목명",
      "verdict": "PASS|WARN|REJECT",
      "confidence": 0.0,
      "confirmed_catalysts": ["확인된 촉매"],
      "unconfirmed_assumptions": ["확인 안 된 내부 전제"],
      "risks": ["리스크"],
      "contradictions": ["전략과 충돌하는 근거"],
      "freshness": "today|recent|stale|unknown",
      "action_filter": "allow|watch_only|block",
      "one_line": "앱에 표시할 한 줄 검증"
    }}
  ]
}}

검증 대상:
{json.dumps(compact_rows, ensure_ascii=False, indent=2, default=str)}
'''.strip()


def _extract_content(raw: dict) -> str:
    try:
        return str(raw['choices'][0]['message']['content'])
    except Exception:
        return json.dumps(raw, ensure_ascii=False)[:4000]


def _parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {'parse_ok': False, 'text': content[:3000]}


def _skipped(reason: str, message: str) -> dict:
    return {
        'ok': False,
        'status': 'skipped',
        'reason': reason,
        'message': message,
        'created_at_kst': _now_kst(),
    }


def _error(reason: str, message: str, model: str | None = None) -> dict:
    return {
        'ok': False,
        'status': 'error',
        'reason': reason,
        'message': message,
        'model': model,
        'created_at_kst': _now_kst(),
    }


def _int_env(name: str, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(int(float(os.getenv(name, str(default)))), upper))
    except Exception:
        return default


def _now_kst() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')
