from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.kr_short_evolution import evolve_kr_short_rules, run_kr_short_backtest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--max-symbols', type=int, default=None)
    parser.add_argument('--current-only', action='store_true')
    args = parser.parse_args()

    result = run_kr_short_backtest(max_symbols=args.max_symbols) if args.current_only else evolve_kr_short_rules(write=args.apply, max_symbols=args.max_symbols)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
