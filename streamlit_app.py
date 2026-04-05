import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 1. 設定・シークレット取得 ---
# LINE設定がSecretsのトップレベルにあることを想定
LINE_CHANNEL_TOKEN = st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = st.secrets.get("LINE_USER_ID")
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
SETTINGS_FILE = "bot_settings.json"

# --- 2. 認証・共通関数 ---
@st.cache_resource
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

def send_line(msg):
    """2026年仕様：LINE Messaging APIによる実況通知"""
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID:
        return False
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"}
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": f"【Threads Bot】\n{msg}"}]}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        return res.status_code == 200
    except:
        return False

def update_sheet_safe(sheet, row, col, val):
    """Googleシートへの書き込みを3回までリトライして確実に行う"""
    for i in range(3):
        try:
            sheet.update_cell(row, col, val)
            return True
        except:
            time.sleep(2)
    return False

def post_to_threads(text, reply_to_id=None):
    """Threadsへの投稿と公開。35秒のメディア処理待機を含む"""
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    try:
        res = requests.post(base_url, data=payload, timeout=60)
        res_data = res.json()
        cid = res_data.get("id")
        if not cid: return False, f"API拒否:{res_data.get('error',{}).get('message','不明')}"
        
        time.sleep(35) # Threads側の生成待機
        
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

# --- 3. メインUI構成 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー完全管理システム [究極マスター版]")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")

# --- 4. サイドバー設定ユニット（リアルタイム反映） ---
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
if st.sidebar.button("LINEにテスト送信"):
    if send_line("疎通確認テストです。これが届けば設定は完璧です！"):
        st.sidebar.success("送信成功！")
    else:
        st.sidebar.error("送信失敗。Secretsの配置を確認してください。")

st.sidebar.divider()
st.sidebar.header("🧪 指定行テスト投稿")
test_row_idx = st.sidebar.number_input("何行目をテストする？", min_value=2, step=1, value=2)
if st.sidebar.button("🚀 テスト実行"):
    try:
        test_data = sheet.row_values(test_row_idx)
        if test_data and test_data[0]:
            texts = [t for t in test_data[0:5] if t.strip()]
            prog = st.empty()
            tid, first_url = None, ""
            for idx, txt in enumerate(texts):
                if idx > 0:
                    for t in range(300, 0, -1):
                        prog.warning(f"⏳ 【テスト】連結待機中 ({idx}/{len(texts)}本完了)\nあと **{t}** 秒...")
                        time.sleep(1)
                prog.info(f"📤 {idx+1}本目を投稿中...")
                ok, res = post_to_threads(txt, tid)
                if ok:
                    tid = res
                    if idx == 0: first_url = f"https://www.threads.net/t/{res}"
                    update_sheet_safe(sheet, test_row_idx, 6, f"テスト中:{idx+1}本完了")
                    send_line(f"🧪テスト実況: {idx+1}/{len(texts)}本目 成功")
                    st.write(f"✅ {idx+1}本目 成功")
                else:
                    st.error(f"❌ 失敗: {res}")
                    send_line(f"❌テスト失敗: {res}")
                    break
            else:
                update_sheet_safe(sheet, test_row_idx, 6, "テスト完了")
                send_line(f"🎊テスト完遂！リンク:\n{first_url}")
                st.balloons()
    except Exception as e: st.sidebar.error(f"エラー: {e}")

# --- 5. データ解析（全枠埋めロジック） ---
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

# --- 6. 自動投稿実行（60分・5分ルール・レジューム） ---
st.metric("今日の完了状況", f"{len(history)} / {new_m} 枠")

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
        first_id = task["data"][8] if len(task["data"]) > 8 else None
        
        if is_resuming:
            start_idx = int(task["status"].replace("本完了", ""))
            current_tid = task["data"][7] if len(task["data"]) > 7 else None
        
        if start_idx == 0:
            update_sheet_safe(sheet, task["row"], 7, jst_now.strftime("%Y-%m-%d %H:%M:%S"))
            send_line(f"⏳ 投稿開始 行:{task['row']} (全{len(texts)}本)")

        for idx in range(start_idx, len(texts)):
            if idx > 0:
                for t in range(300, 0, -1):
                    status_area.warning(f"🕒 ツリー連結待機中 ({idx}/{len(texts)}本完了)\nあと **{t}** 秒...")
                    time.sleep(1)
            
            status_area.info(f"📤 {idx+1}本目を投稿中...")
            ok, res_id = post_to_threads(texts[idx], current_tid)
            if ok:
                current_tid = res_id
                if idx == 0: first_id = res_id
                # 投稿ごとにシートとLINEを即時更新
                update_sheet_safe(sheet, task["row"], 6, f"{idx+1}本完了")
                update_sheet_safe(sheet, task["row"], 8, current_tid)
                update_sheet_safe(sheet, task["row"], 9, first_id)
                send_line(f"📈 実況: {idx+1}/{len(texts)}本目 成功")
                st.write(f"✅ {idx+1}本目 完了")
            else:
                err = str(res_id)[:20]
                update_sheet_safe(sheet, task["row"], 6, f"エラー:{err}")
                send_line(f"⚠️ エラー発生 行:{task['row']} 内容:{err}"); break
        else:
            update_sheet_safe(sheet, task["row"], 6, "完了")
            send_line(f"🎉 ツリー完遂！\nhttps://www.threads.net/t/{first_id}")
            st.rerun()
    elif time_gap < 3600 and not is_resuming:
        st.info(f"⏳ 60分間隔ルールにより待機中（あと {int((3600-time_gap)/60)} 分）")
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
