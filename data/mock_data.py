from __future__ import annotations

from datetime import datetime, timedelta
import numpy as np
import pandas as pd


def _price_series(start: float, trend: float, volatility: float, periods: int = 320, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(datetime.now().date() - timedelta(days=periods * 1.45), periods=periods, freq='B')
    returns = rng.normal(trend / periods, volatility, periods)
    close = start * np.cumprod(1 + returns)
    high = close * (1 + rng.uniform(0.001, 0.018, periods))
    low = close * (1 - rng.uniform(0.001, 0.018, periods))
    open_ = close * (1 + rng.normal(0, 0.004, periods))
    volume = rng.integers(800_000, 12_000_000, periods)
    return pd.DataFrame({'date': dates, 'open': open_, 'high': high, 'low': low, 'close': close, 'volume': volume})


def us_etf_universe() -> pd.DataFrame:
    rows = [
        ('VOO', 'Vanguard S&P 500 ETF', 'S&P500', 0.03, 1.0),
        ('QQQ', 'Invesco Nasdaq 100 ETF', 'Nasdaq100', 0.20, 1.18),
        ('VTI', 'Vanguard Total Stock Market ETF', 'Total Market', 0.03, 0.95),
        ('SCHD', 'Schwab US Dividend Equity ETF', 'Dividend', 0.06, 0.75),
        ('SMH', 'VanEck Semiconductor ETF', 'Semiconductor', 0.35, 1.45),
        ('SOXX', 'iShares Semiconductor ETF', 'Semiconductor', 0.35, 1.45),
        ('MAGS', 'Magnificent 7 ETF', 'AI/Growth', 0.29, 1.35),
        ('BOTZ', 'Global X Robotics & AI ETF', 'AI/Robotics', 0.68, 1.25),
        ('XLV', 'Health Care Select Sector SPDR', 'Healthcare', 0.09, 0.65),
        ('GLD', 'SPDR Gold Shares', 'Gold', 0.40, 0.55),
        ('TLT', 'iShares 20+ Year Treasury Bond ETF', 'Long Bond', 0.15, 0.85),
    ]
    return pd.DataFrame(rows, columns=['ticker', 'name', 'asset_class', 'expense_ratio', 'risk_weight'])


def us_history(ticker: str) -> pd.DataFrame:
    seed = abs(hash(ticker)) % 10_000
    params = {
        'VOO': (480, 0.22, 0.010), 'QQQ': (440, 0.28, 0.014), 'VTI': (245, 0.20, 0.010),
        'SCHD': (77, 0.12, 0.008), 'SMH': (220, 0.36, 0.020), 'SOXX': (230, 0.38, 0.021),
        'MAGS': (45, 0.34, 0.019), 'BOTZ': (34, 0.24, 0.018),
        'XLV': (145, 0.10, 0.007), 'GLD': (215, 0.18, 0.009), 'TLT': (94, -0.05, 0.011),
    }
    start, trend, vol = params.get(ticker, (100, 0.12, 0.012))
    df = _price_series(start, trend, vol, seed=seed)
    df['trade_value'] = df['close'] * df['volume']
    return df


def fx_history() -> pd.DataFrame:
    df = _price_series(1360, 0.02, 0.004, periods=180, seed=77).rename(columns={'close': 'usdkrw'})
    df['dxy'] = 104 + np.sin(np.linspace(0, 7, len(df))) * 2 + np.linspace(0, -0.8, len(df))
    df['us10y'] = 4.3 + np.sin(np.linspace(0, 5, len(df))) * 0.25
    df['vix'] = 16 + np.sin(np.linspace(0, 8, len(df))) * 4
    return df[['date', 'usdkrw', 'dxy', 'us10y', 'vix']]


def kr_etf_universe() -> pd.DataFrame:
    rows = [
        ('360750', 'TIGER 미국S&P500', '미국 S&P500', 0.07, 'risky', True, False, False),
        ('379810', 'KODEX 미국나스닥100TR', '미국 Nasdaq100', 0.05, 'risky', True, False, False),
        ('458730', 'TIGER 미국배당다우존스', '미국 배당', 0.03, 'risky', True, False, False),
        ('305540', 'TIGER 2차전지테마', '국내 2차전지', 0.50, 'risky', True, False, False),
        ('148070', 'KOSEF 국고채10년', '국내 국고채', 0.15, 'safe', True, False, False),
        ('329750', 'TIGER 미국달러단기채권액티브', '달러 단기채', 0.30, 'safe', True, False, False),
        ('122630', 'KODEX 레버리지', '국내 레버리지', 0.64, 'risky', False, True, False),
        ('114800', 'KODEX 인버스', '국내 인버스', 0.64, 'risky', False, False, True),
    ]
    return pd.DataFrame(rows, columns=['code', 'name', 'underlying_index', 'expense_ratio', 'asset_bucket', 'retirement_eligible', 'is_leveraged', 'is_inverse'])


def kr_etf_history(code: str) -> pd.DataFrame:
    seed = abs(hash(code)) % 10_000
    trend = 0.16 if code in {'360750', '379810', '458730'} else 0.05
    vol = 0.012 if code in {'360750', '379810'} else 0.006
    df = _price_series(10000, trend, vol, periods=320, seed=seed)
    df['trade_value'] = df['close'] * df['volume']
    return df


def kr_stock_universe() -> pd.DataFrame:
    rows = [
        ('005930', '삼성전자', '반도체'),
        ('000660', 'SK하이닉스', '반도체'),
        ('042700', '한미반도체', '반도체장비/소재'),
        ('039030', '이오테크닉스', '광통신/AI인프라'),
        ('094970', '제이엠티', '광통신/AI인프라'),
        ('038460', '바이오로그디바이스', '광통신/AI인프라'),
        ('267260', 'HD현대일렉트릭', '전력기기/전선'),
        ('298040', '효성중공업', '전력기기/전선'),
        ('034020', '두산에너빌리티', '원전/에너지'),
        ('010120', 'LS ELECTRIC', '전력기기/전선'),
        ('064350', '현대로템', '방산/철도'),
        ('352820', '하이브', '엔터'),
    ]
    return pd.DataFrame(rows, columns=['code', 'name', 'sector'])


def kr_stock_history(code: str) -> pd.DataFrame:
    seed = abs(hash(code)) % 10_000
    trend_map = {
        '042700': 0.34,
        '039030': 0.38,
        '094970': 0.32,
        '038460': 0.30,
        '267260': 0.42,
        '298040': 0.36,
        '010120': 0.28,
        '034020': 0.18,
    }
    trend = trend_map.get(code, 0.10)
    vol = 0.024 if code in trend_map else 0.014
    df = _price_series(50000, trend, vol, periods=420, seed=seed)
    df['trade_value'] = df['close'] * df['volume']
    return df


def retirement_positions() -> pd.DataFrame:
    return pd.DataFrame([
        ('360750', 'TIGER 미국S&P500', 3_000_000, 'risky'),
        ('379810', 'KODEX 미국나스닥100TR', 2_000_000, 'risky'),
        ('148070', 'KOSEF 국고채10년', 3_000_000, 'safe'),
        ('329750', 'TIGER 미국달러단기채권액티브', 1_000_000, 'safe'),
    ], columns=['code', 'name', 'market_value_krw', 'asset_bucket'])
