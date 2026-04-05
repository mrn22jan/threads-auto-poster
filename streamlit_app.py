import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone

# 1. 接続設定
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
SETTINGS_FILE = "bot_settings.json"

# 2. 認証
scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f: json.dump(settings, f)

def post_to_threads(text, reply_to_id=None):
    """コンテナ作成から公開までを完結させ、投稿IDを返す"""
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: 
        payload["reply_to_id"] = reply_to_id
    
    # ① コンテナ作成
    res = requests.post(base_url, data=payload)
    res_data = res.json()
    if "id" not in res_data: return False, res_data
    container_id = res_data["id"]
    
    # Threads側の反映待ち（公式推奨：数秒）
    time.sleep(10)
    
    # ② 公開実行
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN})
    res_pub_data = res_pub.json()
    
    if "id" in res_pub_data:
        return True, res_pub_data["id"] # 実際の公開済み投稿IDを返す
    else:
        return False, res_pub_data

# --- UI ---
st.set_page_config(page_title="Threads Bot", layout="wide")
current_settings = load_settings()
st.sidebar.header("⚙️ 自動投稿ルール")
new_hours = st.sidebar.multiselect("投稿許可時間（時）※日本時間", options=list(range(24)), default=current_settings["allowed_hours"])
new_max = st.sidebar.number_input("1日の最大投稿数", min_value=1, max_value=24, value=current_settings["max_posts"])

if new_hours != current_settings["allowed_hours"] or new_max != current_settings["max_posts"]:
    save_settings({"allowed_hours": new_hours, "max_posts": new_max})
    st.sidebar.success("設定を保存しました")

st.title("🤖 Threads 自動投稿管理（厳格間隔モード）")

# --- データ取得 ---
jst_now = get_jst_now()
all_data = sheet.get_all_values()
rows = all_data[1:]
today_str = jst_now.strftime("%Y-%m-%d")

today_posts = []
last_post_time = None

for row in rows:
    # 完了 または 投稿中 のものをチェック
    if len(row) > 6 and row[6] and today_str in row[6]:
        # 時刻をパース
        p_time = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
        if row[5] == "完了":
            today_posts.append({"時間": row[6].split(" ")[1], "本文1": row[0], "状況": "✅ 完了"})
        
        if last_post_time is None or p_time > last_post_time:
            last_post_time = p_time

# --- 判定：60分間隔 ---
can_post = True
diff_min = 0
if last_post_time:
    diff_sec = (jst_now - last_post_time).total_seconds()
    if diff_sec < 3600: # 60分 = 3600秒
        can_post = False
        diff_min = int((3600 - diff_sec) / 60)

st.write(f"⌚️ 現在の日本時間: **{jst_now.strftime('%H:%M:%S')}**")
st.metric("本日の投稿数", f"{len(today_posts)} / {new_max}")

# --- メインロジック ---
if not can_post:
    st.warning(f"⏳ 次の新規投稿まであと **{diff_min}分** 待機が必要です。")
elif jst_now.hour not in new_hours:
    st.info("😴 投稿許可時間外です。")
elif len(today_posts) >= new_max:
    st.error("🚫 本日の上限に達しました。")
else:
    # 投稿可能な行を探す
    for i, row in enumerate(rows, start=2):
        if row[0] and not row[5]: # 本文あり 且つ ステータス空
            st.warning(f"🚀 {i}行目のツリー投稿を開始します（間隔：ツリー間5分）")
            
            # 【重要】リロード対策：まずシートに「投稿中」と書いてロックする
            sheet.update_cell(i, 6, "投稿中...")
            sheet.update_cell(i, 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
            
            valid_texts = [t for t in [row[0], row[1], row[2], row[3], row[4]] if t.strip()]
            last_id = None
            all_ok = True
            
            for idx, text in enumerate(valid_texts):
                if idx > 0:
                    # 本文2以降を投げる前に5分待機
                    st.write(f"  ⏳ ツリー間隔保持のため **5分間待機** します... ({idx}/{len(valid_texts)-1})")
                    time.sleep(300) 
                
                success, res_id = post_to_threads(text, reply_to_id=last_id)
                if success:
                    last_id = res_id
                    st.write(f"  ✅ 本文{idx+1} 投稿成功")
                else:
                    st.error(f"  ❌ 本文{idx+1} でエラー: {res_id}")
                    all_ok = False
                    break
            
            if all_ok:
                sheet.update_cell(i, 6, "完了")
                st.success("🎊 すべてのツリーが5分間隔で正常に投稿されました！")
                time.sleep(2)
                st.rerun()
            else:
                sheet.update_cell(i, 6, "失敗あり")
                st.error("一部の投稿に失敗したため中断しました。")
            break

# ログ表示
st.subheader("📋 本日の履歴")
if today_posts: st.table(today_posts)
