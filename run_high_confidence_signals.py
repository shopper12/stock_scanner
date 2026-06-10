from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from notifier import send_telegram_message
from strategies.global_intraday_signal import build_high_confidence_signal_payload


def build_signal_message(payload: dict) -> str:
    regime = payload.get("market_regime") or {}
    signals = payload.get("signals") or []
    lines: list[str] = []
    lines.append("🎯 <b>High-Confidence Trading Signal Watch</b>")
    lines.append(f"기준시각: {html.escape(str(payload.get('created_at_kst', '-')))}")
    lines.append(f"시장레짐: {html.escape(str(regime.get('label', '-')))} / {regime.get('risk_on_score', '-')}점")
    lines.append(html.escape(str(regime.get("interpretation") or "")))
    lines.append("")

    if not signals:
        lines.append("조건 충족 신호 없음")
        lines.append(html.escape(str(payload.get("no_signal_reason") or "No actionable setup.")))
        return "\n".join(lines)

    for s in signals:
        name = s.get("name") or s.get("asset")
        lines.append(f"<b>{html.escape(str(name))}</b> / {html.escape(str(s.get('asset_class', '-')))} / {html.escape(str(s.get('direction', '-')))}")
        lines.append(f"전략: {html.escape(str(s.get('setup', '-')))} / 신뢰도 {s.get('score', '-')} / R:R {s.get('rr', '-')}")
        lines.append(f"진입 {s.get('entry', '-')} / 손절 {s.get('stop_loss', '-')} / 목표 {s.get('target1', '-')}→{s.get('target2', '-')}")
        lines.append(f"무효화: {html.escape(str(s.get('invalidation', '-')))}")
        lines.append(f"근거: {html.escape(str(s.get('rationale', '-')))}")
        lines.append("")
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run high-confidence trading signal watcher.")
    parser.add_argument("--notify", action="store_true", help="Send Telegram only when at least one actionable signal exists.")
    parser.add_argument("--notify-empty", action="store_true", help="Send Telegram even when there is no signal, useful for testing.")
    parser.add_argument("--include-rejected", action="store_true", help="Keep rejected reasons in latest JSON.")
    args = parser.parse_args()

    payload = build_high_confidence_signal_payload(include_rejected=args.include_rejected)
    message = build_signal_message(payload)
    print(message)
    print(f"latest_report={Path('reports/high_confidence_signals_latest.json').resolve()}")

    should_notify = bool(payload.get("signals")) if args.notify else False
    if args.notify_empty:
        should_notify = True
    if should_notify:
        send_telegram_message(message)

    # Non-zero exit would break scheduled monitoring. Always exit cleanly after writing report.
    print(json.dumps({"decision": payload.get("decision"), "alert_count": payload.get("alert_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
