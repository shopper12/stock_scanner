from __future__ import annotations

import pandas as pd
import streamlit as st
from database.db import latest_payload
from scan_once import run_full_scan

st.set_page_config(page_title='Stock Scanner', layout='wide')
st.title('Stock Scanner - Mobile Dashboard')

if st.button('수동 스캔 실행'):
    payload = run_full_scan(notify=False)
    st.success('스캔 완료')
else:
    payload = latest_payload('full_scan')

if payload is None:
    st.info('저장된 스캔 결과가 없습니다. 수동 스캔 실행을 누르세요.')
    st.stop()

st.caption(f"기준시각: {payload['created_at_kst']} / mode={payload.get('mode')}")

fx = payload['fx']
st.subheader('1. 달러 환전 신호')
fx_cols = st.columns(5)
fx_cols[0].metric('USD/KRW', fx['usdkrw'])
fx_cols[1].metric('60일 평균', fx['ma60'], f"{fx['gap_vs_60d_pct']}%")
fx_cols[2].metric('DXY', fx['dxy'])
fx_cols[3].metric('미국 10년물', fx['us10y'])
fx_cols[4].metric('판단', fx['action'])
st.write(f"권장 환전금액: {fx['suggested_conversion_krw']:,}원 / 사유: {fx['reason']}")

st.subheader('2. 미국 장기 ETF 분할매수')
us_df = pd.DataFrame(payload['us_long_etfs'])
st.dataframe(us_df, use_container_width=True)

st.subheader('3. 한국 퇴직연금 ETF')
risk = payload['retirement_risk_report']
ret_cols = st.columns(4)
ret_cols[0].metric('위험자산 비중', f"{risk['risky_pct']}%")
ret_cols[1].metric('안전자산 비중', f"{risk['safe_pct']}%")
ret_cols[2].metric('위험자산 추가여력', f"{risk['risky_buy_room_krw']:,}원")
ret_cols[3].metric('상태', risk['status'])
ret_df = pd.DataFrame(payload['kr_retirement_etfs'])
st.dataframe(ret_df, use_container_width=True)

st.subheader('4. 한국 단기 일반계좌 후보')
kr_short_df = pd.DataFrame(payload['kr_short_stocks'])
st.dataframe(kr_short_df, use_container_width=True)

st.subheader('5. DCA 백테스트')
st.json(payload['dca_backtest'])
