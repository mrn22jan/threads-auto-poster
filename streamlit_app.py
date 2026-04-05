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
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        cid = res.json().get("id")
        if not cid: return False, res.json()
        time.sleep(30)
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(publish_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        return ("id" in res_pub.json()), res_pub.json().get("id")
    except Exception as e:
        return False, str(e)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

# --- UI設定 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("💸 24時間完全自動・放置システム")

conf = load_settings()
st.sidebar.header("⚙️ システム設定")
new_h = st.sidebar.multiselect("投稿許可時間 (時)", list(range(24)), default=conf["allowed_hours"])
new_m = st.sidebar.number_input("1日の最大投稿数", 1, 24, conf["max_posts"])
if st.sidebar.button("設定を保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.sidebar.success("設定を保存しました")
    st.rerun()

# --- データ解析 ---
jst_now = get_jst_now()
today_str = jst_now.strftime("%Y-%m-%d")
all_data = sheet.get_all_values()
rows = all_data[1:]

history, schedule, last_t = [], [], None
allowed = sorted(new_h)

for i, r in enumerate(rows, start=2):
    # 履歴
    if len(r) > 6 and r[6] and today_str in r[6]:
        try:
            pt = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if r[5]: history.append({"時間": r[6].split(" ")[1], "本文1": r[0][:30], "状態": r[5]})
            if not last_t or pt > last_t: last_t = pt
        except: pass
    # 予定
    status = r[5] if len(r) > 5 else ""
    if r[0] and not status:
        idx = len(history) + len(schedule)
        if idx < len(allowed) and idx < new_m:
            h = allowed[idx]
            m = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
            schedule.append({"row": i, "time": jst_now.replace(hour=h, minute=m, second=0), "data": r})

st.metric("今日の投稿数", f"{len(history)} / {new_m}")
can_post = not (last_t and (jst_now - last_t).total_seconds() < 3600)

# --- 投稿実行ロジック ---
if schedule:
    task = schedule[0]
    if jst_now >= task["time"] and can_post:
        st.warning(f"🚀 自動プロセス起動：投稿を開始します...")
        sheet.update_cell(task["row"], 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
        sheet.update_cell(task["row"], 6, "処理中...")
        
        texts, last_id, count = [t for t in task["data"][0:5] if t.strip()], None, 0
        for idx, txt in enumerate(texts):
            if idx > 0:
                p = st.empty()
                for t in range(300, 0, -1):
                    p.info(f"⏳ 待機中... 残り {t}秒 (バックグラウンド実行中)")
                    time.sleep(1)
                p.empty()
            
            ok, res = post_to_threads(txt, last_id)
            if ok:
                last_id, count = res, count + 1
                sheet.update_cell(task["row"], 6, f"{count}本完了")
            else:
                sheet.update_cell(task["row"], 6, "エラー終了")
                break
        
        if count == len(texts):
            sheet.update_cell(task["row"], 6, "完了")
            st.rerun()
    elif not can_post:
        st.info("⏳ 投稿間隔（60分）の調整中です。")
    else:
        st.write(f"📅 次の予定: **{task['time'].strftime('%H:%M')}**")

st.divider()

# --- 履歴と予定のタブ表示 ---
t1, t2 = st.tabs(["📋 今日の履歴", "📅 これからの予定"])
with t1:
    if history:
        st.table(history)
    else:
        st.write("履歴なし")
with t2:
    if schedule:
        st.table([{"時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:30]} for s in schedule])
    else:
        st.write("予定なし")
