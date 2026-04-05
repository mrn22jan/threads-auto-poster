import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
from datetime import datetime

# 1. 接続設定（StreamlitのSecretsから読み込み）
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]

# 2. Googleスプレッドシートの認証
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

def post_to_threads(text):
    """Threadsに投稿し、成功ならIDを、失敗ならエラーメッセージを返す"""
    # ① 投稿コンテナの作成
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    params = {
        "media_type": "TEXT",
        "text": text,
        "access_token": ACCESS_TOKEN
    }
    
    res = requests.post(base_url, data=params)
    res_data = res.json()
    
    if "id" not in res_data:
        return False, res_data # 作成失敗
        
    container_id = res_data["id"]
    
    # ② 投稿の公開
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    publish_params = {
        "creation_id": container_id,
        "access_token": ACCESS_TOKEN
    }
    
    # 少し待機（Threads側の反映待ち）
    time.sleep(2)
    
    res_pub = requests.post(publish_url, data=publish_params)
    res_pub_data = res_pub.json()
    
    if "id" in res_pub_data:
        return True, res_pub_data["id"] # 成功
    else:
        return False, res_pub_data # 公開失敗

# --- Streamlit UI ---
st.title("🧵 Threads 投稿マネージャー")
st.write("ボタンを押すと、スプレッドシートの「投稿ステータス」が空の行をすべて投稿します。")

if st.button("未投稿のものを今すぐ実行"):
    data = sheet.get_all_values()
    headers = data[0]
    rows = data[1:]
    
    # 列番号の特定（F列:投稿ステータス, G列:投稿日時）
    status_col_idx = 6 
    date_col_idx = 7
    
    for i, row in enumerate(rows, start=2):
        text = row[0] # A列:本文1
        status = row[5] # F列:ステータス
        
        if text and not status:
            st.info(f"{i}行目の投稿を開始します...")
            
            # Threads投稿実行
            success, result = post_to_threads(text)
            
            if success:
                # 成功した時だけシートを更新
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sheet.update_cell(i, status_col_idx, "完了")
                sheet.update_cell(i, date_col_idx, now)
                st.success(f"✅ {i}行目の投稿が完了しました！ (ID: {result})")
            else:
                # ❌ 失敗した場合はエラー内容を画面に大きく表示
                st.error(f"❌ {i}行目でエラーが発生しました。Threads側が拒否しています。")
                st.json(result) # エラーのJSONをそのまま表示
                st.warning("このエラーを解消するまで、他の行の投稿を停止します。")
                break
    else:
        st.write("未投稿のデータはありませんでした。")
