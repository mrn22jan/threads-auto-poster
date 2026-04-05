import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone

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

# --- 日本時間(JST)を取得する関数 ---
def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# --- 設定の読み書き機能 ---
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        res = requests.post(base_url, data=payload)
        res_data = res.json()
        if "id" not in res_data: return False, res_data
        
        container_id = res_data["id"]
        time.sleep(2)
        
        publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN})
        res_pub_data = res_pub.json()
        
        if "id" in res_pub_data:
            return True, res_pub_data["id"]
        else:
            return False, res_pub_data
    except Exception as e:
        return False, str(e)

# --- UI：設定画面（サイドバー） ---
current_settings = load_settings()
st.sidebar.header("⚙️ 自動投稿ルール")
new_hours = st.sidebar.multiselect(
    "投稿許可時間（時）※日本時間",
    options=list(range(24)),
    default=current_settings["allowed_hours"]
)
new_max = st.sidebar.number_input(
    "1日の最大投稿数", 
    min_value=1, max_value=24, 
    value=current_settings["max_posts"]
)

if new_hours != current_settings["allowed_hours"] or new_max != current_settings["max_posts"]:
    save_settings({"allowed_hours": new_hours, "max_posts": new_max})
    st.sidebar.success("ルールを更新しました！")

# --- メイン画面 ---
st.title("🤖 Threads 自動投稿 & テスト")

# --- 🧪 即時テスト投稿セクション ---
st.subheader("🧪 即時テスト投稿")
with st.expander("ここから手動でテスト投稿ができます"):
    test_text1 = st.text_area("テスト投稿（1つ目）", placeholder="今すぐ投稿したい内容を入力...")
    test_text2 = st.text_area("テスト投稿ツリー（2つ目：返信）", placeholder="1つ目への返信として繋げたい内容を入力...")
    
    if st.button("🚀 今すぐテスト実行"):
        if not test_text1:
            st.error("投稿内容が空です。")
        else:
            with st.spinner("投稿中..."):
                # 1つ目の投稿
                success1, res1 = post_to_threads(test_text1)
                if success1:
                    st.success(f"1つ目の投稿に成功しました！ ID: {res1}")
                    # 2つ目（ツリー）があれば投稿
                    if test_text2:
                        success2, res2 = post_to_threads(test_text2, reply_to_id=res1)
                        if success2:
                            st.success(f"ツリー投稿に成功しました！ ID: {res2}")
                        else:
                            st.error(f"ツリー投稿に失敗: {res2}")
                else:
                    st.error(f"1つ目の投稿に失敗: {res1}")

st.divider()

# --- 🤖 自動投稿状況セクション ---
st.subheader("📅 自動投稿の稼働状況")
jst_now = get_jst_now()
current_hour = jst_now.hour

st.write(f"⌚️ 現在の日本時間: **{jst_now.strftime('%H:%M:%S')}**")

# 今日の投稿数をカウント
all_rows = sheet.get_all_values()
today_str = jst_now.strftime("%Y-%m-%d")
posts_today = sum(1 for row in all_rows if len(row) > 6 and today_str in row[6])

st.write(f"📝 本日の自動投稿済み: **{posts_today} / {new_max}**")

# 自動投稿ロジック
if current_hour in new_hours and posts_today < new_max:
    st.info("🕒 現在は投稿許可時間内です。")
    for i, row in enumerate(all_rows[1:], start=2):
        texts = [row[0], row[1], row[2], row[3], row[4]]
        status = row[5]
        if texts[0] and not status:
            st.warning(f"📄 スプレッドシート {i}行目を自動投稿します...")
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
                sheet.update_cell(i, 7, jst_now.strftime("%Y-%m-%d %H:%M:%S"))
                st.success(f"✅ {i}行目の自動投稿が完了しました！")
            break
else:
    if current_hour not in new_hours:
        st.write("😴 現在は自動投稿の**待機時間**です。")
    if posts_today >= new_max:
        st.write("🚫 本日の上限数に達したため、自動投稿を停止しています。")
