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

# --- 認証関数 ---
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
        cid = res_data.get("id")
        if not cid: return False, f"コンテナ作成失敗:{res_data}"
        
        # Threads側の内部処理待ち
        time.sleep(30)
        
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        pub_res = res_pub.json()
        if "id" in pub_res:
            return True, pub_res["id"]
        return False, f"公開失敗:{pub_res}"
    except Exception as e:
        return False, str(e)

# --- 画面構成 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー完全管理システム")

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1
jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")

# --- サイドバー：行指定テスト投稿 ---
st.sidebar.header("🧪 テスト投稿ユニット")
target_row = st.sidebar.number_input("スプレッドシートの何行目をテストする？", min_value=2, step=1, value=2, help="スプレッドシートの左端に表示されている番号を入力してください。")

if st.sidebar.button("🚀 指定した行でテスト実行"):
    try:
        # 指定された行のデータを直接取得
        test_data = sheet.row_values(target_row)
        if not test_data or not test_data[0]:
            st.sidebar.error(f"{target_row}行目にはデータが見当たりません。")
        else:
            texts = [t for t in test_data[0:5] if t.strip()]
            st.info(f"📍 {target_row}行目のデータを取得しました（全{len(texts)}本）。テストを開始します。")
            
            progress_area = st.empty()
            last_id = None
            
            for idx, txt in enumerate(texts):
                if idx > 0:
                    # 5分待機 (300秒)
                    for t in range(300, 0, -1):
                        progress_area.warning(f"⏳ 【テスト中】ツリー連結待機中 ({idx}/{len(texts)}本完了)\n\n次の投稿まであと **{t}** 秒...")
                        time.sleep(1)
                
                progress_area.info(f"📤 {idx+1}本目を投稿しています...")
                ok, res = post_to_threads(txt, last_id)
                if ok:
                    last_id = res
                    st.write(f"✅ {idx+1}本目 成功！")
                else:
                    st.error(f"❌ {idx+1}本目で失敗: {res}")
                    break
            
            progress_area.success(f"🎉 {target_row}行目のテスト投稿がすべて完了しました！")
            st.balloons()
    except Exception as e:
        st.sidebar.error(f"エラーが発生しました: {e}")

# --- メインロジック (自動投稿) ---
st.divider()
all_rows = sheet.get_all_values()
data_rows = all_rows[1:]
history, schedule, last_t = [], [], None
allowed_hours = [9, 12, 15, 18, 21]

for i, r in enumerate(data_rows, start=2):
    status = r[5] if len(r) > 5 else ""
    if len(r) > 6 and r[6] and today_str in r[6]:
        if "完了" in status: history.append(r)
        try:
            pt = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if not last_t or pt > last_t: last_t = pt
        except: pass
    
    if r[0] and "完了" not in status:
        slot_idx = len(history) + len(schedule)
        h = allowed_hours[slot_idx] if slot_idx < len(allowed_hours) else 23
        m = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
        schedule.append({"row": i, "time": jst_now.replace(hour=h, minute=m, second=0), "data": r, "status": status})

if schedule:
    task = schedule[0]
    is_resuming = "本完了" in task["status"]
    can_post = not last_t or (jst_now - last_t).total_seconds() >= 3000
    
    if jst_now >= task["time"] and (can_post or is_resuming):
        st.subheader("🚀 自動投稿プロセス実行中")
        main_progress = st.empty()
        
        texts = [t for t in task["data"][0:5] if t.strip()]
        start_idx = 0
        if "本完了" in task["status"]:
            start_idx = int(task["status"].replace("本完了", ""))
        
        if start_idx == 0:
            sheet.update_cell(task["row"], 7, jst_now.strftime("%Y-%m-%d %H:%M:%S"))

        current_last_id = None 
        for idx in range(start_idx, len(texts)):
            if idx > 0:
                for t in range(300, 0, -1):
                    main_progress.warning(f"🕒 ツリー連結待機中... ({idx}/{len(texts)}本目完了)\n\n**次の投稿まであと {t} 秒**")
                    time.sleep(1)
            
            main_progress.info(f"📤 {idx+1}本目を投稿中...")
            ok, res_id = post_to_threads(texts[idx], current_last_id)
            
            if ok:
                current_last_id = res_id
                sheet.update_cell(task["row"], 6, f"{idx+1}本完了")
                st.write(f"✅ {idx+1}本目 完了")
            else:
                sheet.update_cell(task["row"], 6, f"エラー:{str(res_id)[:10]}")
                break
        else:
            sheet.update_cell(task["row"], 6, "完了")
            st.rerun()
    else:
        st.info(f"📅 次の予定: **{task['time'].strftime('%H:%M')}** ({task['row']}行目のデータ)")

st.divider()
tab1, tab2 = st.tabs(["📋 今日の履歴", "📅 これからの予定"])
with tab1: st.table([{"時間": r[6].split(" ")[1] if len(r)>6 else "-", "内容": r[0][:20], "状態": r[5]} for r in history])
with tab2: st.table([{"行": s["row"], "予定時間": s["time"].strftime("%H:%M"), "内容": s["data"][0][:20]} for s in schedule])
