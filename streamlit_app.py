import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone

# --- 設定 ---
SETTINGS_FILE = "bot_settings.json"
GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]

# --- 認証 ---
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
    if len(text) > 500:
        return False, "文字数が500文字を超えています"
    
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id: payload["reply_to_id"] = reply_to_id
    
    res = requests.post(base_url, data=payload)
    res_data = res.json()
    if "id" not in res_data: return False, res_data
    container_id = res_data["id"]
    time.sleep(10) # 安定公開のための待機
    
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    res_pub = requests.post(publish_url, data={"creation_id": container_id, "access_token": ACCESS_TOKEN})
    res_pub_data = res_pub.json()
    return ("id" in res_pub_data), res_pub_data.get("id")

# --- UI設定 ---
st.set_page_config(page_title="チャリンチャリンシステム", layout="wide")
current_settings = load_settings()

st.sidebar.header("⚙️ システム設定")
new_hours = st.sidebar.multiselect("投稿許可時間（時）", options=list(range(24)), default=current_settings["allowed_hours"])
new_max = st.sidebar.number_input("1日の最大投稿数", min_value=1, max_value=24, value=current_settings["max_posts"])

if new_hours != current_settings["allowed_hours"] or new_max != current_settings["max_posts"]:
    save_settings({"allowed_hours": new_hours, "max_posts": new_max})
    st.sidebar.success("設定を更新しました")

st.title("💸 ロクレンジャー用Threads 自動投稿管理チャリンチャリンシステム")

# --- データ取得 ---
jst_now = get_jst_now()
all_data = sheet.get_all_values()
rows = all_data[1:]
today_str = jst_now.strftime("%Y-%m-%d")

today_posts = []
future_posts = []
last_post_time = None

for row in rows:
    # 履歴取得
    if len(row) > 6 and row[6] and today_str in row[6]:
        try:
            p_time = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if row[5] == "完了":
                today_posts.append({"時間": row[6].split(" ")[1], "本文1": row[0]})
            if last_post_time is None or p_time > last_post_time:
                last_post_time = p_time
        except:
            pass
    # 予定取得
    if len(row) > 0 and row[0] and (len(row) <= 5 or not row[5]):
        future_posts.append(row)

# --- 投稿間隔チェック ---
can_post = True
wait_seconds = 0
if last_post_time:
    diff_sec = (jst_now - last_post_time).total_seconds()
    if diff_sec < 3600:
        can_post = False
        wait_seconds = int(3600 - diff_sec)

# --- ステータス表示 ---
col1, col2 = st.columns(2)
with col1:
    st.metric("今日の投稿数", f"{len(today_posts)} / {new_max}")
with col2:
    stock_count = len(future_posts)
    if stock_count <= 3:
        st.warning(f"⚠️ 弾切れ注意！未投稿ネタが残り **{stock_count}** 件です")
    else:
        st.success(f"✅ ネタ在庫：残り **{stock_count}** 件")

# --- 自動投稿ロジック ---
if not can_post:
    st.warning(f"⏳ チャージ中... 次の投稿まであと **{wait_seconds // 60}分 {wait_seconds % 60}秒** （自動で投稿されます）")
elif jst_now.hour not in new_hours:
    st.info(f"💤 待機時間。次のチャンスは {min([h for h in new_hours if h > jst_now.hour] or [min(new_hours)])}時 です。")
elif len(today_posts) >= new_max:
    st.error("🚫 本日の最大投稿数に達しました。")
else:
    for i, row in enumerate(rows, start=2):
        # ステータス列（F列 = index 5）が空のものを探す
        status = row[5] if len(row) > 5 else ""
        if row[0] and not status:
            st.info(f"🚀 {i}行目の投稿を開始しました。5分おきにツリーを繋げます...")
            sheet.update_cell(i, 6, "投稿中...")
            sheet.update_cell(i, 7, get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))
            
            valid_texts = [t for t in [row[0], row[1], row[2], row[3], row[4]] if t.strip()]
            last_id = None
            
            for idx, text in enumerate(valid_texts):
                if idx > 0:
                    placeholder = st.empty()
                    for t in range(300, 0, -1):
                        placeholder.warning(f"⏳ ツリー連結中... あと {t // 60}分 {t % 60}秒 ({idx}/{len(valid_texts)-1}つ目)")
                        time.sleep(1)
                    placeholder.empty()
                
                success, res_id = post_to_threads(text, reply_to_id=last_id)
                if success:
                    last_id = res_id
                    st.write(f"✅ 本文{idx+1} 成功")
                else:
                    st.error(f"❌ 本文{idx+1} 失敗: {res_id}")
                    break
            else:
                sheet.update_cell(i, 6, "完了")
                st.success("💰 全ての投稿が完了しました！チャリンチャリン！")
                st.balloons()
                time.sleep(5)
                st.rerun()
            break

st.divider()

# --- 📋 本日の履歴と予定 ---
tab1, tab2 = st.tabs(["📋 本日の投稿履歴", "📅 今後の投稿予定"])

with tab1:
    if today_posts: st.table(today_posts)
    else: st.write("本日の履歴はまだありません。")

with tab2:
    if future_posts:
        display_future = []
        next_time = jst_now if can_post else (last_post_time + timedelta(hours=1))
        for idx, post in enumerate(future_posts):
            est_time = (next_time + timedelta(hours=idx)).strftime("%m/%d %H:%M頃")
            cd = "準備完了" if (idx==0 and can_post) else f"約{idx}〜{idx+1}時間後"
            display_future.append({"目安時間": est_time, "メイン内容": post[0][:30], "ツリー数": sum(1 for x in post[1:5] if len(post) > x and post[x].strip()), "状態": cd})
        st.table(display_future)
    else: st.write("予定はありません。スプレッドシートを補充してください。")
