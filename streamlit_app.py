import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 1. 固定設定（マリンさん専用：提示済みトークンを入力済み） ---
LINE_CHANNEL_TOKEN = "QYcxrG48yFBSmVTT61RhrrTlv5XRyq/qESM8+/sbNdgkiWV/ikxIme1fzfX8hpTgzRNdWCqU8/v3v5d/0+VMzADXnoiBmQ1eAKBmokAoy02W/9rCWA4ALvGRQULYfuRCv/R/LpnD9H1WatL1lR6JOwdB04t89/1O/w1cDnyilFU="
LINE_USER_ID = "U39ad696b574d048fb0649bf084e51773"

# Secretsから取得する基本設定
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
SETTINGS_FILE = "bot_settings.json"

# --- 2. 認証・通知・通信関数 ---
@st.cache_resource
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

def send_line(msg):
    """LINE Messaging API：1本ごとの詳細実況をマリンさんのスマホへ飛ばす"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": f"【Threads Bot実況】\n{msg}"}]}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        return res.status_code == 200
    except:
        return False

def update_sheet_safe(sheet, row, col, val):
    """Googleシートへの書き込みを3回までリトライ"""
    for i in range(3):
        try:
            sheet.update_cell(row, col, val)
            return True
        except:
            time.sleep(2)
    return False

def post_to_threads(text, reply_to_id=None):
    """Threadsへの投稿（コンテナ作成 → 待機 → 公開 → Permalink取得）"""
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        cid = res.json().get("id")
        if not cid: return False, f"API拒否:{res.json()}", ""
        
        time.sleep(35) # Threads側の生成待機
        
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        pid = res_pub.json().get("id")
        
        if pid:
            # 【新規】正しいリンク（Permalink）をAPIから取得する
            perm_url = f"https://graph.threads.net/v1.0/{pid}?fields=permalink&access_token={ACCESS_TOKEN}"
            perm_res = requests.get(perm_url).json()
            permalink = perm_res.get("permalink", f"https://www.threads.net/t/{pid}")
            return True, pid, permalink
        
        return False, "公開失敗", ""
    except Exception as e:
        return False, str(e), ""

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

# --- 3. UI・初期化 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー完全管理システム")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")

# --- 4. サイドバー設定 ---
conf = load_settings()
st.sidebar.header("⚙️ システム設定")
new_h = st.sidebar.multiselect("投稿許可時間 (時)", list(range(24)), default=conf["allowed_hours"])
new_m = st.sidebar.number_input("1日の最大投稿数", 1, 24, conf["max_posts"])
if st.sidebar.button("設定を永久保存"):
    with open(SETTINGS_FILE, "w") as f: json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.sidebar.success("保存完了")

# LINEテストボタン
if st.sidebar.button("🔔 LINEにテスト送信"):
    if send_line("リンク取得テストを含めた、正常な通知の確認です。"): st.sidebar.success("成功！")

st.sidebar.divider()
st.sidebar.header("🧪 指定行テスト投稿")
test_row_idx = st.sidebar.number_input("何行目をテストする？", min_value=2, step=1, value=2)
if st.sidebar.button("🚀 指定行でテスト実行"):
    try:
        test_data = sheet.row_values(test_row_idx)
        if test_data and test_data[0]:
            texts = [t for t in test_data[0:5] if t.strip()]
            prog = st.empty()
            tid, final_link = None, ""
            for idx, txt in enumerate(texts):
                if idx > 0:
                    for t in range(300, 0, -1):
                        prog.warning(f"⏳ 【テスト】連結待機中 ({idx}/{len(texts)})\nあと **{t}** 秒...")
                        time.sleep(1)
                prog.info(f"📤 {idx+1}本目を投稿中...")
                ok, res_id, link = post_to_threads(txt, tid)
                if ok:
                    tid = res_id
                    if idx == 0: final_link = link
                    update_sheet_safe(sheet, test_row_idx, 6, f"テスト中:{idx+1}本完了")
                    send_line(f"🧪テスト実況: {idx+1}/{len(texts)}本目 成功！\n🔗リンク: {final_link}")
                    st.write(f"✅ {idx+1}本目 成功")
                else:
                    st.error(f"❌ 失敗: {res_id}"); send_line(f"❌失敗: {res_id}"); break
            send_line(f"🎊テスト完遂！\n{final_link}")
    except Exception as e: st.sidebar.error(f"エラー: {e}")

# --- 5. データ解析 ---
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
        schedule.append({"row": t_info['row'], "time": stime, "data": t_info['data'], "status": t_info['status']})

# --- 6. 自動投稿実行（リンク取得強化版） ---
st.metric("今日の状況", f"{len(history)} / {new_m} 完了")

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
        current_link = task["data"][9] if len(task["data"]) > 9 else "" # I列(10番目)にリンク保存
        
        if is_resuming:
            start_idx = int(task["status"].replace("本完了", ""))
            current_tid = task["data"][7] if len(task["data"]) > 7 else None
            send_line(f"🔄 再開: {start_idx+1}本目から(行:{task['row']})")
        else:
            send_line(f"🎬 開始: 全{len(texts)}本(行:{task['row']})")

        for idx in range(start_idx, len(texts)):
            if idx > 0:
                # 最終更新からの待機時間を計算
                try:
                    l_val = sheet.cell(task['row'], 7).value
                    l_time = datetime.strptime(l_val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
                    elap = (datetime.now(timezone(timedelta(hours=9))) - l_time).total_seconds()
                except: elap = 0
                rem = int(300 - elap)
                if rem > 0:
                    for t in range(rem, 0, -1):
                        status_area.warning(f"🕒 ツリー待機中 ({idx}/{len(texts)}本目完了) あと **{t}** 秒...")
                        time.sleep(1)
            
            status_area.info(f"📤 {idx+1}本目を投稿中...")
            ok, res_id, permalink = post_to_threads(texts[idx], current_tid)
            
            if ok:
                current_tid = res_id
                if idx == 0: current_link = permalink
                
                # スプレッドシート更新
                update_sheet_safe(sheet, task["row"], 6, f"{idx+1}本完了")
                update_sheet_safe(sheet, task["row"], 7, datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S"))
                update_sheet_safe(sheet, task["row"], 8, current_tid) # H列
                update_sheet_safe(sheet, task["row"], 10, current_link) # J列(10番目)に正式URL保存
                
                send_line(f"📈 実況: {idx+1}/{len(texts)}本目 成功\n🔗URL: {current_link}")
                st.write(f"✅ {idx+1}本目 完了")
            else:
                update_sheet_safe(sheet, task["row"], 6, f"エラー:{res_id[:10]}")
                send_line(f"⚠️ エラー: {res_id}"); break
        else:
            update_sheet_safe(sheet, task["row"], 6, "完了")
            send_line(f"🎉 完遂しました！\n{current_link}")
            st.rerun()
    elif time_gap < 3600 and not is_resuming:
        st.info(f"⏳ 60分ルール待機中（あと {int((3600-time_gap)/60)} 分）")
    else:
        st.info(f"📅 次回: **{task['time'].strftime('%H:%M')}**")

st.divider()
t1, t2 = st.tabs(["📋 今日の履歴", "📅 これからの予定"])
with t1: st.table([{"時間": r[6].split(" ")[1] if len(r)>6 else "-", "内容": r[0][:20], "状態": r[5]} for r in history])
with t2: st.table([{"行": s["row"], "時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:20]} for s in schedule if s["time"] > jst_now])
