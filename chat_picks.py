from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import settings
from notifier import send_telegram_message

ROOT_DIR = Path(__file__).resolve().parent
REPORT_DIR = ROOT_DIR / 'reports'
CHAT_HISTORY_PATH = REPORT_DIR / 'chat_recommendation_history.json'
COMMON_HISTORY_PATH = REPORT_DIR / 'recommendation_history.json'

SEED_CURRENT_CONVERSATION_PICKS = [
    {
        'recommended_at_kst': '2026-05-26 15:25:00 KST',
        'code': '000660',
        'name': 'SK하이닉스',
        'market': 'KRX',
        'sector': '반도체/HBM',
        'strategy_type': 'chat_close_bet',
        'current_price': 2071500,
        'entry_low': 2055000,
        'entry_high': 2075000,
        'stop_loss': 2025000,
        'target1': 2087000,
        'target2': 2120000,
        'rationale': 'AI/HBM 주도주, 외국인·기관 대형주 수급, 당일 고가 재돌파 관찰',
        'risk': '당일 고가권 추격 및 장마감 차익실현·익일 갭하락 위험',
        'source_note': 'ChatGPT 대화 2026-05-26 한국장 15:25 종가베팅',
    },
    {
        'recommended_at_kst': '2026-05-26 15:25:00 KST',
        'code': '329180',
        'name': 'HD현대중공업',
        'market': 'KRX',
        'sector': '조선',
        'strategy_type': 'chat_close_bet',
        'current_price': 743000,
        'entry_low': 735000,
        'entry_high': 745000,
        'stop_loss': 722000,
        'target1': 763000,
        'target2': 780000,
        'rationale': '조선 섹터 동반 강세, 기관 선호 업종, 당일 고가 재시도 관찰',
        'risk': '급등 후 익일 갭리스크와 환율·원자재 뉴스 민감도',
        'source_note': 'ChatGPT 대화 2026-05-26 한국장 15:25 종가베팅',
    },
]


def _now_kst_text() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M:%S %Z')


def _normalise_code(code: str) -> str:
    value = str(code or '').strip().upper()
    if value.startswith('A') and value[1:].isdigit():
        value = value[1:]
    if value.isdigit():
        return value.zfill(6)
    return value


def _to_float(value, default: float | None = None) -> float | None:
    if value is None or value == '':
        return default
    try:
        return float(str(value).replace(',', '').strip())
    except Exception:
        return default


def _round_or_none(value) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(round(number))


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {'schema_version': 1, 'items': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {'schema_version': 1, 'items': []}
        data.setdefault('schema_version', 1)
        data.setdefault('items', [])
        return data
    except Exception:
        return {'schema_version': 1, 'items': []}


def _history_key(item: dict) -> str:
    source_id = item.get('source_id')
    if source_id:
        return str(source_id)
    scan_date = item.get('scan_date') or item.get('recommended_at_kst', '').split(' ')[0]
    code = _normalise_code(str(item.get('code', '')))
    if not scan_date or not code:
        return ''
    return f'{scan_date}:{code}'


def _write_upsert(path: Path, entry: dict, updated_at_kst: str) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    current = _read_json(path)
    items = current.get('items', [])
    by_key = {_history_key(item): item for item in items if _history_key(item)}
    by_key[_history_key(entry)] = entry
    merged = sorted(
        by_key.values(),
        key=lambda x: str(x.get('recommended_at_kst') or x.get('scan_date') or ''),
        reverse=True,
    )
    out = {
        'schema_version': 1,
        'updated_at_kst': updated_at_kst,
        'items': merged[:500],
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return out


def make_chat_recommendation(
    *,
    code: str,
    name: str,
    market: str = 'KRX',
    sector: str = '기타',
    strategy_type: str = 'chat_recommendation',
    current_price=None,
    entry=None,
    entry_low=None,
    entry_high=None,
    stop_loss=None,
    target1=None,
    target2=None,
    rationale: str = '',
    risk: str = '',
    source_note: str = 'ChatGPT 대화 추천',
    recommended_at_kst: str | None = None,
) -> dict:
    recommended_at = recommended_at_kst or _now_kst_text()
    scan_date = recommended_at.split(' ')[0]
    clean_code = _normalise_code(code)
    current = _to_float(current_price)
    low = _to_float(entry_low)
    high = _to_float(entry_high)
    explicit_entry = _to_float(entry)
    if explicit_entry is None and low is not None and high is not None:
        explicit_entry = (low + high) / 2
    if explicit_entry is None:
        explicit_entry = current

    pnl_pct = None
    pnl_krw = None
    if explicit_entry and current:
        pnl_pct = round((current / explicit_entry - 1.0) * 100, 2)
        pnl_krw = round(current - explicit_entry)

    source_id = f"chat:{recommended_at}:{clean_code}:{_round_or_none(explicit_entry) or 'na'}"
    return {
        'schema_version': 1,
        'source': 'chatgpt_conversation',
        'source_id': source_id,
        'scan_date': scan_date,
        'recommended_at_kst': recommended_at,
        'code': clean_code,
        'name': name,
        'market': market,
        'sector': sector,
        'strategy_type': strategy_type,
        'entry_low': _round_or_none(low),
        'entry_high': _round_or_none(high),
        'entry': _round_or_none(explicit_entry),
        'stop_loss': _round_or_none(stop_loss),
        'target1': _round_or_none(target1),
        'target2': _round_or_none(target2),
        'score_at_recommendation': None,
        'price_at_recommendation': _round_or_none(current),
        'latest_price': _round_or_none(current),
        'latest_price_basis': 'chat_message_price',
        'latest_price_timestamp': recommended_at,
        'pnl_pct': pnl_pct,
        'pnl_krw_per_share': pnl_krw,
        'reason': rationale,
        'risk': risk,
        'failure_condition': f"손절 {_round_or_none(stop_loss):,}원 이탈" if _round_or_none(stop_loss) else '',
        'source_note': source_note,
    }


def add_chat_recommendation(entry: dict, notify: bool = False) -> dict:
    updated_at = _now_kst_text()
    _write_upsert(CHAT_HISTORY_PATH, entry, updated_at)
    common = _write_upsert(COMMON_HISTORY_PATH, entry, updated_at)
    if notify:
        send_telegram_message(build_chat_recommendation_message([entry], title='ChatGPT 대화 추천 저장'))
    return common


def seed_current_conversation_picks(notify: bool = False) -> dict:
    entries = [make_chat_recommendation(**item) for item in SEED_CURRENT_CONVERSATION_PICKS]
    updated_at = _now_kst_text()
    chat_history = None
    common_history = None
    for entry in entries:
        chat_history = _write_upsert(CHAT_HISTORY_PATH, entry, updated_at)
        common_history = _write_upsert(COMMON_HISTORY_PATH, entry, updated_at)
    if notify and entries:
        send_telegram_message(build_chat_recommendation_message(entries, title='ChatGPT 대화 추천 일괄 저장'))
    return common_history or {'schema_version': 1, 'items': []}


def build_chat_recommendation_message(entries: list[dict], title: str = 'ChatGPT 대화 추천') -> str:
    lines = [f"📌 <b>{html.escape(title)}</b>"]
    lines.append(f"저장시각: {html.escape(_now_kst_text())}")
    lines.append('')
    for idx, item in enumerate(entries[:10], 1):
        name = html.escape(str(item.get('name', '')))
        code = html.escape(str(item.get('code', '')))
        sector = html.escape(str(item.get('sector', '기타')))
        strategy = html.escape(str(item.get('strategy_type', '')))
        reason = html.escape(str(item.get('reason', '')))
        risk = html.escape(str(item.get('risk', '')))
        lines.append(f"{idx}) <b>{name}({code})</b> [{sector}/{strategy}]")
        lines.append(
            f"현재 {_fmt_krw(item.get('price_at_recommendation'))} / "
            f"진입 {_fmt_range(item.get('entry_low'), item.get('entry_high'), item.get('entry'))} / "
            f"손절 {_fmt_krw(item.get('stop_loss'))} / "
            f"목표 {_fmt_krw(item.get('target1'))}→{_fmt_krw(item.get('target2'))}"
        )
        if reason:
            lines.append(f"근거: {reason}")
        if risk:
            lines.append(f"리스크: {risk}")
    return '\n'.join(lines)


def _fmt_krw(value) -> str:
    number = _round_or_none(value)
    if number is None:
        return 'N/A'
    return f'{number:,}원'


def _fmt_range(low, high, fallback) -> str:
    low_value = _round_or_none(low)
    high_value = _round_or_none(high)
    if low_value is not None and high_value is not None:
        return f'{low_value:,}~{high_value:,}원'
    return _fmt_krw(fallback)


def _print_history(path: Path, limit: int) -> str:
    data = _read_json(path)
    items = data.get('items', [])[:limit]
    if not items:
        return '저장된 ChatGPT 대화 추천이 없습니다.'
    return build_chat_recommendation_message(items, title=f'ChatGPT 대화 추천 최근 {len(items)}개')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Record ChatGPT conversation recommendations into stock_scanner history.')
    sub = parser.add_subparsers(dest='command', required=True)

    add = sub.add_parser('add', help='Add one recommendation from this ChatGPT conversation.')
    add.add_argument('--code', required=True)
    add.add_argument('--name', required=True)
    add.add_argument('--market', default='KRX')
    add.add_argument('--sector', default='기타')
    add.add_argument('--strategy-type', default='chat_recommendation')
    add.add_argument('--current-price')
    add.add_argument('--entry')
    add.add_argument('--entry-low')
    add.add_argument('--entry-high')
    add.add_argument('--stop-loss')
    add.add_argument('--target1')
    add.add_argument('--target2')
    add.add_argument('--rationale', default='')
    add.add_argument('--risk', default='')
    add.add_argument('--source-note', default='ChatGPT 대화 추천')
    add.add_argument('--recommended-at-kst')
    add.add_argument('--notify', action='store_true')

    seed = sub.add_parser('seed', help='Seed recommendations already generated in this conversation.')
    seed.add_argument('--notify', action='store_true')

    show = sub.add_parser('list', help='Print recent ChatGPT conversation recommendations.')
    show.add_argument('--limit', type=int, default=10)
    show.add_argument('--notify', action='store_true')

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == 'add':
        entry = make_chat_recommendation(
            code=args.code,
            name=args.name,
            market=args.market,
            sector=args.sector,
            strategy_type=args.strategy_type,
            current_price=args.current_price,
            entry=args.entry,
            entry_low=args.entry_low,
            entry_high=args.entry_high,
            stop_loss=args.stop_loss,
            target1=args.target1,
            target2=args.target2,
            rationale=args.rationale,
            risk=args.risk,
            source_note=args.source_note,
            recommended_at_kst=args.recommended_at_kst,
        )
        add_chat_recommendation(entry, notify=args.notify)
        print(build_chat_recommendation_message([entry], title='저장 완료'))
        print(f'chat_history={CHAT_HISTORY_PATH}')
        print(f'common_history={COMMON_HISTORY_PATH}')
        return

    if args.command == 'seed':
        seed_current_conversation_picks(notify=args.notify)
        print(_print_history(CHAT_HISTORY_PATH, limit=10))
        print(f'chat_history={CHAT_HISTORY_PATH}')
        print(f'common_history={COMMON_HISTORY_PATH}')
        return

    if args.command == 'list':
        text = _print_history(CHAT_HISTORY_PATH, limit=args.limit)
        print(text)
        if args.notify:
            send_telegram_message(text)
        return


if __name__ == '__main__':
    main()
