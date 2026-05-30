from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from chat_picks import CHAT_HISTORY_PATH, COMMON_HISTORY_PATH
from chat_sync import read_sync_state, sync_remote_chat_history


st.set_page_config(page_title='Auto Sync', layout='wide')
st.title('ChatGPT Picks Auto Sync')

state = sync_remote_chat_history()
st.json(state)

chat = json.loads(CHAT_HISTORY_PATH.read_text(encoding='utf-8')) if CHAT_HISTORY_PATH.exists() else {'items': []}
common = json.loads(COMMON_HISTORY_PATH.read_text(encoding='utf-8')) if COMMON_HISTORY_PATH.exists() else {'items': []}

st.subheader('Chat history')
items = chat.get('items', [])
if items:
    st.dataframe(pd.DataFrame(items), use_container_width=True)
else:
    st.info('No chat history items yet.')

st.subheader('Common history')
common_items = common.get('items', [])
if common_items:
    st.dataframe(pd.DataFrame(common_items).head(100), use_container_width=True)
else:
    st.info('No common history items yet.')

with st.expander('Last sync state'):
    st.json(read_sync_state())
