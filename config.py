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


@dataclass(frozen=True)
class Settings:
    use_mock_data: bool = _bool(os.getenv('USE_MOCK_DATA'), True)
    database_url: str = os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'stock_scanner.db'}")
    timezone: str = os.getenv('TIMEZONE', 'Asia/Seoul')
    telegram_bot_token: str | None = os.getenv('TELEGRAM_BOT_TOKEN') or None
    telegram_chat_id: str | None = os.getenv('TELEGRAM_CHAT_ID') or None
    base_currency: str = os.getenv('BASE_CURRENCY', 'KRW')
    account_equity_krw: float = float(os.getenv('ACCOUNT_EQUITY_KRW', '10000000'))
    risk_per_trade_pct: float = float(os.getenv('RISK_PER_TRADE_PCT', '1.0'))
    retirement_total_krw: float = float(os.getenv('RETIREMENT_TOTAL_KRW', '10000000'))
    retirement_risky_asset_cap_pct: float = float(os.getenv('RETIREMENT_RISKY_ASSET_CAP_PCT', '70'))
    us_monthly_budget_krw: float = float(os.getenv('US_MONTHLY_BUDGET_KRW', '1000000'))
    min_kr_trade_value_krw: float = float(os.getenv('MIN_KR_TRADE_VALUE_KRW', '5000000000'))


settings = Settings()
