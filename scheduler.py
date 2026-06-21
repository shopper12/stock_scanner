from __future__ import annotations

import time

import schedule

from scan_once import run_full_scan


def job(name: str, notify: bool = True, notify_only_if_global_signal: bool = False) -> None:
    print(f'[scheduler] start {name}')
    run_full_scan(notify=notify, notify_only_if_global_signal=notify_only_if_global_signal)
    print(f'[scheduler] done {name}')


def monitor_job() -> None:
    """08:50 — update open recommendation outcomes and alert closed recommendations."""
    try:
        from database.recommendation_tracker import update_all_open_recommendations
        from notifier import send_telegram_message

        closed = update_all_open_recommendations()
        for rec in closed:
            ret = float(rec.get('realized_return_pct') or 0.0)
            status = 'WIN' if ret > 0 else 'LOSS'
            send_telegram_message(
                f"[추천 종료/{status}] {rec.get('name', '')}({rec.get('code', '')})\n"
                f"수익률: {ret:+.2f}% | {rec.get('exit_reason', '')}\n"
                f"MFE {float(rec.get('mfe_pct') or 0.0):+.1f}% / MAE {float(rec.get('mae_pct') or 0.0):+.1f}%"
            )
    except Exception as exc:
        print(f'[monitor_job] error: {exc}')


def eod_summary_job() -> None:
    """15:40 — send end-of-day recommendation performance summary."""
    try:
        from database.recommendation_tracker import summarise_live_performance
        from notifier import send_telegram_message

        perf = summarise_live_performance()
        if int(perf.get('closed_count', 0) or 0) == 0:
            return
        exit_breakdown = perf.get('exit_reason_breakdown', {}) or {}
        stops = exit_breakdown.get('stop', 0)
        targets = int(exit_breakdown.get('target1', 0) or 0) + int(exit_breakdown.get('target2', 0) or 0)
        send_telegram_message(
            f"[일일 성과]\n"
            f"활성 {perf.get('open_count', 0)}건 | 종료 {perf.get('closed_count', 0)}건\n"
            f"평균수익률 {float(perf.get('avg_realized_return_pct') or 0.0):+.2f}% | "
            f"승률 {float(perf.get('win_rate') or 0.0) * 100:.1f}%\n"
            f"손절 {stops}건 | 목표가 {targets}건"
        )
    except Exception as exc:
        print(f'[eod_summary_job] error: {exc}')


def weekly_evolve_job() -> None:
    """Friday 20:00 — run missed-surge audit and rule evolution."""
    try:
        from backtest.missed_surge_audit import run_missed_surge_audit
        from backtest.kr_short_evolution import evolve_kr_short_rules
        from notifier import send_telegram_message

        audit = run_missed_surge_audit()
        result = evolve_kr_short_rules(write=True, ai_review=True)
        written = bool(result.get('rules_written', False))
        improvement = float(result.get('improvement') or 0.0)
        send_telegram_message(
            f"[주간 룰 진화]\n"
            f"놓친 급등 {audit.get('total_missed', 0)}건 "
            f"(평균 {float(audit.get('avg_score_gap') or 0.0):.1f}점 미달)\n"
            f"권고: {audit.get('recommendation', '')}\n"
            f"룰 업데이트: {'YES' if written else 'NO'} | "
            f"Fitness {improvement:+.4f}"
        )
    except Exception as exc:
        print(f'[weekly_evolve_job] error: {exc}')


def register_jobs() -> None:
    schedule.every().hour.at(':05').do(job, 'Global US/KR/commodity condition watch', True, True)
    schedule.every().day.at('07:30').do(job, 'US ETF / FX morning', True)
    schedule.every().day.at('08:50').do(monitor_job)
    schedule.every().day.at('09:05').do(job, 'KR open scan', True)
    schedule.every().day.at('10:30').do(job, 'KR morning flow scan', True)
    schedule.every().day.at('13:30').do(job, 'KR afternoon scan', True)
    schedule.every().day.at('14:50').do(job, 'KR closing bet scan', True)
    schedule.every().day.at('15:20').do(job, 'KR final scan', True)
    schedule.every().day.at('15:40').do(eod_summary_job)
    schedule.every().monday.at('08:10').do(job, 'Retirement ETF weekly rebalance', True)
    schedule.every().friday.at('20:00').do(weekly_evolve_job)


def main() -> None:
    register_jobs()
    print('[scheduler] registered jobs. Ctrl+C to stop.')
    while True:
        schedule.run_pending()
        time.sleep(20)


if __name__ == '__main__':
    main()
