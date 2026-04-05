import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import random
import json
from datetime import datetime, date

# --- ページ設定 ---
st.set_page_config(page_title="Threads Pro Poster", page_icon="⏰")
st.title("⏰ Threads 時間帯指定・ツリー時間差投稿")

if 'running' not in st.session_state: st.session_state.running = False
if 'logs' not in st.session_state: st.session_state.logs = []
if 'target_minute' not in st.session_state: st.session_state.target_minute = random.randint(0, 50)

def add_log(message):
    now = datetime.now().strftime("%m/%d %H:%M:%S")
    st.session_state.logs.append(f"[{now}] {message}")
    if len(st.session_state.logs) > 50: st.session_state.logs.pop(0)

# --- サイドバー：詳細設定 ---
st.sidebar.header("⚙️ 基本設定")
spreadsheet_id = st.sidebar.text_input("スプレッドシートID")
threads_access_token = st.sidebar.text_input("Threads Access Token", type="password")
threads_user_id = st.sidebar.text_input("Threads User ID")
uploaded_file = st.sidebar.file_uploader("Google Credentials (JSON)", type="json")

st.sidebar.header("🎯 投稿スケジュール設定")
target_hours = st.sidebar.multiselect(
    "投稿を許可する時間帯 (時)", 
    options=list(range(24)), 
    default=[7, 8, 12, 18, 21],
    help="選んだ時間帯の中でランダムに1回投稿を開始します。"
)
max_daily_posts = st.sidebar.slider("1日の最大投稿合計数", 1, 24, 5)

# --- API関数 ---
def get_gspread_client(json_info):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(json_info, scopes=scopes)
    return gspread.authorize(creds)

def post_to_threads(text, access_token, user_id, reply_to_id=None):
    url = f"https://graph.threads.net/v1.0/{user_id}/threads"
    params = {'media_type': 'TEXT', 'text': text, 'access_token': access_token}
    if reply_to_id: params['reply_to_id'] = reply_to_id
    res = requests.post(url, params=params).json()
    if 'id' not in res: raise Exception(f"Container Error: {res}")
    pub_res = requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads_publish", 
                            params={'creation_id': res['id'], 'access_token': access_token}).json()
    return pub_res.get('id')

# --- メイン実行 ---
col1, col2 = st.columns(2)
if col1.button("実行開始", use_container_width=True, type="primary"):
    if not (spreadsheet_id and threads_access_token and uploaded_file):
        st.error("設定が足りません")
    else:
        st.session_state.running = True
        add_log("システムを起動しました。")

if col2.button("停止", use_container_width=True):
    st.session_state.running = False
    st.warning("停止します...")

if st.session_state.running:
    status_placeholder = st.empty()
    log_placeholder = st.empty()
    
    service_account_info = json.load(uploaded_file)
    gc = get_gspread_client(service_account_info)
    sheet = gc.open_by_key(spreadsheet_id).get_worksheet(0)

    while st.session_state.running:
        now = datetime.now()
        current_hour = now.hour
        current_min = now.minute
        today_str = date.today().isoformat()
        
        df = pd.DataFrame(sheet.get_all_records())
        
        if '投稿日時' in df.columns:
            today_df = df[df['投稿日時'].astype(str).str.contains(today_str)]
            today_posts_count = len(today_df)
            already_posted_this_hour = any(pd.to_datetime(today_df['投稿日時']).dt.hour == current_hour)
        else:
            today_posts_count = 0
            already_posted_this_hour = False

        status_placeholder.metric("今日の進捗", f"{today_posts_count} / {max_daily_posts} 件")

        is_target_hour = current_hour in target_hours
        
        if today_posts_count >= max_daily_posts:
            msg = "本日の上限に達しました。"
        elif not is_target_hour:
            msg = f"待機時間外です（次は {min([h for h in target_hours if h > current_hour] or [min(target_hours)])}時台の予定）"
        elif already_posted_this_hour:
            msg = f"{current_hour}時台は投稿済みです。次を待ちます。"
        elif current_min < st.session_state.target_minute:
            msg = f"{current_hour}時台の投稿予定まであと {st.session_state.target_minute - current_min} 分"
        else:
            # 投稿処理
            pending_rows = df[df['投稿ステータス'] == '未']
            if pending_rows.empty:
                msg = "「未」のデータがありません。"
            else:
                target_index = random.choice(pending_rows.index)
                row_data = df.iloc[target_index]
                row_num = target_index + 2
                
                try:
                    add_log(f"🚀 親ポスト（本文1）を投稿中...")
                    parent_id = post_to_threads(row_data['本文1'], threads_access_token, threads_user_id)
                    
                    # ツリー投稿ループ（本文2〜5）
                    for i in range(2, 6):
                        col_name = f'本文{i}'
                        if col_name in row_data and row_data[col_name]:
                            # ★ここで5分（300秒）待機
                            add_log(f"⏳ {col_name} の投稿まで5分間待機します...")
                            for wait_sec in range(300, 0, -1):
                                if not st.session_state.running: break
                                status_placeholder.warning(f"ツリー投稿待機中: あと {wait_sec // 60}分 {wait_sec % 60}秒")
                                time.sleep(1)
                            
                            if st.session_state.running:
                                post_to_threads(row_data[col_name], threads_access_token, threads_user_id, reply_to_id=parent_id)
                                add_log(f"✅ {col_name} を投稿しました。")
                    
                    # 完了更新
                    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sheet.update_cell(row_num, df.columns.get_loc('投稿ステータス') + 1, '済')
                    sheet.update_cell(row_num, df.columns.get_loc('投稿日時') + 1, now_ts)
                    add_log("✨ 全スレッドの投稿が完了しました！")
                    
                    st.session_state.target_minute = random.randint(0, 50)
                    msg = "次の時間帯まで待機します。"
                except Exception as e:
                    add_log(f"❌ エラー: {e}")
                    st.session_state.running = False
                    break

        status_placeholder.info(f"状態: {msg}")
        log_placeholder.code("\n".join(st.session_state.logs[::-1]))
        time.sleep(60)

# ログ表示
st.subheader("📝 実行ログ")
st.code("\n".join(st.session_state.logs[::-1]))
