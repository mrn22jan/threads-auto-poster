import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 1. 定数・シークレット ---
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
LINE_CHANNEL_TOKEN = st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = st.secrets.get("LINE_USER_ID")
SETTINGS_FILE = "bot_settings.json"

# --- 2. 認証・通知・API関数 ---
@st.cache_resource
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

def send_line(msg):
    """LINE Messaging APIによる詳細通知"""
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": f"【Threads Bot通信】\n{msg}"}]}
    try: requests.post(url, headers=headers, json=payload, timeout=10)
    except: pass

def post_to_threads(text, reply_to_id=None):
    """Threadsへの投稿プロセス"""
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        cid = res_data.get("id")
        if not cid: return False, f"API拒否:{res_data.get('error',{}).get('message','不明')}"
        
        time.sleep(35) # メディアコンテナ処理待ち
        
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        pub_res = res_pub.json()
        if "id" in pub_res: return True, pub_res["id"]
        return False, f"公開失敗:{pub_res.get('error',{}).get('message','不明')}"
    except Exception as e:
        return False, f"通信エラー:{str(e)[:20]}"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

# --- 3. UI構成 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー完全管理システム [究極マスター版]")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")

# --- 4. サイドバー：設定（本数・時間・行指定テスト） ---
conf = load_settings()
st.sidebar.header("⚙️ システム設定")
new_h = st.sidebar.multiselect("投稿許可時間 (時)", list(range(24)), default=conf["allowed_hours"])
new_m = st.sidebar.number_input("1日の最大投稿数", 1, 24, conf["max_posts"])
if st.sidebar.button("設定を保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.sidebar.success("保存しました")
    st.rerun()

st.sidebar.divider()
st.sidebar.header("🧪 行指定テスト投稿")
test_row_idx = st.sidebar.number_input("何行目をテストする？", min_value=2, step=1, value=2)
if st.sidebar.button("🚀 テスト実行"):
    test_data = sheet.row_values(test_row_idx)
    if test_data and test_data[0]:
        texts = [t for t in test_data[0:5] if t.strip()]
        prog = st.empty()
        tid = None
        first_post_url = ""
        for idx, txt in enumerate(texts):
            if idx > 0:
                for t in range(300, 0, -1):
                    prog.warning(f"⏳ 【テスト】連結待機中 ({idx}/{len(texts)})\nあと **{t}** 秒...")
                    time.sleep(1)
            ok, res = post_to_threads(txt, tid)
            if ok:
                tid = res
                if idx == 0: first_post_url = f"https://www.threads.net/t/{res}"
                st.write(f"✅ {idx+1}本目 成功")
                send_line(f"🧪テスト中: {idx+1}/{len(texts)}本目 成功！")
            else:
                st.error(f"失敗: {res}"); send_line(f"❌テスト失敗: {res}"); break
        send_line(f"🎊テスト完了！\nツリー全体を確認:\n{first_post_url}")

# --- 5. データ解析（全枠埋め・JST・ランダム分） ---
all_rows = sheet.get_all_values()
data_rows = all_rows[1:]
history, last_t = [], None
available_data = []

for i, r in enumerate(data_rows, start=2):
    status = r[5] if len(r) > 5 else ""
    if len(r) > 6 and r[6] and today_str in r[6] and "完了" in status:
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
        stime = jst_now.replace(hour=h, minute=m, second=0, microsecond=0)
        schedule.append({"row": t_info["row"], "time": stime, "data": t_info["data"], "status": t_info["status"]})

# --- 6. 実行処理（60分・5分・カウントダウン・詳細LINE） ---
st.metric("今日の進捗", f"{len(history)} / {new_m} 完了")

if schedule:
    task = schedule[0]
    time_gap = (jst_now - last_t).total_seconds() if last_t else 9999
    is_resuming = "本完了" in task["status"]
    
    if jst_now >= task["time"] and (time_gap >= 3600 or is_resuming):
        st.subheader("🚀 投稿プロセス実行中")
        status_area = st.empty()
        texts = [t for t in task["data"][0:5] if t.strip()]
        start_idx = 0
        current_tid = None
        first_id = task["data"][8] if len(task["data"]) > 8 else None # I列に1本目ID(リンク用)
        
        if is_resuming:
            start_idx = int(task["status"].replace("本完了", ""))
            current_tid = task["data"][7] if len(task["data"]) > 7 else None # H列
        
        if start_idx == 0:
            sheet.update_cell(task["row"], 7, jst_now.strftime("%Y-%m-%d %H:%M:%S"))
            send_line(f"⏳ 投稿を開始します\n行: {task['row']}\n全 {len(texts)} 本のツリー予定")

        for idx in range(start_idx, len(texts)):
            if idx > 0:
                for t in range(300, 0, -1):
                    status_area.warning(f"🕒 ツリー待機中 ({idx}/{len(texts)}本完了)\nあと **{t}** 秒")
                    time.sleep(1)
            
            ok, res_id = post_to_threads(texts[idx], current_tid)
            if ok:
                current_tid = res_id
                if idx == 0: first_id = res_id # 初回ID保持
                sheet.update_cell(task["row"], 6, f"{idx+1}本完了")
                sheet.update_cell(task["row"], 8, current_tid) # H列: 直近ID
                sheet.update_cell(task["row"], 9, first_id)   # I列: 起点ID
                st.write(f"✅ {idx+1}本目 完了")
                send_line(f"📈 進捗: {idx+1}/{len(texts)}本目 成功\n内容: {texts[idx][:20]}...")
            else:
                err = str(res_id)[:20]
                sheet.update_cell(task["row"], 6, f"エラー:{err}")
                send_line(f"⚠️ エラー発生\n行: {task['row']}\n理由: {err}"); break
        else:
            sheet.update_cell(task["row"], 6, "完了")
            link = f"https://www.threads.net/t/{first_id}"
            send_line(f"🎉 ツリー完遂！\n行: {task['row']}\n全{len(texts)}本を無事に投稿しました。\n\n👇投稿を確認する\n{link}")
            st.rerun()
    elif time_gap < 3600 and not is_resuming:
        st.info(f"⏳ 60分間隔ルール適用中（あと {int((3600-time_gap)/60)} 分）")
    else:
        st.info(f"📅 次回: **{task['time'].strftime('%H:%M')}** ({task['row']}行目)")

st.divider()
t1, t2 = st.tabs(["📋 履歴", "📅 予定"])
with t1: st.table([{"時間": r[6].split(" ")[1] if len(r)>6 else "-", "内容": r[0][:20], "状態": r[5]} for r in history])
with t2: st.table([{"行": s["row"], "時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:20], "状態": s["status"]} for s in schedule])
