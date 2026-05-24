from __future__ import annotations

import json
from typing import Any

import requests

from config import settings


BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/models'


def is_enabled() -> bool:
    return bool(settings.gemini_enabled and settings.gemini_api_key)


def review_report(summary: dict[str, Any]) -> dict[str, Any]:
    if not is_enabled():
        return {'enabled': False, 'used': False, 'reason': 'missing Gemini configuration'}

    text = _call_model(_prompt(summary))
    return {
        'enabled': True,
        'used': True,
        'model': settings.gemini_model,
        'raw_text': text,
        'json': _parse_json(text),
    }


def _call_model(prompt: str) -> str:
    response = requests.post(
        f"{BASE_URL}/{settings.gemini_model}:generateContent",
        headers={'x-goog-api-key': settings.gemini_api_key},
        json={
            'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.2, 'responseMimeType': 'application/json'},
        },
        timeout=settings.gemini_timeout_sec,
    )
    response.raise_for_status()
    data = response.json()
    candidates = data.get('candidates') or []
    if not candidates:
        return '{}'
    parts = candidates[0].get('content', {}).get('parts', [])
    return '\n'.join([p.get('text', '') for p in parts if p.get('text')]).strip()


def _prompt(summary: dict[str, Any]) -> str:
    compact = json.dumps(summary, ensure_ascii=False, default=str)[:12000]
    return f"""
Review this quantitative scanner evaluation report.
Return JSON only.
Focus on data quality, sample size, overfitting risk, and which thresholds should be tested again.
Do not mention individual securities.

Schema:
{{
  "diagnosis": ["string"],
  "overfit_risks": ["string"],
  "threshold_tests": [{{"field": "string", "direction": "increase|decrease|keep", "reason": "string"}}],
  "do_not_change": ["string"],
  "confidence": 0.0
}}

Report:
{compact}
""".strip()


def _parse_json(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except Exception:
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
    return None
