from __future__ import annotations

import re

from . import bot_services_v6 as v6
from . import bot_services_v4 as v4

US_SYMBOL_ALIASES = {
    "애플": "AAPL", "마이크로소프트": "MSFT", "마소": "MSFT", "엔비디아": "NVDA", "테슬라": "TSLA",
    "아마존": "AMZN", "알파벳": "GOOGL", "구글": "GOOGL", "메타": "META", "페이스북": "META",
    "넷플릭스": "NFLX", "브로드컴": "AVGO", "AMD": "AMD", "인텔": "INTC", "팔란티어": "PLTR",
    "오라클": "ORCL", "코스트코": "COST", "월마트": "WMT", "JP모건": "JPM", "제이피모건": "JPM",
    "버크셔": "BRK-B", "코카콜라": "KO", "펩시": "PEP", "맥도날드": "MCD", "나이키": "NKE",
    "디즈니": "DIS", "보잉": "BA", "록히드마틴": "LMT", "엑슨모빌": "XOM", "셰브론": "CVX",
    "코인베이스": "COIN", "마이크로스트래티지": "MSTR", "로블록스": "RBLX", "우버": "UBER",
    "슈퍼마이크로": "SMCI", "슈마컴": "SMCI", "퀄컴": "QCOM", "ASML": "ASML", "TSMC": "TSM",
    "아이온큐": "IONQ", "리게티": "RGTI", "SOFI": "SOFI", "소파이": "SOFI", "로빈후드": "HOOD",
    "SPY": "SPY", "QQQ": "QQQ", "TQQQ": "TQQQ", "SOXL": "SOXL", "EWY": "EWY",
}


def _alias_target(target: str) -> str:
    raw = str(target or "").strip()
    compact = re.sub(r"[\s·().,_-]+", "", raw).upper()
    for key, symbol in US_SYMBOL_ALIASES.items():
        if compact == re.sub(r"[\s·().,_-]+", "", key).upper():
            return symbol
    return raw


def simple_quote(target: str) -> str:
    return v4.simple_quote(_alias_target(target))


def fast_quote(target: str) -> str:
    return v4.fast_quote(_alias_target(target))


def handle_command(*, user_id: str, message: str, latest_report: str) -> str:
    has_prefix, msg = v4.base._strip_bot_prefix(message)
    if not has_prefix:
        return "명령어는 '봇'으로 시작해야 합니다. 예: 봇 뉴스"

    if msg.startswith("시세") or msg.lower().startswith("quote"):
        target = re.sub(r"^(시세|quote)\s*", "", msg, flags=re.IGNORECASE).strip()
        return simple_quote(target)

    if msg.startswith("차트"):
        target = re.sub(r"^차트\s*", "", msg).strip()
        return fast_quote(target)

    trade_target = v4.base._extract_trade_target(msg)
    if trade_target:
        return fast_quote(trade_target)

    return v6.handle_command(user_id=user_id, message=message, latest_report=latest_report)
