from __future__ import annotations

import requests
from config import settings


def telegram_enabled() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_telegram_message(text: str) -> bool:
    if not telegram_enabled():
        print('[notifier] Telegram 설정 없음. 메시지만 출력합니다.')
        print(text)
        return False
    url = f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage'
    resp = requests.post(url, json={
        'chat_id': settings.telegram_chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }, timeout=15)
    resp.raise_for_status()
    return True


def build_mobile_summary(payload: dict) -> str:
    fx = payload['fx']
    us_top = payload['us_long_etfs'][:3]
    kr_short = payload['kr_short_stocks'][:3]
    retirement = payload['retirement_risk_report']
    lines = []
    lines.append('📌 <b>Stock Scanner 요약</b>')
    lines.append(f"기준시각: {payload['created_at_kst']}")
    lines.append('')
    lines.append('💵 <b>환율</b>')
    lines.append(f"USD/KRW {fx['usdkrw']} / 60일평균 {fx['ma60']} / 판단: {fx['action']}")
    lines.append(f"권장 환전: {fx['suggested_conversion_ratio_pct']}% / {fx['suggested_conversion_krw']:,}원")
    lines.append('')
    lines.append('🇺🇸 <b>미국 장기 ETF 상위</b>')
    for x in us_top:
        lines.append(f"{x['ticker']} 점수 {x['score']} / 이번달 매수 {x['this_month_buy_pct']}% / {x['additional_buy_condition']}")
    lines.append('')
    lines.append('🏦 <b>퇴직연금 한도</b>')
    lines.append(f"위험자산 {retirement['risky_pct']}% / 상태: {retirement['status']} / 추가여력 {retirement['risky_buy_room_krw']:,}원")
    lines.append('')
    lines.append('🇰🇷 <b>한국 단기 일반계좌 후보</b>')
    if kr_short:
        for x in kr_short:
            lines.append(f"{x['name']}({x['code']}) 점수 {x['score']} / 진입 {x['entry']:,} / 손절 {x['stop_loss']:,} / 목표 {x['target1']:,}")
    else:
        lines.append('조건 통과 종목 없음')
    return '\n'.join(lines)
