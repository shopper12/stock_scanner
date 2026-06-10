from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from config import settings

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT_DIR / "reports"
SIGNAL_LATEST_PATH = REPORT_DIR / "high_confidence_signals_latest.json"
SIGNAL_HISTORY_PATH = REPORT_DIR / "high_confidence_signal_history.json"


@dataclass(frozen=True)
class SignalWatchConfig:
    min_score: float = 82.0
    min_rr: float = 2.0
    max_alerts: int = 5
    max_etf_risk_pct: float = 7.5
    max_crypto_risk_pct: float = 8.5
    max_kr_risk_pct: float = 8.0
    min_rvol: float = 1.35
    timezone: str = settings.timezone


US_LONG_UNIVERSE = ["SPY", "QQQ", "IWM", "SMH", "SOXX", "TQQQ", "SOXL", "EWY", "KORU"]
US_INVERSE_UNIVERSE = ["SQQQ", "SOXS", "SPXU", "SH", "PSQ"]
CRYPTO_UNIVERSE = ["BTC-USD", "ETH-USD", "SOL-USD"]
FUTURES_UNIVERSE = ["ES=F", "NQ=F", "RTY=F", "YM=F"]
REGIME_TICKERS = ["SPY", "QQQ", "IWM", "SMH", "^VIX", "DX-Y.NYB", "KRW=X", "^TNX", "BTC-USD", "ES=F", "NQ=F", "RTY=F"]


def build_high_confidence_signal_payload(config: SignalWatchConfig | None = None, include_rejected: bool = True) -> dict:
    cfg = config or SignalWatchConfig()
    created_at = _now_text(cfg.timezone)
    regime = _build_market_regime(cfg)

    candidates: list[dict] = []
    rejected: list[dict] = []

    for ticker in US_LONG_UNIVERSE:
        signal, reason = _evaluate_ticker_signal(
            ticker=ticker,
            asset_class="US_ETF",
            direction="LONG",
            market_bias="risk_on",
            regime=regime,
            cfg=cfg,
        )
        _collect_signal(signal, reason, candidates, rejected)

    for ticker in US_INVERSE_UNIVERSE:
        signal, reason = _evaluate_ticker_signal(
            ticker=ticker,
            asset_class="US_INVERSE_ETF",
            direction="LONG_INVERSE",
            market_bias="risk_off",
            regime=regime,
            cfg=cfg,
        )
        _collect_signal(signal, reason, candidates, rejected)

    for ticker in FUTURES_UNIVERSE:
        signal, reason = _evaluate_ticker_signal(
            ticker=ticker,
            asset_class="FUTURES",
            direction="LONG" if regime.get("risk_on_score", 50) >= 55 else "SHORT_BIAS",
            market_bias="risk_on" if regime.get("risk_on_score", 50) >= 55 else "risk_off",
            regime=regime,
            cfg=cfg,
        )
        _collect_signal(signal, reason, candidates, rejected)

    for ticker in CRYPTO_UNIVERSE:
        signal, reason = _evaluate_ticker_signal(
            ticker=ticker,
            asset_class="CRYPTO",
            direction="LONG",
            market_bias="crypto_risk_on",
            regime=regime,
            cfg=cfg,
        )
        _collect_signal(signal, reason, candidates, rejected)

    kr_payload = _evaluate_kr_short_candidates(regime=regime, cfg=cfg)
    candidates.extend(kr_payload["signals"])
    rejected.extend(kr_payload["rejected"])

    candidates = sorted(candidates, key=lambda x: (float(x.get("score") or 0), float(x.get("rr") or 0)), reverse=True)
    actionable = candidates[: cfg.max_alerts]
    payload = {
        "ok": True,
        "schema_version": 1,
        "created_at_kst": created_at,
        "mode": "mock" if settings.use_mock_data else "live",
        "config": asdict(cfg),
        "market_regime": regime,
        "alert_count": len(actionable),
        "signals": actionable,
        "all_passed": candidates,
        "rejected": rejected[:80] if include_rejected else [],
        "decision": "notify" if actionable else "no_signal",
        "no_signal_reason": "No setup passed score, risk-reward, regime, trigger, and invalidation filters." if not actionable else "",
    }
    _write_signal_reports(payload)
    return payload


def _collect_signal(signal: dict | None, reason: dict, candidates: list[dict], rejected: list[dict]) -> None:
    if signal:
        candidates.append(signal)
    else:
        rejected.append(reason)


def _build_market_regime(cfg: SignalWatchConfig) -> dict:
    changes = {ticker: _daily_change_pct(ticker) for ticker in REGIME_TICKERS}
    score = 50.0

    def add_if(ticker: str, pos: float, neg: float, weight: float) -> None:
        nonlocal score
        value = changes.get(ticker)
        if value is None:
            return
        if value >= pos:
            score += weight
        elif value <= neg:
            score -= weight

    add_if("SPY", 0.20, -0.30, 6)
    add_if("QQQ", 0.25, -0.35, 8)
    add_if("SMH", 0.35, -0.45, 6)
    add_if("IWM", 0.20, -0.35, 4)
    add_if("ES=F", 0.12, -0.20, 5)
    add_if("NQ=F", 0.15, -0.25, 7)
    add_if("RTY=F", 0.15, -0.25, 3)
    add_if("BTC-USD", 0.60, -0.80, 5)

    vix_level = _last_close("^VIX")
    vix_change = changes.get("^VIX")
    if vix_level is not None:
        if vix_level >= 22:
            score -= 12
        elif vix_level >= 19:
            score -= 6
        elif vix_level <= 16:
            score += 5
    if vix_change is not None:
        if vix_change >= 5:
            score -= 8
        elif vix_change <= -4:
            score += 4

    for defensive in ["DX-Y.NYB", "KRW=X", "^TNX"]:
        value = changes.get(defensive)
        if value is None:
            continue
        if value >= 0.35:
            score -= 3
        elif value <= -0.35:
            score += 2

    score = round(max(0.0, min(100.0, score)), 1)
    if score >= 62:
        label = "risk_on"
    elif score <= 42:
        label = "risk_off"
    else:
        label = "neutral"

    return {
        "risk_on_score": score,
        "label": label,
        "long_allowed": score >= 55,
        "short_or_inverse_allowed": score <= 48,
        "crypto_long_allowed": score >= 50 and (changes.get("BTC-USD") or 0) > -1.5,
        "changes_pct": {k: _round_or_none(v, 2) for k, v in changes.items()},
        "vix_level": _round_or_none(vix_level, 2),
        "interpretation": _regime_interpretation(label, score),
    }


def _regime_interpretation(label: str, score: float) -> str:
    if label == "risk_on":
        return f"Risk-on gate open ({score}/100). Long setups may be considered only after trigger confirmation."
    if label == "risk_off":
        return f"Risk-off gate active ({score}/100). Long setups are blocked; inverse/short setups need non-chasing entries."
    return f"Neutral regime ({score}/100). Require stronger volume, trend, and risk-reward confirmation."


def _evaluate_ticker_signal(
    ticker: str,
    asset_class: str,
    direction: str,
    market_bias: str,
    regime: dict,
    cfg: SignalWatchConfig,
) -> tuple[dict | None, dict]:
    bars = _download_bars(ticker, period="7d" if asset_class == "CRYPTO" else "5d", interval="15m")
    reason_base = {"asset": ticker, "asset_class": asset_class, "direction": direction}
    if bars.empty or len(bars) < 55:
        return None, {**reason_base, "reject_reason": "insufficient_15m_bars"}

    metrics = _technical_metrics(bars)
    if not metrics:
        return None, {**reason_base, "reject_reason": "metric_build_failed"}

    is_inverse = asset_class == "US_INVERSE_ETF" or direction == "LONG_INVERSE"
    is_crypto = asset_class == "CRYPTO"
    max_risk_pct = cfg.max_crypto_risk_pct if is_crypto else cfg.max_etf_risk_pct

    if market_bias == "risk_on" and not regime.get("long_allowed"):
        return None, {**reason_base, "reject_reason": "market_regime_blocks_long", "metrics": metrics}
    if market_bias == "risk_off" and not regime.get("short_or_inverse_allowed"):
        return None, {**reason_base, "reject_reason": "market_regime_blocks_inverse_or_short", "metrics": metrics}
    if market_bias == "crypto_risk_on" and not regime.get("crypto_long_allowed"):
        return None, {**reason_base, "reject_reason": "market_regime_blocks_crypto_long", "metrics": metrics}

    entry = float(metrics["close"])
    atr = float(metrics["atr"])
    ema20 = float(metrics["ema20"])
    vwap = float(metrics["vwap"])
    if entry <= 0 or atr <= 0:
        return None, {**reason_base, "reject_reason": "invalid_price_or_atr", "metrics": metrics}

    stop = min(vwap, ema20, entry - 1.2 * atr)
    if is_inverse:
        stop = min(vwap, ema20, entry - 1.1 * atr)
    risk = entry - stop
    if risk <= 0:
        return None, {**reason_base, "reject_reason": "stop_not_below_entry", "metrics": metrics}
    risk_pct = risk / entry * 100.0
    if risk_pct > max_risk_pct or risk_pct < 0.25:
        return None, {**reason_base, "reject_reason": "risk_pct_out_of_bounds", "risk_pct": round(risk_pct, 2), "metrics": metrics}

    target1 = entry + risk
    target2 = entry + 2.05 * risk
    rr = (target2 - entry) / risk
    if rr < cfg.min_rr:
        return None, {**reason_base, "reject_reason": "rr_below_minimum", "rr": round(rr, 2), "metrics": metrics}

    trigger = _classify_trigger(metrics)
    if trigger == "none":
        return None, {**reason_base, "reject_reason": "no_breakout_or_pullback_trigger", "metrics": metrics}

    score = _score_signal(metrics=metrics, regime=regime, trigger=trigger, market_bias=market_bias, is_inverse=is_inverse)
    if score < cfg.min_score:
        return None, {**reason_base, "reject_reason": "score_below_threshold", "score": score, "metrics": metrics, "trigger": trigger}

    invalidation = f"15m close below {stop:.2f}, VWAP loss, or regime score falls below 50."
    if is_inverse:
        invalidation = f"15m close below {stop:.2f}, inverse ETF loses VWAP, or risk-on score reclaims 55+."
    if is_crypto:
        invalidation = f"15m close below {stop:.2f}, BTC loses intraday VWAP, or volume fades below RVOL 1.0."

    return {
        "asset": ticker,
        "asset_class": asset_class,
        "direction": direction,
        "setup": trigger,
        "score": score,
        "entry": round(entry, 4),
        "stop_loss": round(stop, 4),
        "target1": round(target1, 4),
        "target2": round(target2, 4),
        "rr": round(rr, 2),
        "risk_pct": round(risk_pct, 2),
        "invalidation": invalidation,
        "rationale": _build_rationale(ticker, trigger, metrics, regime, is_inverse=is_inverse),
        "metrics": metrics,
    }, {**reason_base, "reject_reason": "passed"}


def _evaluate_kr_short_candidates(regime: dict, cfg: SignalWatchConfig) -> dict:
    signals: list[dict] = []
    rejected: list[dict] = []
    if not _is_kr_market_actionable(cfg.timezone):
        return {
            "signals": [],
            "rejected": [{"asset_class": "KR_EQUITY", "reject_reason": "kr_market_closed_or_preopen_no_intraday_trigger"}],
        }
    if not regime.get("long_allowed"):
        return {
            "signals": [],
            "rejected": [{"asset_class": "KR_EQUITY", "reject_reason": "market_regime_blocks_kr_long"}],
        }
    try:
        from strategies.kr_short_stock_pure_runtime import scan_kr_short_stocks

        rows = scan_kr_short_stocks().to_dict("records")
    except Exception as exc:
        return {"signals": [], "rejected": [{"asset_class": "KR_EQUITY", "reject_reason": "kr_scan_failed", "message": str(exc)[:300]}]}

    for row in rows:
        code = str(row.get("code") or "").zfill(6)
        name = str(row.get("name") or "")
        score = float(row.get("score") or 0)
        entry = _float(row.get("entry") or row.get("current_price"))
        stop = _float(row.get("stop_loss"))
        target2 = _float(row.get("target2"))
        target1 = _float(row.get("target1"))
        if entry <= 0 or stop <= 0 or target2 <= 0:
            rejected.append({"asset": code, "name": name, "reject_reason": "missing_entry_stop_target", "score": score})
            continue
        risk = entry - stop
        reward = target2 - entry
        rr = reward / risk if risk > 0 else 0
        risk_pct = risk / entry * 100.0 if entry else 0
        quote_ok = bool(row.get("quote_ok", True))
        if score < cfg.min_score:
            rejected.append({"asset": code, "name": name, "reject_reason": "score_below_threshold", "score": score})
            continue
        if rr < cfg.min_rr:
            rejected.append({"asset": code, "name": name, "reject_reason": "rr_below_minimum", "rr": round(rr, 2), "score": score})
            continue
        if risk_pct <= 0 or risk_pct > cfg.max_kr_risk_pct:
            rejected.append({"asset": code, "name": name, "reject_reason": "risk_pct_out_of_bounds", "risk_pct": round(risk_pct, 2), "score": score})
            continue
        if not quote_ok:
            rejected.append({"asset": code, "name": name, "reject_reason": "quote_not_ok", "score": score})
            continue
        signals.append({
            "asset": code,
            "name": name,
            "asset_class": "KR_EQUITY",
            "direction": "LONG",
            "setup": row.get("strategy_type") or "kr_short_swing_intraday_gate",
            "score": round(score, 1),
            "entry": round(entry, 2),
            "stop_loss": round(stop, 2),
            "target1": round(target1, 2),
            "target2": round(target2, 2),
            "rr": round(rr, 2),
            "risk_pct": round(risk_pct, 2),
            "invalidation": row.get("failure_condition") or f"진입가 이탈 후 {stop:.0f} 손절 또는 시장 레짐 악화",
            "rationale": row.get("reason") or "KR scanner candidate passed strict intraday gate.",
            "metrics": {
                "current_price": row.get("current_price"),
                "sector": row.get("sector"),
                "price_basis": row.get("price_basis"),
                "trade_value_krw": row.get("trade_value_krw"),
            },
        })
    return {"signals": signals, "rejected": rejected[:50]}


def _score_signal(metrics: dict, regime: dict, trigger: str, market_bias: str, is_inverse: bool) -> float:
    score = 0.0
    regime_score = float(regime.get("risk_on_score") or 50)
    if market_bias == "risk_on":
        score += min(18, max(0, (regime_score - 45) * 0.6))
    elif market_bias == "risk_off":
        score += min(18, max(0, (55 - regime_score) * 0.6))
    else:
        score += min(16, max(0, (regime_score - 45) * 0.5))

    close = float(metrics["close"])
    ema20 = float(metrics["ema20"])
    ema50 = float(metrics["ema50"])
    vwap = float(metrics["vwap"])
    rvol = float(metrics["rvol"])
    change_1d = float(metrics.get("change_1d_pct") or 0)
    dist_ema20_atr = float(metrics.get("dist_ema20_atr") or 0)

    if close > ema20:
        score += 12
    if ema20 > ema50:
        score += 10
    if close > vwap:
        score += 10
    if trigger == "opening_range_breakout":
        score += 18
    elif trigger == "vwap_pullback_reclaim":
        score += 17
    elif trigger == "squeeze_breakout":
        score += 16
    score += min(15, max(0, (rvol - 1.0) * 10))
    if change_1d > 0.2:
        score += 7
    if change_1d > 1.0:
        score += 5
    if 0.0 <= dist_ema20_atr <= 1.8:
        score += 8
    elif dist_ema20_atr > 3.0:
        score -= 15
    if metrics.get("last_candle_green"):
        score += 5
    if is_inverse and regime_score > 52:
        score -= 20
    if not is_inverse and regime_score < 48:
        score -= 20
    return round(max(0.0, min(100.0, score)), 1)


def _classify_trigger(metrics: dict) -> str:
    close = float(metrics["close"])
    high20 = float(metrics["high20_prev"])
    low_latest = float(metrics["latest_low"])
    ema20 = float(metrics["ema20"])
    vwap = float(metrics["vwap"])
    rvol = float(metrics["rvol"])
    range_ratio = float(metrics.get("range_ratio_20") or 1)

    if close >= high20 * 0.998 and rvol >= 1.35:
        return "opening_range_breakout"
    if low_latest <= max(ema20, vwap) * 1.006 and close > ema20 and close > vwap and rvol >= 1.15 and metrics.get("last_candle_green"):
        return "vwap_pullback_reclaim"
    if range_ratio <= 0.72 and close >= high20 * 0.995 and rvol >= 1.25:
        return "squeeze_breakout"
    return "none"


def _technical_metrics(bars: pd.DataFrame) -> dict | None:
    try:
        df = bars.copy().dropna(subset=["Close"])
        if len(df) < 55:
            return None
        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].fillna(0).astype(float)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()
        prev_close = close.shift(1)
        true_range = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr = true_range.rolling(14).mean().dropna()
        typical = (high + low + close) / 3.0
        session = df[df.index.date == df.index[-1].date()]
        if session.empty:
            session = df.tail(40)
        session_vol = session["Volume"].fillna(0).astype(float)
        session_typical = ((session["High"] + session["Low"] + session["Close"]) / 3.0).astype(float)
        vwap = float((session_typical * session_vol).sum() / session_vol.sum()) if session_vol.sum() > 0 else float(close.iloc[-1])
        latest_vol = float(volume.iloc[-1])
        base_vol = float(volume.tail(60).replace(0, pd.NA).dropna().median() or 0)
        rvol = latest_vol / base_vol if base_vol > 0 else 0.0
        high20_prev = float(high.tail(21).iloc[:-1].max())
        range_now = float((high.tail(7) - low.tail(7)).mean())
        range_base = float((high.tail(25) - low.tail(25)).mean())
        range_ratio = range_now / range_base if range_base > 0 else 1.0
        c = float(close.iloc[-1])
        e20 = float(ema20.iloc[-1])
        a = float(atr.iloc[-1]) if not atr.empty else 0.0
        return {
            "close": round(c, 4),
            "latest_low": round(float(low.iloc[-1]), 4),
            "latest_high": round(float(high.iloc[-1]), 4),
            "ema20": round(e20, 4),
            "ema50": round(float(ema50.iloc[-1]), 4),
            "vwap": round(vwap, 4),
            "atr": round(a, 4),
            "rvol": round(rvol, 2),
            "high20_prev": round(high20_prev, 4),
            "range_ratio_20": round(range_ratio, 2),
            "change_1d_pct": round((c / float(close.iloc[-2]) - 1.0) * 100.0, 2) if len(close) >= 2 else 0.0,
            "dist_ema20_atr": round((c - e20) / a, 2) if a > 0 else 0.0,
            "last_candle_green": bool(close.iloc[-1] > df["Open"].astype(float).iloc[-1]),
        }
    except Exception:
        return None


def _build_rationale(ticker: str, trigger: str, metrics: dict, regime: dict, is_inverse: bool = False) -> str:
    side = "inverse/short-side" if is_inverse else "long-side"
    return (
        f"{ticker} {side} setup: {trigger}; close above VWAP/EMA20 with RVOL {metrics.get('rvol')}, "
        f"ATR-defined stop available, regime={regime.get('label')}({regime.get('risk_on_score')}/100)."
    )


def _download_bars(ticker: str, period: str, interval: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period=period, interval=interval, auto_adjust=True, prepost=True, progress=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)
        required = ["Open", "High", "Low", "Close", "Volume"]
        if not all(col in df.columns for col in required):
            return pd.DataFrame()
        return df[required].dropna(how="all")
    except Exception:
        return pd.DataFrame()


def _daily_change_pct(ticker: str) -> float | None:
    try:
        bars = yf.download(ticker, period="7d", interval="1d", auto_adjust=True, prepost=True, progress=False, threads=False)
        if bars is None or bars.empty:
            return None
        if isinstance(bars.columns, pd.MultiIndex):
            bars.columns = bars.columns.get_level_values(-1)
        close = bars["Close"].dropna().astype(float)
        if len(close) < 2:
            return None
        return float((close.iloc[-1] / close.iloc[-2] - 1.0) * 100.0)
    except Exception:
        return None


def _last_close(ticker: str) -> float | None:
    try:
        bars = yf.download(ticker, period="5d", interval="1d", auto_adjust=True, progress=False, threads=False)
        if bars is None or bars.empty:
            return None
        if isinstance(bars.columns, pd.MultiIndex):
            bars.columns = bars.columns.get_level_values(-1)
        close = bars["Close"].dropna().astype(float)
        return float(close.iloc[-1]) if len(close) else None
    except Exception:
        return None


def _write_signal_reports(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SIGNAL_LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if not payload.get("signals"):
        return
    history = _read_history_json(SIGNAL_HISTORY_PATH)
    items = history.get("items", [])
    seen = {item.get("dedupe_key") for item in items if isinstance(item, dict)}
    created_at = payload.get("created_at_kst")
    for signal in payload.get("signals", []):
        key = f"{created_at}:{signal.get('asset')}:{signal.get('direction')}:{signal.get('setup')}"
        if key in seen:
            continue
        items.append({"dedupe_key": key, "created_at_kst": created_at, **signal})
    history_out = {
        "schema_version": 1,
        "updated_at_kst": created_at,
        "items": items[-300:],
    }
    SIGNAL_HISTORY_PATH.write_text(json.dumps(history_out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_history_json(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "items": []}


def _is_kr_market_actionable(tz_name: str) -> bool:
    now = datetime.now(ZoneInfo(tz_name))
    if now.weekday() >= 5:
        return False
    return time(9, 0) <= now.time() <= time(15, 20)


def _now_text(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S %Z")


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        if math.isnan(float(value)):
            return None
        return round(float(value), digits)
    except Exception:
        return None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default
