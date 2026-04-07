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
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": f"【Threads Bot実況】\n{msg}"}]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        return res.status_code == 200
    except:
        return False

def update_sheet_safe(sheet, row, col, val):
    """Googleシートへの書き込みを3回まで粘り強くリトライする"""
    for i in range(3):
        try:
            sheet.update_cell(row, col, val)
            return True
        except:
            time.sleep(2)
    return False

def post_to_threads(text, reply_to_id=None):
    """Threadsへの投稿（コンテナ作成 → 35秒待機 → 公開）"""
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    
    try:
        # コンテナ作成
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        cid = res_data.get("id")
        if not cid:
            return False, f"API拒否:{res_data.get('error',{}).get('message','不明')}"
        
        # Threads側のメディア処理待ち（35秒）
        time.sleep(35)
        
        # 公開
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        pub_res = res_pub.json()
        if "id" in pub_res:
            return True, pub_res["id"]
        return False, f"公開失敗:{pub_res.get('error',{}).get('message','不明')}"
    except Exception as e:
        return False, f"通信エラー:{str(e)[:20]}"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

# --- 3. UI・初期化 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー完全管理システム [究極マスター版]")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")

# --- 4. サイドバー：設定・テスト・通知確認 ---
conf = load_settings()
st.sidebar.header("⚙️ システム設定")
new_h = st.sidebar.multiselect("投稿許可時間 (時)", list(range(24)), default=conf["allowed_hours"])
new_m = st.sidebar.number_input("1日の最大投稿数", 1, 24, conf["max_posts"])
if st.sidebar.button("設定を永久保存"):
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.sidebar.success("設定ファイルを更新しました")

st.sidebar.divider()
st.sidebar.header("🔔 LINE通知テスト")
if st.sidebar.button("今すぐLINEにテスト送信"):
    if send_line("テスト通知です！これが届けばアクセストークン設定は完璧です。"):
        st.sidebar.success("送信成功！")
    else:
        st.sidebar.error("送信失敗。公式アカウントの友だち追加を確認してください。")

st.sidebar.divider()
st.sidebar.header("🧪 指定行テスト投稿")
test_row_idx = st.sidebar.number_input("何行目をテストする？", min_value=2, step=1, value=2)
if st.sidebar.button("🚀 指定行でテスト実行"):
    try:
        test_data = sheet.row_values(test_row_idx)
        if test_data and test_data[0]:
            texts = [t for t in test_data[0:5] if t.strip()]
            prog = st.empty()
            tid, first_url = None, ""
            for idx, txt in enumerate(texts):
                if idx > 0:
                    for t in range(300, 0, -1):
                        prog.warning(f"⏳ 【テスト中】連結待機中 ({idx}/{len(texts)}本完了)\nあと **{t}** 秒で次を投稿します...")
                        time.sleep(1)
                prog.info(f"📤 {idx+1}本目を投稿中...")
                ok, res = post_to_threads(txt, tid)
                if ok:
                    tid = res
                    if idx == 0: first_url = f"https://www.threads.net/t/{res}"
                    update_sheet_safe(sheet, test_row_idx, 6, f"テスト中:{idx+1}本完了")
                    send_line(f"🧪テスト実況: {idx+1}/{len(texts)}本目 成功！\nリンク(1本目): {first_url}")
                    st.write(f"✅ {idx+1}本目 成功")
                else:
                    st.error(f"❌ 失敗: {res}")
                    send_line(f"❌テスト失敗: {res}")
                    break
            else:
                update_sheet_safe(sheet, test_row_idx, 6, "テスト完了")
                send_line(f"🎊テスト完遂しました！\n{first_url}")
                st.balloons()
    except Exception as e: st.sidebar.error(f"エラー: {e}")

# --- 5. データ解析（全枠埋め・リアルタイム反映） ---
all_rows = sheet.get_all_values()
data_rows = all_rows[1:]
history, last_t = [], None
available_data = []

for i, r in enumerate(data_rows, start=2):
    status = r[5] if len(r) > 5 else ""
    # 今日の「完了」履歴
    if len(r) > 6 and r[6] and today_str in r[6] and "完了" in status:
        history.append(r)
        try:
            pt = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if not last_t or pt > last_t: last_t = pt
        except: pass
    # 未投稿、または再開待ちデータ
    elif r[0] and "完了" not in status:
        available_data.append({"row": i, "data": r, "status": status})

# サイドバーの最新設定をリアルタイム適用
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

# --- 6. 自動投稿実行（60分・5分・再開・リンク実況） ---
st.metric("今日の完了状況", f"{len(history)} / {new_m} 枠")

if schedule:
    task = schedule[0]
    # 60分ルール：前のスレッド開始から3600秒経過しているか
    time_gap = (jst_now - last_t).total_seconds() if last_t else 9999
    is_resuming = "本完了" in task["status"]
    
    if jst_now >= task["time"] and (time_gap >= 3600 or is_resuming):
        st.subheader("🚀 投稿プロセス実行中")
        status_area = st.empty()
        texts = [t for t in task["data"][0:5] if t.strip()]
        
        start_idx = 0
        current_tid = None
        first_id = task["data"][8] if len(task["data"]) > 8 else None
        
        # 再開（レジューム）処理
        if is_resuming:
            start_idx = int(task["status"].replace("本完了", ""))
            current_tid = task["data"][7] if len(task["data"]) > 7 else None
            send_line(f"🔄 再開します: {start_idx + 1}本目から投稿(行:{task['row']})")
        else:
            send_line(f"🎬 投稿開始: 全{len(texts)}本のツリー予定(行:{task['row']})")

        for idx in range(start_idx, len(texts)):
            if idx > 0:
                # ツリー内の5分待機（前回の更新時刻から計算）
                try:
                    l_time = datetime.strptime(sheet.cell(task['row'], 7).value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
                    elap = (datetime.now(timezone(timedelta(hours=9))) - l_time).total_seconds()
                except: elap = 0
                rem = int(300 - elap)
                if rem > 0:
                    for t in range(rem, 0, -1):
                        status_area.warning(f"🕒 ツリー連結待機中 ({idx}/{len(texts)}本完了)\nあと **{t}** 秒...")
                        time.sleep(1)
            
            status_area.info(f"📤 {idx+1}本目を投稿中...")
            ok, res_id = post_to_threads(texts[idx], current_tid)
            
            if ok:
                current_tid = res_id
                if idx == 0: first_id = res_id
                
                # スプレッドシートを即時更新（確実性を高めるリトライ付き）
                update_sheet_safe(sheet, task["row"], 6, f"{idx+1}本完了")
                update_sheet_safe(sheet, task["row"], 7, datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S"))
                update_sheet_safe(sheet, task["row"], 8, current_tid)
                update_sheet_safe(sheet, task["row"], 9, first_id)
                
                # 1本ごとにLINEで実況
                post_url = f"https://www.threads.net/t/{first_id}"
                send_line(f"📈 実況: {idx+1}/{len(texts)}本目 成功！\n内容: {texts[idx][:15]}...\nリンク: {post_url}")
                st.write(f"✅ {idx+1}本目 完了")
            else:
                err = str(res_id)[:20]
                update_sheet_safe(sheet, task["row"], 6, f"エラー:{err}")
                send_line(f"⚠️ エラー発生 行:{task['row']} 内容:{err}"); break
        else:
            update_sheet_safe(sheet, task["row"], 6, "完了")
            send_line(f"🎉 ツリー完遂しました！\nhttps://www.threads.net/t/{first_id}")
            st.rerun()
    elif time_gap < 3600 and not is_resuming:
        st.info(f"⏳ 60分間隔ルール待機中（あと {int((3600-time_gap)/60)} 分）")
    else:
        # 未来の予定を表示
        display_schedule = [s for s in schedule if s["time"] > jst_now]
        if display_schedule:
            st.info(f"📅 次回予定: **{display_schedule[0]['time'].strftime('%H:%M')}** ({display_schedule[0]['row']}行目)")
        else:
            st.warning("🌙 今日の予定枠はすべて終了しました。")

st.divider()
t1, t2 = st.tabs(["📋 今日の履歴", "📅 これからの予定"])
with t1: st.table([{"時間": r[6].split(" ")[1] if len(r)>6 else "-", "内容": r[0][:20], "状態": r[5]} for r in history])
with t2:
    display_sched = [{"行": s["row"], "時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:20], "状態": s["status"] if s["status"] else "予約中"} for s in schedule if s["time"] > jst_now]
    st.table(display_sched if display_sched else [{"予定": "なし"}])
