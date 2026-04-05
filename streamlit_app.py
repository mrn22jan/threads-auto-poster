import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 設定 ---
SETTINGS_FILE = "bot_settings.json"
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]

# --- 認証 ---
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f: json.dump(settings, f)

def get_random_minute(row_idx, date_str):
    """行番号と日付に基づいて、その行専用のランダムな『分』(0-59)を生成する"""
    seed = f"{date_str}_{row_idx}"
    return int(hashlib.md5(seed.encode()).hexdigest(), 16) % 60

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    res = requests.post(base_url, data=payload)
    res_data = res.json()
    if "id" not in res_data: return False, res_data
    container_id = res_data["id"]
    time.sleep(10)
    
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN})
    res_pub_data = res_pub.json()
    return ("id" in res_pub_data), res_pub_data.get("id")

# --- UI設定 ---
st.set_page_config(page_title="チャリンチャリンシステム", layout="wide")
current_settings = load_settings()

st.sidebar.header("⚙️ システム設定")
new_hours = st.sidebar.multiselect("投稿許可時間（時）", options=sorted(list(range(24))), default=current_settings["allowed_hours"])
new_max = st.sidebar.number_input("1日の最大投稿数", min_value=1, max_value=24, value=current_settings["max_posts"])

if new_hours != current_settings["allowed_hours"] or new_max != current_settings["max_posts"]:
    save_settings({"allowed_hours": new_hours, "max_posts": new_max})
    st.sidebar.success("設定を更新しました")

st.title("💸チャリンチャリンシステム")

# --- データ取得 & スケジュール構築 ---
jst_now = get_jst_now()
today_str = jst_now.strftime("%Y-%m-%d")
all_data = sheet.get_all_values()
rows = all_data[1:]

today_posts = []
future_schedule = []
last_post_time = None

# 本日の許可時間リスト
allowed_hours = sorted(new_hours)

# 1. 履歴の確認
for row in rows:
    if len(row) > 6 and row[6] and today_str in row[6]:
        try:
            p_time = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if row[5] == "完了":
                today_posts.append({"時間": row[6].split(" ")[1], "本文1": row[0]})
            if last_post_time is None or p_time > last_post_time:
                last_post_time = p_time
        except: pass

# 2. 本日の予定表を作成
posts_done_count = len(today_posts)
future_rows = [i for i, r in enumerate(rows, start=2) if r[0] and (len(r) <= 5 or not r[5])]

for idx, row_idx in enumerate(future_rows):
    # 最大投稿数を超えない範囲で予定を組む
    slot_idx = posts_done_count + idx
    if slot_idx < len(allowed_hours) and slot_idx < new_max:
        target_hour = allowed_hours[slot_idx]
        target_minute = get_random_minute(row_idx, today_str)
        scheduled_time = jst_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        
        future_schedule.append({
            "row_idx": row_idx,
            "scheduled_time": scheduled_time,
            "content": rows[row_idx-2][0],
            "row_data": rows[row_idx-2]
        })

# --- 表示 ---
st.metric("今日の投稿数", f"{len(today_posts)} / {new_max}")

# --- 自動投稿ロジック ---
# 60分間隔ルール
can_post_by_interval = True
if last_post_time:
    if (jst_now - last_post_time).total_seconds() < 3600:
        can_post_by_interval = False

if future_schedule:
    next_task = future_schedule[0]
    is_time = jst_now >= next_task["scheduled_time"]
    
    if is_time and can_post_by_interval and len(today_posts) < new_max:
        st.info(f"🚀 予約時刻（{next_task['scheduled_time'].strftime('%H:%M')}）になりました。投稿を開始します...")
        row_idx = next_task["row_idx"]
        row_data = next_task["row_data"]
        
        sheet.update_cell(row_idx, 6, "投稿中...")
        sheet.update_cell(row_idx, 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
        
        valid_texts = [t for t in row_data[0:5] if t.strip()]
        last_id = None
        for idx, text in enumerate(valid_texts):
            if idx > 0:
                placeholder = st.empty()
                for t in range(300, 0, -1):
                    placeholder.warning(f"⏳ ツリー連結中... あと {t // 60}分 {t % 60}秒")
                    time.sleep(1)
                placeholder.empty()
            
            success, res_id = post_to_threads(text, reply_to_id=last_id)
            if success: last_id = res_id
            else: break
        
        sheet.update_cell(row_idx, 6, "完了")
        st.success("✅ 投稿完了されました")
        st.balloons()
        time.sleep(5)
        st.rerun()
    elif not is_time:
        st.write(f"⏳ 次の投稿予定：**{next_task['scheduled_time'].strftime('%H:%M')}**")
    elif not can_post_by_interval:
        st.warning("⚠️ 予約時間ですが、前回の投稿から60分経過するまで待機しています。")

st.divider()

# --- 履歴と予定テーブル ---
tab1, tab2 = st.tabs(["📋 本日の投稿履歴", "📅 本日の予定"])

with tab1:
    if today_posts: st.table(today_posts)
    else: st.write("本日の履歴はありません。")

with tab2:
    if future_schedule:
        display_schedule = []
        for item in future_schedule:
            display_schedule.append({
                "予定時間": item["scheduled_time"].strftime("%m/%d %H:%M"),
                "本文1": item["content"][:40] + "..."
            })
        st.table(display_schedule)
    else:
        st.write("本日の予定はすべて終了したか、ネタがありません。")
