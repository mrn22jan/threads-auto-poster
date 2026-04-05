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

@st.cache_resource
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        if "id" not in res_data: return False, f"API拒否:{res_data.get('error', {}).get('message', '不明')}"
        
        cid = res_data["id"]
        time.sleep(45) # Threads側の処理を長めに待つ
        
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        pub_data = res_pub.json()
        
        if "id" in pub_data: return True, pub_data["id"]
        return False, f"公開失敗:{pub_data.get('error', {}).get('message', '不明')}"
    except Exception as e:
        return False, f"通信エラー:{str(e)[:20]}"

st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("💸 粘り強い自動投稿システム")

# 起動直後のスリープ防止（外部アクセス用）
st.write(f"最終チェック: {datetime.now(timezone(timedelta(hours=9))).strftime('%H:%M:%S')}")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1

# --- 設定読み込み ---
if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "r") as f: conf = json.load(f)
else:
    conf = {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

st.sidebar.header("⚙️ 設定")
new_h = st.sidebar.multiselect("投稿時間", list(range(24)), default=conf["allowed_hours"])
new_m = st.sidebar.number_input("最大投稿数", 1, 24, conf["max_posts"])
if st.sidebar.button("設定保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.rerun()

# --- 解析 ---
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")
all_data = sheet.get_all_values()
rows = all_data[1:]

history, schedule, last_t = [], [], None
allowed = sorted(new_h)

for i, r in enumerate(rows, start=2):
    if len(r) > 6 and r[6] and today_str in r[6]:
        try:
            pt = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if r[5] and "エラー" not in r[5]: history.append(r)
            if not last_t or pt > last_t: last_t = pt
        except: pass
    
    status = r[5] if len(r) > 5 else ""
    if r[0] and not status:
        idx = len(history) + len(schedule)
        if idx < len(allowed) and idx < new_m:
            h = allowed[idx]
            m = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
            schedule.append({"row": i, "time": jst_now.replace(hour=h, minute=m, second=0, microsecond=0), "data": r})

st.metric("今日の投稿数", f"{len(history)} / {new_m}")
can_post = not (last_t and (jst_now - last_t).total_seconds() < 3000) # 間隔を少し短縮(50分)

if schedule:
    task = schedule[0]
    if jst_now >= task["time"] and can_post:
        st.warning(f"🚀 {task['time'].strftime('%H:%M')} の投稿を開始")
        # Googleシートへの書き込み失敗対策でリトライを入れる
        try:
            sheet.update_cell(task["row"], 7, jst_now.strftime("%Y-%m-%d %H:%M:%S"))
            sheet.update_cell(task["row"], 6, "1本目送信中")
        except:
            time.sleep(5)
            sheet.update_cell(task["row"], 6, "再試行中")

        texts = [t for t in task["data"][0:5] if t.strip()]
        last_id, count = None, 0
        
        for idx, txt in enumerate(texts):
            if idx > 0:
                p = st.empty()
                for t in range(300, 0, -10):
                    p.info(f"⏳ 連結待機中... 残り {t}秒")
                    time.sleep(10)
                p.empty()
            
            ok, res = post_to_threads(txt, last_id)
            if ok:
                last_id, count = res, count + 1
                sheet.update_cell(task["row"], 6, f"{count}本完了")
            else:
                sheet.update_cell(task["row"], 6, f"エラー:{str(res)[:15]}")
                break
        
        if count == len(texts):
            sheet.update_cell(task["row"], 6, "完了")
            st.rerun()
    elif not can_post: st.info("⏳ 連続投稿防止のため待機中")
    else: st.write(f"📅 次回予定: **{task['time'].strftime('%H:%M')}**")

st.divider()
t1, t2 = st.tabs(["📋 履歴", "📅 予定"])
with t1:
    if history: st.table([{"時間": r[6].split(" ")[1], "内容": r[0][:20], "状態": r[5]} for r in history])
with t2:
    if schedule: st.table([{"時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:20]} for s in schedule])
