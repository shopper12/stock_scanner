from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _float_env(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _int_env(name: str, default: str) -> int:
    try:
        return int(float(os.getenv(name, default)))
    except ValueError:
        return int(float(default))


def _chat_ids() -> str | None:
    multi = os.getenv('TELEGRAM_CHAT_IDS')
    if multi and multi.strip():
        return multi.strip()
    single = os.getenv('TELEGRAM_CHAT_ID')
    if single and single.strip():
        return single.strip()
    return None


@dataclass(frozen=True)
class Settings:
    # Live data is the default. Set USE_MOCK_DATA=1 only for UI/build tests.
    allow_data_fallback: bool = _bool(os.getenv('ALLOW_DATA_FALLBACK'), False)
    use_mock_data: bool = _bool(os.getenv('USE_MOCK_DATA'), False)
    bull_market_mode: bool = _bool(os.getenv('BULL_MARKET_MODE'), False)
    database_url: str = os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'stock_scanner.db'}")
    timezone: str = os.getenv('TIMEZONE', 'Asia/Seoul')
    telegram_bot_token: str | None = os.getenv('TELEGRAM_BOT_TOKEN') or None
    telegram_chat_id: str | None = os.getenv('TELEGRAM_CHAT_ID') or None
    telegram_chat_ids: str | None = _chat_ids()
    base_currency: str = os.getenv('BASE_CURRENCY', 'KRW')
    account_equity_krw: float = _float_env('ACCOUNT_EQUITY_KRW', '10000000')
    risk_per_trade_pct: float = _float_env('RISK_PER_TRADE_PCT', '1.0')
    retirement_total_krw: float = _float_env('RETIREMENT_TOTAL_KRW', '10000000')
    retirement_risky_asset_cap_pct: float = _float_env('RETIREMENT_RISKY_ASSET_CAP_PCT', '70')
    us_monthly_budget_krw: float = _float_env('US_MONTHLY_BUDGET_KRW', '1000000')
    min_kr_trade_value_krw: float = _float_env('MIN_KR_TRADE_VALUE_KRW', '5000000000')
    min_kr_price: float = _float_env('MIN_KR_PRICE', '1000')
    # Keep a wider live universe so fast large-cap/theme repricing moves are not lost in the first prefilter.
    kr_universe_top_n: int = _int_env('KR_UNIVERSE_TOP_N', '180')
    kr_universe_top_n_bull: int = _int_env('KR_UNIVERSE_TOP_N_BULL', '180')
    max_kr_entry_gap_from_ma20_pct: float = _float_env('MAX_KR_ENTRY_GAP_FROM_MA20_PCT', '12')
    max_kr_trade_risk_pct: float = _float_env('MAX_KR_TRADE_RISK_PCT', '12')
    min_kr_trade_risk_pct: float = _float_env('MIN_KR_TRADE_RISK_PCT', '1.5')
    gemini_api_key: str | None = os.getenv('GEMINI_API_KEY') or None
    gemini_model: str = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash')
    gemini_enabled: bool = _bool(os.getenv('GEMINI_ENABLED'), False)
    gemini_timeout_sec: int = _int_env('GEMINI_TIMEOUT_SEC', '30')


settings = Settings()
