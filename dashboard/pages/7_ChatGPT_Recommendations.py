from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chat_picks import CHAT_HISTORY_PATH, COMMON_HISTORY_PATH, seed_current_conversation_picks


PREFERRED_COLS = [
    'recommended_at_kst',
    'source',
    'code',
    'name',
    'market',
    'sector',
    'strategy_type',
    'price_at_recommendation',
    'entry_low',
    'entry_high',
    'entry',
    'stop_loss',
    'target1',
    'target2',
    'latest_price',
    'pnl_pct',
    'pnl_krw_per_share',
    'reason',
    'risk',
    'failure_condition',
    'source_note',
]


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {'schema_version': 1, 'items': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {'schema_version': 1, 'items': []}
        data.setdefault('items', [])
        return data
    except Exception:
        return {'schema_version': 1, 'items': []}


def _order_cols(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ordered = [col for col in PREFERRED_COLS if col in df.columns]
    rest = [col for col in df.columns if col not in ordered]
    return df[ordered + rest]


def _fmt_krw(value) -> str:
    try:
        if value is None or value == '':
            return 'N/A'
        return f"{int(round(float(value))):,}원"
    except Exception:
        return 'N/A'


st.set_page_config(page_title='ChatGPT 추천기록', layout='wide')
st.title('ChatGPT 대화 추천기록')
st.caption('이 대화에서 생성한 추천 종목을 scanner 추천 히스토리와 별도 chat 히스토리에 저장해서 확인하는 화면입니다.')

cols = st.columns(3)
if cols[0].button('현재 대화 추천 seed 저장'):
    seed_current_conversation_picks(notify=False)
    st.success('현재 대화의 기존 추천 종목을 저장했습니다.')
if cols[1].button('현재 대화 추천 seed 저장 + 텔레그램 발송'):
    seed_current_conversation_picks(notify=True)
    st.success('저장 후 텔레그램 발송을 요청했습니다. TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 설정이 없으면 콘솔에만 출력됩니다.')
cols[2].write(f'히스토리 파일: `{CHAT_HISTORY_PATH.relative_to(ROOT_DIR)}`')

chat_data = _read_json(CHAT_HISTORY_PATH)
common_data = _read_json(COMMON_HISTORY_PATH)
items = chat_data.get('items', [])

st.subheader('1. ChatGPT 대화 추천')
if not items:
    st.info('아직 저장된 ChatGPT 대화 추천이 없습니다. 위 버튼을 누르거나 `python chat_picks.py add ... --notify`를 실행하세요.')
else:
    df = _order_cols(pd.DataFrame(items))
    top = items[0]
    metric_cols = st.columns(5)
    metric_cols[0].metric('최근 추천', f"{top.get('name')}({top.get('code')})")
    metric_cols[1].metric('진입', _fmt_krw(top.get('entry')))
    metric_cols[2].metric('손절', _fmt_krw(top.get('stop_loss')))
    metric_cols[3].metric('1차 목표', _fmt_krw(top.get('target1')))
    metric_cols[4].metric('손익률', f"{top.get('pnl_pct', 'N/A')}%")
    st.dataframe(df, use_container_width=True)

st.subheader('2. 통합 추천 히스토리 반영 상태')
common_items = common_data.get('items', [])
st.caption(f"통합 히스토리 항목 수: {len(common_items)} / 파일: `{COMMON_HISTORY_PATH.relative_to(ROOT_DIR)}`")
if common_items:
    common_df = _order_cols(pd.DataFrame(common_items))
    st.dataframe(common_df.head(100), use_container_width=True)

st.subheader('3. CLI 입력 예시')
st.code(
    "python chat_picks.py add --code 000660 --name SK하이닉스 --sector 반도체/HBM "
    "--strategy-type chat_close_bet --current-price 2071500 --entry-low 2055000 "
    "--entry-high 2075000 --stop-loss 2025000 --target1 2087000 --target2 2120000 "
    "--rationale \"AI/HBM 주도주, 외국인·기관 수급\" --risk \"고가권 추격 리스크\" --notify",
    language='powershell',
)
