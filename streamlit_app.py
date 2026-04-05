import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
from datetime import datetime

# --- 設定ファイルのパス ---
SETTINGS_FILE = "bot_settings.json"

# 1. 接続設定
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]

# 2. 認証
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# --- 設定の読み書き機能 ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    res = requests.post(base_url, data=payload)
    res_data = res.json()
    if "id" not in res_data: return False, res_data
    container_id = res_data["id"]
    time.sleep(2)
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN})
    return ("id" in res_pub.json()), res_pub.json()

# --- UI：設定画面 ---
st.title("🤖 究極の放置型 Threads BOT")

# 現在の設定を読み込む
current_settings = load_settings()

st.sidebar.header("⚙️ 投稿ルールの変更")
new_hours = st.sidebar.multiselect(
    "投稿を許可する時間（時）",
    options=list(range(24)),
    default=current_settings["allowed_hours"]
)
new_max = st.sidebar.number_input(
    "1日の最大投稿数", 
    min_value=1, max_value=24, 
    value=current_settings["max_posts"]
)

# 変更があったら保存
if new_hours != current_settings["allowed_hours"] or new_max != current_settings["max_posts"]:
    save_settings({"allowed_hours": new_hours, "max_posts": new_max})
    st.sidebar.success("設定を保存しました！")

# --- 実行ロジック ---
now = datetime.now()
st.write(f"現在時刻: {now.hour}時 / 今日の最大投稿数: {new_max}")

# 今日の投稿数をカウント
all_rows = sheet.get_all_values()
today_str = now.strftime("%Y-%m-%d")
posts_today = sum(1 for row in all_rows if len(row) > 6 and today_str in row[6])

if now.hour in new_hours and posts_today < new_max:
    st.info("条件一致。投稿をチェックします...")
    for i, row in enumerate(all_rows[1:], start=2):
        texts = [row[0], row[1], row[2], row[3], row[4]]
        status = row[5]
        if texts[0] and not status:
            last_id = None
            all_ok = True
            valid_texts = [t for t in texts if t.strip()]
            for t in valid_texts:
                success, res = post_to_threads(t, reply_to_id=last_id)
                if success:
                    last_id = res
                    time.sleep(2)
                else:
                    all_ok = False; break
            if all_ok:
                sheet.update_cell(i, 6, "完了")
                sheet.update_cell(i, 7, now.strftime("%Y-%m-%d %H:%M:%S"))
                st.success(f"{i}行目の投稿完了！")
            break
else:
    st.write("待機中です（時間外または上限到達）")
