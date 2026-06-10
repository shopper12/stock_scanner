from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from notifier import send_telegram_message
from strategies.global_intraday_signal import SIGNAL_LATEST_PATH, build_high_confidence_signal_payload


def build_signal_message(payload: dict) -> str:
    created_at = html.escape(str(payload.get("created_at_kst", "-")))
    regime = payload.get("market_regime") or {}
    signals = payload.get("signals") or []
    lines: list[str] = []
    lines.append("🎯 <b>High-Confidence Signal Watch</b>")
    lines.append(f"기준: {created_at}")
    lines.append(f"레짐: {html.escape(str(regime.get('label', '-')))} / 점수 {regime.get('risk_on_score', '-')}/100")
    lines.append(html.escape(str(regime.get("interpretation", ""))))
    lines.append("")
    if not signals:
        lines.append("조건 충족 신호 없음")
        lines.append(html.escape(str(payload.get("no_signal_reason") or "No actionable signal.")))
        return "\n".join(lines)

    for signal in signals:
        asset = html.escape(str(signal.get("name") or signal.get("asset")))
        asset_code = html.escape(str(signal.get("asset")))
        direction = html.escape(str(signal.get("direction")))
        setup = html.escape(str(signal.get("setup")))
        rationale = html.escape(str(signal.get("rationale", "")))
        invalidation = html.escape(str(signal.get("invalidation", "")))
        lines.append(f"<b>{asset}</b> ({asset_code}) / {direction} / {setup}")
        lines.append(f"신뢰도 {signal.get('score')} / R:R {signal.get('rr')} / 위험 {signal.get('risk_pct')}%")
        lines.append(f"진입 {signal.get('entry')} / 손절 {signal.get('stop_loss')} / 목표 {signal.get('target1')}→{signal.get('target2')}")
        lines.append(f"근거: {rationale}")
        lines.append(f"무효화: {invalidation}")
        lines.append("")
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch high-confidence actionable trading signals.")
    parser.add_argument("--notify", action="store_true", help="Send Telegram only when at least one signal passes all filters.")
    parser.add_argument("--notify-no-signal", action="store_true", help="Also notify when no signal passes. Useful for manual debugging only.")
    parser.add_argument("--print-json", action="store_true", help="Print full JSON payload.")
    args = parser.parse_args()

    payload = build_high_confidence_signal_payload()
    message = build_signal_message(payload)
    should_notify = bool(payload.get("signals")) or args.notify_no_signal
    if args.notify and should_notify:
        send_telegram_message(message)
    else:
        print(message)
    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print(f"latest_signal_report={Path(SIGNAL_LATEST_PATH)}")


if __name__ == "__main__":
    main()
