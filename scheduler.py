from __future__ import annotations

import time
import schedule
from scan_once import run_full_scan


def job(name: str, notify: bool = True) -> None:
    print(f'[scheduler] start {name}')
    run_full_scan(notify=notify)
    print(f'[scheduler] done {name}')


def register_jobs() -> None:
    schedule.every().day.at('07:30').do(job, 'US ETF / FX morning', True)
    schedule.every().day.at('09:05').do(job, 'KR open scan', True)
    schedule.every().day.at('10:30').do(job, 'KR morning flow scan', True)
    schedule.every().day.at('13:30').do(job, 'KR afternoon scan', True)
    schedule.every().day.at('14:50').do(job, 'KR closing bet scan', True)
    schedule.every().day.at('15:20').do(job, 'KR final scan', True)
    schedule.every().monday.at('08:10').do(job, 'Retirement ETF weekly rebalance', True)


def main() -> None:
    register_jobs()
    print('[scheduler] registered jobs. Ctrl+C to stop.')
    while True:
        schedule.run_pending()
        time.sleep(20)


if __name__ == '__main__':
    main()
