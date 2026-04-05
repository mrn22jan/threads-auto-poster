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
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
SETTINGS_FILE = "bot_settings.json"

# --- 認証（キャッシュを使用して安定化） ---
@st.cache_resource
def get_gspread_client():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google認証エラー: {e}")
        return None

client = get_gspread_client()
if client:
    sheet = client.open_by_key(SHEET_ID).sheet1
else:
    st.stop()

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        if "id" not in res_data: return False, f"コンテナ作成失敗: {res_data}"
        container_id = res_data["id"]
        
        time.sleep(20) # 念のための長め待機
        
        publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN}, timeout=60)
        res_pub_data = res_pub.json()
        return ("id" in res_pub_data), res_pub_data.get("id")
    except Exception as e:
        return False, str(e)

# --- UI ---
st.set_page_config(page_title="チャリンチャリンシステム", layout="wide")
st.title("💸 ロクレンジャー用Threads 自動投稿管理")

# --- 稼働テスト（ここが重要） ---
try:
    # 1行目のJ列（10列目）に最終確認時刻を書き込んでみるテスト
    test_time = get_jst_now().strftime("%H:%M:%S")
    sheet.update_cell(1, 10, f"最終接続:{test_time}")
    st.sidebar.success(f"シート接続OK ({test_time})")
except Exception as e:
    st.error(f"⚠️ スプレッドシートへの書き込み権限がありません！共有設定を確認してください: {e}")

# 設定の読み込み
if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "r") as f: current_settings = json.load(f)
else:
    current_settings = {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

# サイドバー設定
new_hours = st.sidebar.multiselect("投稿許可時間", options=list(range(24)), default=current_settings["allowed_hours"])
new_max = st.sidebar.number_input("1日の最大投稿数", min_value=1, max_value=24, value=current_settings["max_posts"])
if st.sidebar.button("設定保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_hours, "max_posts": new_max}, f)
    st.sidebar.info("保存しました。")

# --- データ解析 ---
jst_now = get_jst_now()
today_str = jst_now.strftime("%Y-%m-%d")
all_data = sheet.get_all_values()
rows = all_data[1:]

today_posts = []
future_schedule = []
last_post_time = None
allowed_hours = sorted(new_hours)

for i, row in enumerate(rows, start=2):
    if len(row) > 6 and row[6] and today_str in row[6]:
        try:
            p_time = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if row[5]: today_posts.append({"時間": row[6].split(" ")[1], "本文1": row[0], "状態": row[5]})
            if last_post_time is None or p_time > last_post_time: last_post_time = p_time
        except: pass
    
    status = row[5] if len(row) > 5 else ""
    if row[0] and not status:
        slot_idx = len(today_posts) + len(future_schedule)
        if slot_idx < len(allowed_hours) and slot_idx < new_max:
            t_hour = allowed_hours[slot_idx]
            t_min = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
            sched_time = jst_now.replace(hour=t_hour, minute=t_min, second=0, microsecond=0)
            future_schedule.append({"row_idx": i, "time": sched_time, "data": row})

st.metric("今日の投稿数", f"{len(today_posts)} / {new_max}")

# 間隔チェック
can_post = True
if last_post_time and (jst_now - last_post_time).total_seconds() < 3600:
    can_post = False

if future_schedule:
    next_task = future_schedule[0]
    if jst_now >= next_task["time"] and can_post and len(today_posts) < new_max:
        st.warning(f"🚀 {next_task['time'].strftime('%H:%M')} の投稿を開始")
        r_idx = next_task["row_idx"]
        r_data = next_task["data"]
        
        # ★ 投稿前に時間を書き込む
        sheet.update_cell(r_idx, 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
        sheet.update_cell(r_idx, 6, "1本目送信中...")
        
        valid_texts = [t for t in r_data[0:5] if t.strip()]
        last_id = None
        success_count = 0
        
        for idx, text in enumerate(valid_texts):
            if idx > 0:
                p_hold = st.empty()
                for t in range(300, 0, -1):
                    p_hold.info(f"⏳ 待機中: あと {t // 60}分 {t % 60}秒")
                    time.sleep(1)
                p_hold.empty()
            
            success, res_id = post_to_threads(text, reply_to_id=last_id)
            if success:
                last_id = res_id
                success_count += 1
                sheet.update_cell(r_idx, 6, f"{success_count}本完了")
            else:
                sheet.update_cell(r_idx, 6, f"エラー:{res_id[:10]}")
                break
        
        if success_count == len(valid_texts):
            sheet.update_cell(r_idx, 6, "完了")
            st.rerun()
    elif not can_post:
        st.info("⏳ 前回の投稿から60分間隔を空けるために待機中です。")
    else:
        st.write(f"⏳ 次の予定: **{next_task['time'].strftime('%H:%M')}**")

st.divider()
st.subheader("📋 履歴と予定")
st.table(today_posts) if today_posts else st.write("本日の履歴なし")
