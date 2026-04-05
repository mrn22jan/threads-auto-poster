import streamlit as st
import gspread
import requests
import time
from google.oauth2.service_account import Credentials
from datetime import datetime

# 1. 接続設定（StreamlitのSecretsから読み込み）
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]

# 2. 認証処理
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

def post_to_threads(text, reply_to=None):
    """Threadsに1件投稿し、その投稿IDを返す"""
    url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    params = {'text': text, 'access_token': ACCESS_TOKEN}
    if reply_to:
        params['reply_to_id'] = reply_to
    
    # メディアコンテナ作成
    res = requests.post(url, params=params).json()
    container_id = res.get('id')
    
    # 公開（Publish）
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    publish_res = requests.post(publish_url, params={'creation_id': container_id, 'access_token': ACCESS_TOKEN}).json()
    return publish_res.get('id')

# 3. 画面表示
st.title("🧵 Threads 投稿マネージャー")
st.write("ボタンを押すと、スプレッドシートの「投稿ステータス」が空の行をすべて投稿します。")

if st.button("未投稿のものを今すぐ実行"):
    # 全データを取得
    records = sheet.get_all_records()
    
    for i, row in enumerate(records):
        # 投稿ステータス（F列）が空欄の場合のみ実行
        if str(row.get("投稿ステータス", "")).strip() == "":
            st.info(f"{i+2}行目の投稿を開始します...")
            last_id = None
            
            # 本文1〜5を順番に投稿（スレッドにする）
            for key in ["本文1", "本文2", "本文3", "本文4", "本文5"]:
                text = str(row.get(key, "")).strip()
                if text and text != "None":
                    last_id = post_to_threads(text, reply_to=last_id)
                    time.sleep(2) # 連続投稿エラー防止
            
            # 完了したらステータスと日時を書き込む
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.update_cell(i + 2, 6, "完了") # F列
            sheet.update_cell(i + 2, 7, now_str) # G列
            st.success(f"{i+2}行目の投稿が完了しました！ ({now_str})")
