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
        res = requests.post(base_url, data=payload, timeout=60)
        cid = res.json().get("id")
        if not cid: return False, res.json()
        time.sleep(30) # Threads側の処理待ち
        pub_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        res_pub = requests.post(pub_url, data={"creation_id": cid, "access_token": ACCESS_TOKEN}, timeout=60)
        return ("id" in res_pub.json()), res_pub.json().get("id")
    except Exception as e:
        return False, str(e)

# --- メイン UI ---
st.set_page_config(page_title="ロクレンジャー自動投稿", layout="wide")
st.title("💸 Threads 自動投稿管理システム")

jst_now = datetime.now(timezone(timedelta(hours=9)))
today_str = jst_now.strftime("%Y-%m-%d")
all_data = sheet.get_all_values()
rows = all_data[1:]

# --- データ解析 ---
today_history = []
future_schedule = []
last_time = None
allowed_hours = sorted([9, 12, 15, 18, 21]) # 投稿許可時間

# 1. 履歴と予定を分類
for i, row in enumerate(rows, start=2):
    # 履歴 (今日の日付がG列にあり、F列にステータスがあるもの)
    if len(row) > 6 and row[6] and today_str in row[6]:
        p_t = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
        if row[5]:
            today_history.append({"時間": row[6].split(" ")[1], "本文": row[0][:30], "状態": row[5]})
        if not last_time or p_t > last_time:
            last_time = p_t
            
    # 予定 (本文があり、ステータスが空のもの)
    if row[0] and (len(row) <= 5 or not row[5]):
        slot_idx = len(today_history) + len(future_schedule)
        if slot_idx < len(allowed_hours):
            h = allowed_hours[slot_idx]
            m = int(hashlib.md5(f"{today_str}_{i}".encode()).hexdigest(), 16) % 60
            sched_time = jst_now.replace(hour=h, minute=m, second=0, microsecond=0)
            future_schedule.append({"row": i, "time": sched_time, "data": row})

# --- 上部メトリクス ---
st.metric("今日の投稿数", f"{len(today_history)} / {len(allowed_hours)}")

# --- 投稿実行ロジック ---
can_post = True
if last_time and (jst_now - last_time).total_seconds() < 3600:
    can_post = False

if future_schedule:
    next_task = future_schedule[0]
    is_time = jst_now >= next_task["time"]
    
    if is_time and can_post:
        st.warning(f"🚀 予約時間({next_task['time'].strftime('%H:%M')})になりました。投稿を開始します...")
        r_idx = next_task["row"]
        
        # 開始時間を打つ
        sheet.update_cell(r_idx, 7, datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S"))
        sheet.update_cell(r_idx, 6, "処理開始中...")
        
        texts = [t for t in next_task["data"][0:5] if t.strip()]
        last_id = None
        count = 0
        
        for idx, txt in enumerate(texts):
            if idx > 0:
                msg = st.empty()
                for t in range(300, 0, -10): # 10秒ごとに刻んでサーバーを切断させない
                    msg.info(f"⏳ ツリー連結待機中... 残り約{t}秒 ({idx}/{len(texts)-1})")
                    time.sleep(10)
                msg.empty()
            
            ok, res = post_to_threads(txt, last_id)
            if ok:
                last_id = res
                count += 1
                sheet.update_cell(r_idx, 6, f"{count}本完了")
                st.write(f"✅ {count}本目 送信成功")
            else:
                sheet.update_cell(r_idx, 6, f"エラー中断")
                break
        
        if count == len(texts):
            sheet.update_cell(r_idx, 6, "完了")
            st.success("🎉 全てのツリー投稿が完了しました！")
            time.sleep(5)
            st.rerun()
    elif not is_time:
        st.info(f"📅 次の投稿予定：**{next_task['time'].strftime('%H:%M')}**")
    elif not can_post:
        st.info("⏳ 1時間の間隔を空けるために待機しています。")

st.divider()

# --- 履歴と予定のテーブル表示 ---
col1, col2 = st.tabs(["📋 今日の投稿履歴", "📅 これからの予約状況"])

with col1:
    if today_history:
        st.table(today_history)
    else:
        st.write("本日の履歴はまだありません。")

with col2:
    if future_schedule:
        # 見やすく加工
        display_future = []
        for f in future_schedule:
            display_future.append({
                "予定時間": f["time"].strftime("%H:%M"),
                "本文1の内容": f["data"][0][:40] + "..."
            })
        st.table(display_future)
    else:
        st.write("今日のこれからの予定はありません。")
