from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT_DIR = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT_DIR / 'rules' / 'kr_short_rules.json'


@dataclass(frozen=True)
class KrShortRules:
    version: int = 1
    score_threshold: float = 55.0
    min_risk_pct: float = 1.5
    max_risk_pct: float = 12.0
    max_entry_gap_pct: float = 3.5
    max_gap_ma20_pct: float = 12.0
    surge_threshold_pct: float = 12.0
    surge_lookahead_days: int = 20
    hold_days: int = 10
    min_backtest_trades: int = 15
    min_surge_precision: float = 0.15
    min_avg_return_pct: float = 0.3
    min_profit_factor: float = 1.05
    min_win_rate: float = 0.45
    min_improvement_score: float = 0.05
    last_evolution: str | None = None
    last_summary: dict | None = None


def default_rules() -> KrShortRules:
    return KrShortRules()


def load_kr_short_rules() -> KrShortRules:
    if not RULES_PATH.exists():
        return default_rules()
    try:
        data = json.loads(RULES_PATH.read_text(encoding='utf-8'))
        allowed = set(KrShortRules.__dataclass_fields__.keys())
        clean = {k: v for k, v in data.items() if k in allowed}
        return KrShortRules(**clean)
    except Exception:
        return default_rules()


def save_kr_short_rules(rules: KrShortRules) -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(json.dumps(asdict(rules), ensure_ascii=False, indent=2), encoding='utf-8')


def rules_with_summary(rules: KrShortRules, summary: dict) -> KrShortRules:
    data = asdict(rules)
    data['last_evolution'] = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S %Z')
    data['last_summary'] = summary
    data['version'] = int(data.get('version', 1)) + 1
    return KrShortRules(**data)
