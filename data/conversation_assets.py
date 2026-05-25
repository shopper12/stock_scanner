from __future__ import annotations

import pandas as pd


CONVERSATION_SOURCE = 'chatgpt_conversation_2026_05_20_25'

# 한국 단기 일반계좌 스캐너에 반영할 대화 기반 관심 종목.
# 원칙: 이 목록은 유니버스 누락 방지와 소폭 점수 보정용이며, 가격/차트/리스크 필터를 대체하지 않는다.
CONVERSATION_KR_STOCKS: list[dict] = [
    {'code': '005930', 'name': '삼성전자', 'sector': '반도체', 'priority': 5, 'tags': ['AI반도체', '메모리', '대형주']},
    {'code': '000660', 'name': 'SK하이닉스', 'sector': '반도체', 'priority': 5, 'tags': ['HBM', 'AI메모리', '대형주']},
    {'code': '036930', 'name': '주성엔지니어링', 'sector': '반도체장비/소재', 'priority': 5, 'tags': ['반도체장비', '거래대금', '신고가']},
    {'code': '267260', 'name': 'HD현대일렉트릭', 'sector': '전력기기/전선', 'priority': 5, 'tags': ['전력인프라', '데이터센터', '변압기']},
    {'code': '034020', 'name': '두산에너빌리티', 'sector': '원전/에너지', 'priority': 4, 'tags': ['원전', '전력인프라', 'AI전력']},
    {'code': '329180', 'name': 'HD현대중공업', 'sector': '조선/해양', 'priority': 4, 'tags': ['조선', '엔진', '데이터센터전력']},
    {'code': '001440', 'name': '대한전선', 'sector': '전력기기/전선', 'priority': 4, 'tags': ['전선', '전력망']},
    {'code': '047810', 'name': '한국항공우주', 'sector': '방산/우주', 'priority': 3, 'tags': ['방산', '항공우주', 'KAI']},
    {'code': '100090', 'name': 'SK오션플랜트', 'sector': '친환경/풍력/태양광', 'priority': 3, 'tags': ['해상풍력', '해양플랜트']},
    {'code': '036540', 'name': 'SFA반도체', 'sector': '반도체장비/소재', 'priority': 3, 'tags': ['반도체후공정', '패키징']},
    {'code': '018880', 'name': '한온시스템', 'sector': '자동차/부품', 'priority': 2, 'tags': ['자동차부품', '열관리']},
    {'code': '003380', 'name': '하림지주', 'sector': '화장품/소비', 'priority': 2, 'tags': ['지주사', '소비']},
    {'code': '043260', 'name': '성호전자', 'sector': 'PCB/전자부품', 'priority': 3, 'tags': ['전자부품', '강추세차트']},
    {'code': '052710', 'name': '아모텍', 'sector': 'PCB/전자부품', 'priority': 3, 'tags': ['전자부품', '차트분석']},
]

# 한국상장 ETF는 현재 KR_SHORT_STOCK 엔진의 개별주 필터와 분리해 보고서/대시보드 참고 목록으로 기록한다.
CONVERSATION_KR_ETFS: list[dict] = [
    {'code': '091160', 'name': 'KODEX 반도체', 'theme': '국내 반도체', 'priority': 4, 'tags': ['반도체ETF', '한국상장ETF']},
    {'code': '471990', 'name': 'KODEX AI반도체핵심장비', 'theme': 'AI 반도체 장비', 'priority': 5, 'tags': ['AI반도체', '장비ETF', '한국상장ETF']},
    {'code': '381180', 'name': 'TIGER 미국필라델피아반도체나스닥', 'theme': '미국 반도체', 'priority': 4, 'tags': ['필라델피아반도체', '한국상장ETF']},
]

CONVERSATION_US_ASSETS: list[dict] = [
    {'ticker': 'NVDA', 'name': 'NVIDIA', 'asset_type': 'us_equity', 'priority': 5, 'tags': ['AI반도체', 'GPU']},
    {'ticker': 'AVGO', 'name': 'Broadcom', 'asset_type': 'us_equity', 'priority': 4, 'tags': ['AI네트워크', '반도체']},
    {'ticker': 'SOXX', 'name': 'iShares Semiconductor ETF', 'asset_type': 'us_etf', 'priority': 4, 'tags': ['반도체ETF']},
    {'ticker': 'SMH', 'name': 'VanEck Semiconductor ETF', 'asset_type': 'us_etf', 'priority': 4, 'tags': ['반도체ETF']},
]

CONVERSATION_CRYPTO_ASSETS: list[dict] = [
    {'symbol': 'BTC', 'name': 'Bitcoin', 'priority': 5, 'tags': ['시장레짐', '기준자산']},
    {'symbol': 'ETH', 'name': 'Ethereum', 'priority': 4, 'tags': ['메이저알트', 'ETF기대']},
    {'symbol': 'SOL', 'name': 'Solana', 'priority': 4, 'tags': ['메이저알트', '상대강도']},
]


def get_conversation_kr_stock_rows() -> pd.DataFrame:
    rows = []
    for item in CONVERSATION_KR_STOCKS:
        row = item.copy()
        row['code'] = str(row['code']).zfill(6)
        row['conversation_source'] = CONVERSATION_SOURCE
        row['conversation_tags'] = ','.join(row.get('tags', []))
        rows.append(row)
    return pd.DataFrame(rows)


def get_conversation_kr_stock_map() -> dict[str, dict]:
    return {
        str(row['code']).zfill(6): row
        for row in get_conversation_kr_stock_rows().to_dict('records')
    }


def get_conversation_assets_payload() -> dict:
    return {
        'source': CONVERSATION_SOURCE,
        'kr_stocks': get_conversation_kr_stock_rows().to_dict('records'),
        'kr_etfs': CONVERSATION_KR_ETFS,
        'us_assets': CONVERSATION_US_ASSETS,
        'crypto_assets': CONVERSATION_CRYPTO_ASSETS,
        'scanner_policy': 'KR stocks are rescanned with the KR_SHORT_STOCK filters and a small conversation-priority bonus. KR ETFs, US assets, and crypto are recorded as reference assets unless a dedicated engine exists.',
    }
