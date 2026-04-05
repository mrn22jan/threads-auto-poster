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

# --- 認証 ---
@st.cache_resource
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)

client = get_client()
sheet = client.open_by_key(SHEET_ID).sheet1

def post_to_threads(text, reply_to_id=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    try:
        # 1. コンテナ作成
        res = requests.post(base_url, data=payload, timeout=60)
        cid = res.json().get("id")
        if not cid: return False, res.json()
        
        # 2. メディア処理待ち (Threads推奨の30秒待機)
        time.sleep(30)
        
        # 3. 公開
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        return ("id" in res_pub.json()), res_pub.json().get("id")
    except Exception as e:
        return False, str(e)

# --- メインロジック ---
st.title("💸 ロクレンジャー自動投稿")

jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")
all_data = sheet.get_all_values()
rows = all_data[1:]

# 履歴と予定の整理
today_posts = []
future_tasks = []
last_time = None
allowed_hours = sorted([9, 12, 15, 18, 21]) # デフォルト

for i, row in enumerate(rows, start=2):
    if len(row) > 6 and row[6] and today_str in row[6]:
        p_t = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
        if row[5]: today_posts.append(row)
        if not last_time or p_t > last_time: last_time = p_t
    if row[0] and (len(row) <= 5 or not row[5]):
        h = allowed_hours[len(today_posts) + len(future_tasks)] if (len(today_posts) + len(future_tasks)) < len(allowed_hours) else 23
        m = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
        future_tasks.append({"row": i, "time": jst_now.replace(hour=h, minute=m, second=0), "data": row})

# 実行
if future_tasks:
    task = future_tasks[0]
    # 60分間隔 & 予約時間
    if jst_now >= task["time"] and (not last_time or (jst_now - last_time).total_seconds() >= 3600):
        st.warning(f"🚀 投稿開始: {task['data'][0][:20]}...")
        
        # 1つずつ投稿 & 都度シート更新
        texts = [t for t in task["data"][0:5] if t.strip()]
        last_id = None
        
        # 投稿開始時刻を先に打つ
        sheet.update_cell(task["row"], 7, datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S"))

        for idx, txt in enumerate(texts):
            if idx > 0:
                # サーバー切断防止カウントダウン (10秒ごとに画面更新)
                msg = st.empty()
                for t in range(300, 0, -10):
                    msg.info(f"⏳ ツリー連結待機中... 残り約{t}秒")
                    time.sleep(10)
                msg.empty()
            
            ok, res_id = post_to_threads(txt, last_id)
            if ok:
                last_id = res_id
                sheet.update_cell(task["row"], 6, f"{idx+1}本目完了")
                st.write(f"✅ {idx+1}本目成功")
            else:
                sheet.update_cell(task["row"], 6, f"エラー:{str(res_id)[:15]}")
                break
        else:
            sheet.update_cell(task["row"], 6, "完了")
            st.success("🎉 全て完了！")
            st.rerun()

st.divider()
st.subheader("📋 本日の状況")
if today_posts:
    st.table([{"時間": r[6].split(" ")[1], "本文": r[0][:30], "状態": r[5]} for r in today_posts])
