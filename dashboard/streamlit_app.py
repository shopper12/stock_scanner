from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import streamlit as st
from database.db import latest_payload
from scan_once import run_full_scan


def _order_cols(df: pd.DataFrame, preferred: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    ordered = [c for c in preferred if c in df.columns]
    rest = [c for c in df.columns if c not in ordered]
    return df[ordered + rest]


def _fmt_krw(value) -> str:
    try:
        return f"{int(round(float(value))):,}원"
    except Exception:
        return 'N/A'


def _latest_rule_report() -> dict | None:
    path = ROOT_DIR / 'reports' / 'kr_short_evolution_latest.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


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

mode = payload.get('mode', 'unknown')
st.caption(f"기준시각: {payload['created_at_kst']} / mode={mode}")
if mode == 'mock':
    st.warning('현재 mock 데이터 모드입니다. 실전 매매 판단에 사용하지 마세요.')

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
st.dataframe(_order_cols(us_df, ['ticker', 'name', 'asset_class', 'current_price', 'score', 'this_month_buy_pct', 'this_month_buy_krw', 'drawdown_52w_pct', 'momentum_12m_pct', 'additional_buy_condition', 'risk_summary']), use_container_width=True)

st.subheader('3. 한국 퇴직연금 ETF')
risk = payload['retirement_risk_report']
ret_cols = st.columns(4)
ret_cols[0].metric('위험자산 비중', f"{risk['risky_pct']}%")
ret_cols[1].metric('안전자산 비중', f"{risk['safe_pct']}%")
ret_cols[2].metric('위험자산 추가여력', f"{risk['risky_buy_room_krw']:,}원")
ret_cols[3].metric('상태', risk['status'])
ret_df = pd.DataFrame(payload['kr_retirement_etfs'])
st.dataframe(_order_cols(ret_df, ['code', 'name', 'asset_bucket', 'current_price', 'score', 'current_weight_pct', 'recommended_weight_pct', 'additional_buy_capacity_krw', 'rebalance_needed', 'momentum_1y_pct', 'mdd_1y_pct']), use_container_width=True)

st.subheader('4. 한국 단기 일반계좌 후보')
kr_short_df = pd.DataFrame(payload['kr_short_stocks'])
if kr_short_df.empty:
    st.info('조건 통과 종목 없음')
else:
    top = kr_short_df.iloc[0]
    m = st.columns(5)
    m[0].metric('1순위', f"{top.get('name')}({top.get('code')})")
    m[1].metric('점수', top.get('score'))
    m[2].metric('셋업', top.get('strategy_type', 'N/A'))
    m[3].metric('위험폭', f"{top.get('risk_pct', 'N/A')}%")
    m[4].metric('권장노출', _fmt_krw(top.get('position_size_krw')))
    st.caption('가격 기준: current_price는 price_basis/price_timestamp에 표시된 데이터 기준입니다. 실시간 호가가 아니라면 진입 전 증권사 현재가로 재확인해야 합니다.')
    show_cols = ['code', 'name', 'sector', 'strategy_type', 'current_price', 'price_basis', 'price_timestamp', 'history_last_date', 'data_source', 'score', 'entry', 'stop_loss', 'target1', 'target2', 'risk_pct', 'position_size_krw', 'volume_ratio_20d', 'trade_value_ratio_20d', 'trade_value_krw', 'momentum_20d_pct', 'reason', 'failure_condition']
    st.dataframe(_order_cols(kr_short_df, show_cols), use_container_width=True)

st.subheader('5. 한국 단기 조건 검증 리포트')
report = _latest_rule_report()
if report is None:
    st.info('아직 생성된 조건 검증 리포트가 없습니다. tools/kr_short_check.py를 실행하세요.')
else:
    cols = st.columns(5)
    cols[0].metric('생성시각', str(report.get('created_at_kst', 'N/A')))
    cols[1].metric('개선폭', report.get('improvement', 'N/A'))
    cols[2].metric('적용 가능', str(report.get('accepted', 'N/A')))
    cols[3].metric('기준 fitness', report.get('base_fitness', 'N/A'))
    cols[4].metric('최고 fitness', report.get('best_fitness', 'N/A'))

    base_summary = report.get('base_summary', {})
    best_summary = report.get('best_summary', {})
    summary_df = pd.DataFrame([
        {'case': 'base', **{k: base_summary.get(k) for k in ['trades', 'avg_return_pct', 'win_rate', 'surge_precision', 'profit_factor', 'stop_rate', 'target_rate']}},
        {'case': 'best', **{k: best_summary.get(k) for k in ['trades', 'avg_return_pct', 'win_rate', 'surge_precision', 'profit_factor', 'stop_rate', 'target_rate']}},
    ])
    st.dataframe(summary_df, use_container_width=True)

    ai = report.get('ai_review')
    if ai:
        with st.expander('AI 리포트 리뷰'):
            st.json(ai)
    with st.expander('전체 검증 리포트 JSON'):
        st.json(report)

st.subheader('6. DCA 백테스트')
st.json(payload['dca_backtest'])
