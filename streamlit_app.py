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

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except: pass
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
        
        # コンテナ作成後、少し待機してから公開
        time.sleep(5) 
        
        publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN})
        res_pub_data = res_pub.json()
        
        if "id" in res_pub_data:
            return True, res_pub_data["id"]
        else:
            return False, res_pub_data
    except Exception as e:
        return False, str(e)

# --- UI設定 ---
st.set_page_config(page_title="Threads Auto Bot", layout="wide")
current_settings = load_settings()

st.sidebar.header("⚙️ 自動投稿ルール")
new_hours = st.sidebar.multiselect("投稿許可時間（時）※日本時間", options=list(range(24)), default=current_settings["allowed_hours"])
new_max = st.sidebar.number_input("1日の最大投稿数", min_value=1, max_value=24, value=current_settings["max_posts"])

if new_hours != current_settings["allowed_hours"] or new_max != current_settings["max_posts"]:
    save_settings({"allowed_hours": new_hours, "max_posts": new_max})
    st.sidebar.success("ルールを更新しました。")

st.title("🤖 Threads 自動投稿管理")

# --- 🧪 テスト投稿エリア ---
with st.expander("🧪 手動テスト投稿"):
    t1 = st.text_area("テスト投稿1")
    t2 = st.text_area("テスト投稿2（5分後に投稿されます）")
    if st.button("テスト実行"):
        s1, r1 = post_to_threads(t1)
        if s1 and t2:
            st.info("1つ目成功。5分待機してからツリーを投稿します...")
            time.sleep(300) # 5分待機
            s2, r2 = post_to_threads(t2, reply_to_id=r1)
            if s2: st.success("ツリーまで完了！")
        elif s1: st.success("投稿完了！")

st.divider()

# --- 🤖 自動投稿 & ログ表示 ---
jst_now = get_jst_now()
st.write(f"⌚️ 現在の日本時間: **{jst_now.strftime('%H:%M:%S')}**")

all_rows = sheet.get_all_values()
header = all_rows[0]
rows = all_rows[1:]
today_str = jst_now.strftime("%Y-%m-%d")

# 今日の投稿データを抽出
today_posts = []
last_post_time = None

for row in rows:
    if len(row) > 6 and today_str in row[6]:
        today_posts.append({
            "時間": row[6].split(" ")[1],
            "本文1": row[0],
            "ツリー内容": f"{row[1]} / {row[2]}" if row[1] else "なし",
            "ステータス": "✅ 完了"
        })
        # 最後に投稿された時間を取得
        p_time = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
        if last_post_time is None or p_time > last_post_time:
            last_post_time = p_time

posts_today_count = len(today_posts)
st.metric("本日の自動投稿済み", f"{posts_today_count} / {new_max}")

# --- 投稿ロジック ---
# 前回の投稿から60分経過しているかチェック
can_post_by_interval = True
if last_post_time:
    diff = (jst_now - last_post_time).total_seconds() / 60
    if diff < 60:
        can_post_by_interval = False
        st.warning(f"⏳ 次の投稿まであと {int(60 - diff)} 分待機が必要です（間隔60分設定）")

if jst_now.hour in new_hours and posts_today_count < new_max and can_post_by_interval:
    for i, row in enumerate(rows, start=2):
        if row[0] and not row[5]: # 未投稿を発見
            st.info(f"🚀 {i}行目の投稿を開始します...")
            last_id = None
            valid_texts = [t for t in [row[0], row[1], row[2], row[3], row[4]] if t.strip()]
            
            for idx, text in enumerate(valid_texts):
                if idx > 0:
                    st.write(f"  ⏳ ツリー投稿のため5分待機中... ({idx}/{len(valid_texts)-1})")
                    time.sleep(300) # ツリー間隔 5分
                
                success, res = post_to_threads(text, reply_to_id=last_id)
                if success:
                    last_id = res
                    st.write(f"  ✅ {idx+1}つ目の投稿成功")
                else:
                    st.error(f"  ❌ 失敗: {res}")
                    break
            else:
                # すべて成功した場合のみスプレッドシート更新
                sheet.update_cell(i, 6, "完了")
                sheet.update_cell(i, 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
                st.success("全てのツリー投稿が完了しました！")
                st.rerun() # 画面を更新してログに反映
            break

# --- 今日のログ表示 ---
st.subheader("📋 本日の投稿履歴")
if today_posts:
    st.table(today_posts)
else:
    st.write("今日の投稿はまだありません。")

st.caption("※インサイト機能はAPIの制限により現在準備中です。")
