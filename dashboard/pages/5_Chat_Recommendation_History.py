from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import streamlit as st

from data.trade_history_schema import read_trade_history, write_trade_history


DISPLAY_COLS = [
    'date', 'session', 'asset_type', 'ticker', 'name', 'currency',
    'entry_low', 'entry_high', 'entry_mid', 'stop_loss', 'target1', 'target2',
    'current_price', 'current_price_time', 'current_price_source',
    'pnl_vs_entry_mid_pct', 'distance_to_target1_pct', 'distance_to_stop_pct',
    'status', 'source_status', 'memo',
]


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


def recalc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ['entry_low', 'entry_high', 'entry_mid', 'stop_loss', 'target1', 'target2', 'current_price']:
        if col in out.columns:
            out[col] = _num(out[col])
    missing_mid = out['entry_mid'].isna() & out['entry_low'].notna() & out['entry_high'].notna()
    out.loc[missing_mid, 'entry_mid'] = ((out.loc[missing_mid, 'entry_low'] + out.loc[missing_mid, 'entry_high']) / 2).round(6)

    valid = out['current_price'].notna() & out['entry_mid'].notna() & out['entry_mid'].ne(0)
    out.loc[valid, 'pnl_vs_entry_mid_pct'] = ((out.loc[valid, 'current_price'] / out.loc[valid, 'entry_mid'] - 1) * 100).round(2)

    valid_target = out['current_price'].notna() & out['target1'].notna() & out['current_price'].ne(0)
    out.loc[valid_target, 'distance_to_target1_pct'] = ((out.loc[valid_target, 'target1'] / out.loc[valid_target, 'current_price'] - 1) * 100).round(2)

    valid_stop = out['current_price'].notna() & out['stop_loss'].notna() & out['stop_loss'].ne(0)
    out.loc[valid_stop, 'distance_to_stop_pct'] = ((out.loc[valid_stop, 'current_price'] / out.loc[valid_stop, 'stop_loss'] - 1) * 100).round(2)

    target_hit = out['current_price'].notna() & out['target1'].notna() & (out['current_price'] >= out['target1'])
    stop_hit = out['current_price'].notna() & out['stop_loss'].notna() & (out['current_price'] <= out['stop_loss'])
    out.loc[target_hit, 'status'] = 'target1_hit'
    out.loc[stop_hit, 'status'] = 'stop_hit'
    out['status'] = out['status'].fillna('open')
    return out


st.set_page_config(page_title='Chat Recommendation History', layout='wide')
st.title('대화 추천 히스토리')

st.caption('ChatGPT 대화 중 제시된 매수·진입 전략을 강제 편입해 추적한다. 현재가는 자동 갱신 workflow 또는 이 화면의 직접 편집값 기준이다.')

df = recalc(read_trade_history())

if df.empty:
    st.info('저장된 대화 추천 히스토리가 없습니다.')
    st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric('전체', len(df))
c2.metric('진행중', int((df['status'] == 'open').sum()))
c3.metric('목표 도달', int((df['status'] == 'target1_hit').sum()))
c4.metric('손절 도달', int((df['status'] == 'stop_hit').sum()))
valid_pnl = pd.to_numeric(df['pnl_vs_entry_mid_pct'], errors='coerce').dropna()
c5.metric('평균 손익률', f"{valid_pnl.mean():.2f}%" if not valid_pnl.empty else 'N/A')

asset_types = ['ALL'] + sorted([x for x in df['asset_type'].dropna().unique().tolist()])
selected_type = st.selectbox('자산 유형', asset_types)
filtered = df if selected_type == 'ALL' else df[df['asset_type'] == selected_type]

ordered_cols = [c for c in DISPLAY_COLS if c in filtered.columns] + [c for c in filtered.columns if c not in DISPLAY_COLS]
edited = st.data_editor(
    filtered[ordered_cols],
    use_container_width=True,
    num_rows='dynamic',
    key='chat_recommendation_history_editor',
)

if st.button('히스토리 저장'):
    edited_df = pd.DataFrame(edited)
    if selected_type == 'ALL':
        new_df = edited_df
    else:
        rest = df[df['asset_type'] != selected_type]
        new_df = pd.concat([edited_df, rest], ignore_index=True)
    write_trade_history(recalc(new_df))
    st.success('저장 완료')

st.subheader('상태별 요약')
summary = (
    filtered.groupby(['asset_type', 'status'], dropna=False)
    .agg(count=('ticker', 'count'), avg_pnl_pct=('pnl_vs_entry_mid_pct', 'mean'))
    .reset_index()
)
if not summary.empty:
    summary['avg_pnl_pct'] = summary['avg_pnl_pct'].round(2)
    st.dataframe(summary, use_container_width=True)
