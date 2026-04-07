import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 1. 設定取得 ---
LINE_CHANNEL_TOKEN = st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = st.secrets.get("LINE_USER_ID")
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

def send_line(msg):
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": f"【Threads Bot】\n{msg}"}]}
    try: requests.post(url, headers=headers, json=payload, timeout=10)
    except: pass

def update_sheet_safe(sheet, row, col, val):
    for i in range(3):
        try:
            sheet.update_cell(row, col, val)
            return True
        except:
            time.sleep(2)
    return False

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        cid = res_data.get("id")
        if not cid: return False, f"API拒否:{res_data.get('error',{}).get('message','不明')}"
        time.sleep(35) # Threadsメディア生成待ち
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        pub_res = res_pub.json()
        if "id" in pub_res: return True, pub_res["id"]
        return False, "公開失敗"
    except Exception as e: return False, str(e)[:20]

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try: with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

# --- 2. メインUI ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー管理システム [完遂型]")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")

conf = load_settings()
st.sidebar.header("⚙️ システム設定")
new_h = st.sidebar.multiselect("投稿許可時間", list(range(24)), default=conf["allowed_hours"])
new_m = st.sidebar.number_input("1日の最大数", 1, 24, conf["max_posts"])
if st.sidebar.button("設定保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.sidebar.success("保存完了")

# LINEテストボタン
if st.sidebar.button("🔔 LINE疎通テスト"):
    if send_line("テスト通知です！届いたら成功です。"): st.sidebar.success("送信成功")
    else: st.sidebar.error("失敗")

# --- 3. データ解析 ---
all_rows = sheet.get_all_values()
data_rows = all_rows[1:]
history, last_t = [], None
available_data = []

# 現在のステータスと最終更新時刻を把握する
for i, r in enumerate(data_rows, start=2):
    status = r[5] if len(r) > 5 else ""
    last_update_str = r[6] if len(r) > 6 else ""
    
    if today_str in last_update_str and "完了" in status:
        history.append(r)
        try:
            pt = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if not last_t or pt > last_t: last_t = pt
        except: pass
    elif r[0] and "完了" not in status:
        available_data.append({"row": i, "data": r, "status": status})

allowed_slots = sorted(new_h)[:new_m]
schedule = []
used_count = len(history)
for i, t_info in enumerate(available_data):
    idx = used_count + i
    if idx < len(allowed_slots):
        h = allowed_slots[idx]
        m = int(hashlib.md5(f"{today_str}_{t_info['row']}".encode()).hexdigest(), 16) % 60
        schedule.append({"row": t_info['row'], "time": jst_now.replace(hour=h, minute=m, second=0, microsecond=0), "data": t_info['data'], "status": t_info['status']})

# --- 4. 投稿実行ロジック（強化版） ---
st.metric("今日の進捗", f"{len(history)} / {new_m}")

if schedule:
    task = schedule[0]
    time_gap = (jst_now - last_t).total_seconds() if last_t else 9999
    is_resuming = "本完了" in task["status"]
    
    # 投稿開始条件（時間になった、かつ 60分経過 または 再開中）
    if jst_now >= task["time"] and (time_gap >= 3600 or is_resuming):
        st.subheader("🚀 投稿プロセス実行中")
        status_area = st.empty()
        
        texts = [t for t in task["data"][0:5] if t.strip()]
        start_idx = 0
        current_tid = None
        first_id = task["data"][8] if len(task["data"]) > 8 else None
        
        if is_resuming:
            start_idx = int(task["status"].replace("本完了", ""))
            current_tid = task["data"][7] if len(task["data"]) > 7 else None
        
        # 1本目開始時
        if start_idx == 0:
            update_sheet_safe(sheet, task["row"], 7, jst_now.strftime("%Y-%m-%d %H:%M:%S"))
            send_line(f"⏳ 投稿開始(行:{task['row']})")

        for idx in range(start_idx, len(texts)):
            # 2本目以降の5分待機
            if idx > 0:
                # 最後にシートを更新した時刻を基準に待機
                try:
                    last_post_time = datetime.strptime(sheet.cell(task['row'], 7).value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
                    elapsed = (datetime.now(timezone(timedelta(hours=9))) - last_post_time).total_seconds()
                except: elapsed = 0
                
                remaining = int(300 - elapsed)
                if remaining > 0:
                    for t in range(remaining, 0, -1):
                        status_area.warning(f"🕒 ツリー連結待機中 ({idx}/{len(texts)}本目完了)\nあと **{t}** 秒で次を投稿します...")
                        time.sleep(1)
            
            # 投稿実行
            status_area.info(f"📤 {idx+1}本目を投稿中...")
            ok, res_id = post_to_threads(texts[idx], current_tid)
            
            if ok:
                current_tid = res_id
                if idx == 0: first_id = res_id
                # スプレッドシート更新（ここが最優先）
                update_sheet_safe(sheet, task["row"], 6, f"{idx+1}本完了")
                update_sheet_safe(sheet, task["row"], 7, datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S"))
                update_sheet_safe(sheet, task["row"], 8, current_tid)
                update_sheet_safe(sheet, task["row"], 9, first_id)
                
                send_line(f"📈 {idx+1}/{len(texts)}本目 成功\nリンク: https://www.threads.net/t/{first_id}")
                st.write(f"✅ {idx+1}本目 完了")
            else:
                update_sheet_safe(sheet, task["row"], 6, f"エラー:{str(res_id)[:15]}")
                send_line(f"⚠️ エラー発生 行:{task['row']} {res_id}"); break
        else:
            update_sheet_safe(sheet, task["row"], 6, "完了")
            send_line(f"🎉 完遂！\nhttps://www.threads.net/t/{first_id}")
            st.rerun()
    elif time_gap < 3600 and not is_resuming:
        st.info(f"⏳ 60分間隔ルール待機中（あと {int((3600-time_gap)/60)} 分）")
    else:
        st.info(f"📅 次回: **{task['time'].strftime('%H:%M')}** ({task['row']}行目)")

st.divider()
t1, t2 = st.tabs(["📋 履歴", "📅 予定"])
with t1: st.table([{"時間": r[6].split(" ")[1] if len(r)>6 else "-", "内容": r[0][:20], "状態": r[5]} for r in history])
with t2: st.table([{"行": s["row"], "時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:20], "状態": s["status"]} for s in schedule if s["time"] > jst_now])
