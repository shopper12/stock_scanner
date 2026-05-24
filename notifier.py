from __future__ import annotations

import html
import requests
from config import settings


def _telegram_chat_ids() -> list[str]:
    raw = getattr(settings, 'telegram_chat_ids', None) or settings.telegram_chat_id or ''
    ids: list[str] = []
    for part in str(raw).replace(';', ',').replace('\n', ',').split(','):
        value = part.strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def telegram_enabled() -> bool:
    return bool(settings.telegram_bot_token and _telegram_chat_ids())


def send_telegram_message(text: str) -> bool:
    if not telegram_enabled():
        print('[notifier] Telegram 설정 없음. 메시지만 출력합니다.')
        print(text)
        return False

    url = f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage'
    ok = True
    for chat_id in _telegram_chat_ids():
        resp = requests.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=15)
        if not resp.ok:
            ok = False
            print(f'[notifier] Telegram 전송 실패: chat_id={chat_id}')
            print(f'HTTP {resp.status_code}: {resp.text}')
            print('점검: chat.id 숫자인지, 해당 사용자가 봇에게 /start를 보냈는지 확인하세요.')
    return ok


def build_mobile_summary(payload: dict) -> str:
    fx = payload['fx']
    us_top = payload['us_long_etfs'][:3]
    kr_short = payload['kr_short_stocks'][:3]
    retirement = payload['retirement_risk_report']
    mode = payload.get('mode', 'unknown')

    lines = []
    lines.append('📌 <b>Stock Scanner 요약</b>')
    lines.append(f"기준시각: {html.escape(str(payload['created_at_kst']))} / 데이터: {html.escape(str(mode))}")
    if mode == 'mock':
        lines.append('⚠️ mock 모드: 실전 매매 판단 금지')
    lines.append('')

    lines.append('💵 <b>환율</b>')
    lines.append(f"USD/KRW {fx['usdkrw']} / 60일평균 {fx['ma60']} / 판단: {html.escape(str(fx['action']))}")
    lines.append(f"권장 환전: {fx['suggested_conversion_ratio_pct']}% / {fx['suggested_conversion_krw']:,}원")
    lines.append('')

    lines.append('🇺🇸 <b>미국 장기 ETF 상위</b>')
    for x in us_top:
        lines.append(
            f"{html.escape(str(x['ticker']))} 점수 {x['score']} / "
            f"이번달 매수 {x['this_month_buy_pct']}% / "
            f"가격 {x.get('current_price', 'N/A')} / "
            f"{html.escape(str(x['additional_buy_condition']))}"
        )
    lines.append('')

    lines.append('🏦 <b>퇴직연금 한도</b>')
    lines.append(f"위험자산 {retirement['risky_pct']}% / 상태: {html.escape(str(retirement['status']))} / 추가여력 {retirement['risky_buy_room_krw']:,}원")
    lines.append('')

    lines.append('🇰🇷 <b>한국 단기 일반계좌 후보</b>')
    if kr_short:
        for x in kr_short:
            name = html.escape(str(x.get('name', '')))
            code = html.escape(str(x.get('code', '')))
            sector = html.escape(str(x.get('sector', '기타')))
            setup = html.escape(str(x.get('strategy_type', '')))
            reason = html.escape(str(x.get('reason', '')))
            basis = html.escape(str(x.get('price_basis', 'unknown')))
            source = html.escape(str(x.get('quote_source') or x.get('data_source', 'unknown')))
            ts = html.escape(str(x.get('price_timestamp', 'unknown')))
            current = _fmt_int(x.get('current_price'))
            entry = _fmt_int(x.get('entry'))
            stop = _fmt_int(x.get('stop_loss'))
            target1 = _fmt_int(x.get('target1'))
            target2 = _fmt_int(x.get('target2'))
            position = _fmt_int(x.get('position_size_krw'))
            risk_pct = x.get('risk_pct', 'N/A')
            lines.append(f"<b>{name}({code})</b> [{sector}/{setup}] 점수 {x.get('score')}")
            lines.append(f"현재 {current}({basis}, {source}, {ts}) / 진입 {entry} / 손절 {stop} / 목표 {target1}→{target2}")
            lines.append(f"위험 {risk_pct}% / 권장노출 {position}원 / {reason}")
    else:
        lines.append('조건 통과 종목 없음')
    return '\n'.join(lines)


def _fmt_int(value) -> str:
    try:
        if value is None:
            return 'N/A'
        return f"{int(round(float(value))):,}"
    except Exception:
        return str(value)
