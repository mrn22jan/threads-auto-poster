import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 設定 (Secrets) ---
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
SETTINGS_FILE = "bot_settings.json"

# --- 認証 ---
@st.cache_resource
def get_gspread_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

client = get_gspread_client()
sheet = client.open_by_key(SHEET_ID).sheet1

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        if "id" not in res_data: return False, res_data
        container_id = res_data["id"]
        
        # Threads側の反映を待つ
        time.sleep(20)
        
        publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN}, timeout=60)
        return ("id" in res_pub.json()), res_pub.json().get("id")
    except Exception as e:
        return False, str(e)

# --- UI設定 ---
st.set_page_config(page_title="ロクレンジャー投稿システム", layout="wide")
st.title("💸チャリンチャリンシステム")

# 設定読み込み
if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "r") as f: current_settings = json.load(f)
else:
    current_settings = {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

st.sidebar.header("⚙️ 設定")
new_hours = st.sidebar.multiselect("投稿許可時間", options=list(range(24)), default=current_settings["allowed_hours"])
new_max = st.sidebar.number_input("1日の最大投稿数", 1, 24, current_settings["max_posts"])
if st.sidebar.button("設定を保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_hours, "max_posts": new_max}, f)
    st.sidebar.success("保存しました")

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
    # 履歴
    if len(row) > 6 and row[6] and today_str in row[6]:
        try:
            p_time = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if row[5]:
                today_posts.append({"時間": row[6].split(" ")[1], "本文1": row[0][:30], "状態": row[5]})
            if last_post_time is None or p_time > last_post_time:
                last_post_time = p_time
        except: pass
    # 予定
    status = row[5] if len(row) > 5 else ""
    if row[0] and not status:
        idx = len(today_posts) + len(future_schedule)
        if idx < len(allowed_hours) and idx < new_max:
            h = allowed_hours[idx]
            m = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
            future_schedule.append({"row": i, "time": jst_now.replace(hour=h, minute=m, second=0), "data": row})

st.metric("今日の投稿数", f"{len(today_posts)} / {new_max}")

# 間隔チェック
can_post = True
if last_post_time and (jst_now - last_post_time).total_seconds() < 3600:
    can_post = False

# --- 投稿実行 ---
if future_schedule:
    task = future_schedule[0]
    if jst_now >= task["time"] and can_post and len(today_posts) < new_max:
        st.warning(f"🚀 {task['time'].strftime('%H:%M')} の投稿を開始します...")
        r_idx = task["row"]
        
        # 記録開始
        sheet.update_cell(r_idx, 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
        sheet.update_cell(r_idx, 6, "1本目送信中")
        
        texts = [t for t in task["data"][0:5] if t.strip()]
        last_id = None
        count = 0
        
        for idx, txt in enumerate(texts):
            if idx > 0:
                p_hold = st.empty()
                for t in range(300, 0, -1):
                    p_hold.info(f"⏳ ツリー連結待機中... あと {t//60}分{t%60}秒 ({idx}/{len(texts)-1})")
                    time.sleep(1)
                p_hold.empty()
            
            ok, res = post_to_threads(txt, last_id)
            if ok:
                last_id = res
                count += 1
                sheet.update_cell(r_idx, 6, f"{count}本完了")
            else:
                sheet.update_cell(r_idx, 6, f"エラー:{str(res)[:10]}")
                break
        
        if count == len(texts):
            sheet.update_cell(r_idx, 6, "完了")
            st.success("✅ すべてのツリーが正常に投稿されました！")
            st.balloons()
            time.sleep(5)
            st.rerun()
    elif not is_time if 'is_time' in locals() else jst_now < task["time"]:
        st.write(f"📅 次の予定: **{task['time'].strftime('%H:%M')}**")
    elif not can_post:
        st.info("⏳ 1時間の間隔を空けるために待機しています")

st.divider()

# --- 履歴と予定の表示 (修正版) ---
tab1, tab2 = st.tabs(["📋 本日の履歴", "📅 本日の予定"])
with tab1:
    if today_posts:
        st.table(today_posts)
    else:
        st.write("本日の履歴はありません。")

with tab2:
    if future_schedule:
        disp_sch = [{"予定時間": t["time"].strftime("%H:%M"), "本文1": t["data"][0][:40]} for t in future_schedule]
        st.table(disp_sch)
    else:
        st.write("本日の予定はありません。")
