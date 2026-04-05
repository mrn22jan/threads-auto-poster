import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import random
import logging
from datetime import datetime

# --- ロギング設定 ---
logging.basicConfig(level=logging.INFO)

# --- ページ設定 ---
st.set_page_config(page_title="Threads Auto-Poster", page_icon="📝")
st.title("🚀 Threads 自動投稿システム")

# --- セッション状態の初期化 ---
if 'running' not in st.session_state:
    st.session_state.running = False
if 'logs' not in st.session_state:
    st.session_state.logs = []

def add_log(message):
    now = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{now}] {message}")
    if len(st.session_state.logs) > 50:
        st.session_state.logs.pop(0)

# --- サイドバー：設定 ---
st.sidebar.header("⚙️ 設定")
spreadsheet_id = st.sidebar.text_input("スプレッドシートID")
threads_access_token = st.sidebar.text_input("Threads Access Token", type="password")
threads_user_id = st.sidebar.text_input("Threads User ID (数値)")

st.sidebar.subheader("⏳ 待機時間設定 (分)")
min_wait = st.sidebar.number_input("最小待機時間", value=15, min_value=1)
max_wait = st.sidebar.number_input("最大待機時間", value=60, min_value=min_wait)

uploaded_file = st.sidebar.file_uploader("Google Credentials (JSON) をアップロード", type="json")

# --- API連携関数 ---
def get_gspread_client(json_file):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(json_file, scopes=scopes)
    return gspread.authorize(creds)

def post_to_threads(text, access_token, user_id, reply_to_id=None):
    url = f"https://graph.threads.net/v1.0/{user_id}/threads"
    params = {
        'media_type': 'TEXT',
        'text': text,
        'access_token': access_token
    }
    if reply_to_id:
        params['reply_to_id'] = reply_to_id
    
    # メディアコンテナ作成
    res = requests.post(url, params=params)
    res_data = res.json()
    if 'id' not in res_data:
        raise Exception(f"Container Error: {res_data}")
    
    creation_id = res_data['id']
    
    # 公開
    publish_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
    publish_params = {'creation_id': creation_id, 'access_token': access_token}
    pub_res = requests.post(publish_url, params=publish_params)
    pub_data = pub_res.json()
    
    if 'id' not in pub_data:
        raise Exception(f"Publish Error: {pub_data}")
    return pub_data['id']

# --- メインロジック ---
col1, col2 = st.columns(2)
start_btn = col1.button("実行開始", use_container_width=True, type="primary")
stop_btn = col2.button("停止", use_container_width=True)

if stop_btn:
    st.session_state.running = False
    st.warning("停止コマンドを受け付けました。現在の処理終了後に停止します。")

if start_btn:
    if not (spreadsheet_id and threads_access_token and uploaded_file and threads_user_id):
        st.error("すべての設定項目を入力し、JSONファイルをアップロードしてください。")
    else:
        st.session_state.running = True
        add_log("システムを起動しました。")

# 実行ループ
if st.session_state.running:
    status_placeholder = st.empty()
    log_placeholder = st.empty()
    
    import json
    service_account_info = json.load(uploaded_file)
    gc = get_gspread_client(service_account_info)
    sheet = gc.open_by_key(spreadsheet_id).get_worksheet(0)

    while st.session_state.running:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # 「投稿ステータス」が「未」の行を抽出
        pending_rows = df[df['投稿ステータス'] == '未']
        
        if pending_rows.empty:
            add_log("「未」のデータがありません。待機中...")
            time.sleep(30)
            continue
        
        # ランダムに1件選択
        target_index = random.choice(pending_rows.index)
        row_data = df.iloc[target_index]
        row_num = target_index + 2 # スプレッドシートの行番号 (ヘッダー+0始まり補正)

        try:
            add_log(f"{row_num}行目の投稿を開始します。")
            
            # 親ポスト投稿
            parent_id = post_to_threads(row_data['本文1'], threads_access_token, threads_user_id)
            
            # ツリー投稿（本文2, 本文3...がある場合）
            for i in range(2, 11): # 最大本文10まで対応
                col_name = f'本文{i}'
                if col_name in row_data and row_data[col_name]:
                    time.sleep(2) # APIの安定のため少し待機
                    post_to_threads(row_data[col_name], threads_access_token, threads_user_id, reply_to_id=parent_id)
            
            # ステータス更新
            sheet.update_cell(row_num, df.columns.get_loc('投稿ステータス') + 1, '済')
            add_log("投稿成功！ステータスを「済」に更新しました。")
            
        except Exception as e:
            add_log(f"エラー発生: {e}")
            st.session_state.running = False
            break

        # ランダム待機
        wait_time = random.randint(min_wait * 60, max_wait * 60)
        add_log(f"次の投稿まで {wait_time // 60} 分待機します...")
        
        # 待機時間を分割して表示更新
        for s in range(wait_time, 0, -1):
            if not st.session_state.running: break
            status_placeholder.info(f"⏳ 次の投稿まであと {s // 60} 分 {s % 60} 秒")
            log_placeholder.code("\n".join(st.session_state.logs[::-1]))
            time.sleep(1)

# ログの表示
st.subheader("📝 実行ログ")
st.code("\n".join(st.session_state.logs[::-1]))
