from __future__ import annotations

from pathlib import Path
import json

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
TRADE_HISTORY_PATH = ROOT_DIR / 'reports' / 'conversation_trade_history.json'

HISTORY_COLUMNS = [
    'id', 'date', 'session', 'asset_type', 'ticker', 'name', 'currency',
    'entry_low', 'entry_high', 'entry_mid', 'stop_loss', 'target1', 'target2',
    'current_price', 'current_price_time', 'current_price_source',
    'pnl_vs_entry_mid_pct', 'distance_to_target1_pct', 'distance_to_stop_pct',
    'status', 'source_status', 'memo',
]

SEED_TRADES = [
    ['20260522-am-000660', '2026-05-22', 'morning', 'kr_stock', '000660', 'SK하이닉스', 'KRW', 228000, 230000, 229000, 221000, 242000, None, None, None, None, None, None, None, 'open', 'conversation_recommended', '대화 중 매수 전략으로 제시됨'],
    ['20260522-am-381180', '2026-05-22', 'morning', 'kr_etf', '381180', 'TIGER 미국필라델피아반도체나스닥', 'KRW', 28800, 29200, 29000, 27900, 31000, None, None, None, None, None, None, None, 'open', 'conversation_recommended', '대화 중 매수 전략으로 제시됨'],
    ['20260522-am-SOL', '2026-05-22', 'morning', 'crypto', 'SOL', 'Solana', 'USD', 166, 169, 167.5, 158, 184, None, None, None, None, None, None, None, 'open', 'conversation_recommended', '대화 중 매수 전략으로 제시됨'],
    ['20260522-close-034020', '2026-05-22', 'close', 'kr_stock', '034020', '두산에너빌리티', 'KRW', 55000, 56000, 55500, 53200, 59000, None, None, None, None, None, None, None, 'open', 'conversation_recommended', '대화 중 종가베팅 후보로 제시됨'],
    ['20260523-am-NVDA', '2026-05-23', 'morning', 'us_equity', 'NVDA', 'NVIDIA', 'USD', 186, 188, 187, 179, 198, None, None, None, None, None, None, None, 'open', 'holiday_substitute_recommended', '한국장 휴장 대체 시장 추천'],
    ['20260523-am-SOXX', '2026-05-23', 'morning', 'us_etf', 'SOXX', 'iShares Semiconductor ETF', 'USD', 313, 315, 314, 304, 329, None, None, None, None, None, None, None, 'open', 'holiday_substitute_recommended', '한국장 휴장 대체 시장 추천'],
    ['20260523-am-SOL', '2026-05-23', 'morning', 'crypto', 'SOL', 'Solana', 'USD', 174, 176, 175, 166, 192, None, None, None, None, None, None, None, 'open', 'holiday_substitute_recommended', '한국장 휴장 대체 시장 추천'],
    ['20260524-am-AVGO', '2026-05-24', 'morning', 'us_equity', 'AVGO', 'Broadcom', 'USD', 2120, 2135, 2127.5, 2040, 2280, None, None, None, None, None, None, None, 'open', 'holiday_substitute_recommended', '한국장 휴장 대체 시장 추천'],
    ['20260524-am-SMH', '2026-05-24', 'morning', 'us_etf', 'SMH', 'VanEck Semiconductor ETF', 'USD', 339, 341, 340, 329, 358, None, None, None, None, None, None, None, 'open', 'holiday_substitute_recommended', '한국장 휴장 대체 시장 추천'],
    ['20260524-am-ETH', '2026-05-24', 'morning', 'crypto', 'ETH', 'Ethereum', 'USD', 4430, 4470, 4450, 4180, 4900, None, None, None, None, None, None, None, 'open', 'holiday_substitute_recommended', '한국장 휴장 대체 시장 추천'],
    ['20260525-am-000660', '2026-05-25', 'morning', 'kr_stock', '000660', 'SK하이닉스', 'KRW', 234000, 236000, 235000, 227000, 248000, None, None, None, None, None, None, None, 'open', 'kr_holiday_error_kept_for_tracking', '2026-05-25 한국장 휴장 오판 답변이었으나 사용자 요청에 따라 히스토리 보존'],
    ['20260525-am-471990', '2026-05-25', 'morning', 'kr_etf', '471990', 'KODEX AI반도체핵심장비', 'KRW', 18950, 19150, 19050, 18200, 20300, None, None, None, None, None, None, None, 'open', 'kr_holiday_error_kept_for_tracking', '2026-05-25 한국장 휴장 오판 답변이었으나 사용자 요청에 따라 히스토리 보존'],
    ['20260525-am-ETH', '2026-05-25', 'morning', 'crypto', 'ETH', 'Ethereum', 'USD', 4500, 4540, 4520, 4240, 4950, None, None, None, None, None, None, None, 'open', 'conversation_recommended', '대화 중 매수 전략으로 제시됨'],
    ['20260525-close-267260', '2026-05-25', 'close', 'kr_stock', '267260', 'HD현대일렉트릭', 'KRW', 409000, 413000, 411000, 394000, 438000, None, None, None, None, None, None, None, 'open', 'kr_holiday_error_kept_for_tracking', '2026-05-25 한국장 휴장 오판 답변이었으나 사용자 요청에 따라 히스토리 보존'],
]


def empty_trade_history() -> pd.DataFrame:
    return pd.DataFrame(columns=HISTORY_COLUMNS)


def seeded_trade_history() -> pd.DataFrame:
    return pd.DataFrame(SEED_TRADES, columns=HISTORY_COLUMNS)


def read_trade_history() -> pd.DataFrame:
    if not TRADE_HISTORY_PATH.exists():
        return seeded_trade_history()
    try:
        payload = json.loads(TRADE_HISTORY_PATH.read_text(encoding='utf-8'))
        df = pd.DataFrame(payload.get('items', []))
        if df.empty:
            return seeded_trade_history()
        for col in HISTORY_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[HISTORY_COLUMNS]
    except Exception:
        return seeded_trade_history()


def write_trade_history(df: pd.DataFrame) -> None:
    TRADE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in HISTORY_COLUMNS:
        if col not in out.columns:
            out[col] = None
    payload = {'schema_version': 1, 'items': out[HISTORY_COLUMNS].to_dict('records')}
    TRADE_HISTORY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
