import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

# --- 1. 安全な設定取得（すべてSecretsから読み込む） ---
LINE_CHANNEL_TOKEN = st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = st.secrets.get("LINE_USER_ID")

GOOGLE_JSON = st.secrets["google_json"]
SHEET_ID = st.secrets["sheet_id"]
ACCESS_TOKEN = st.secrets["threads_access_token"]
THREADS_USER_ID = st.secrets["threads_user_id"]
SETTINGS_FILE = "bot_settings.json"
REPLY_INTERVAL_SECONDS = 300
NEW_THREAD_INTERVAL_SECONDS = 3600

# --- 2. 認証・通知・通信関数 ---
@st.cache_resource
def get_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GOOGLE_JSON, scopes=scope)
    return gspread.authorize(creds)


def send_line(msg):
    """LINE実況通知：Secretsから取得した情報で送信"""
    if not LINE_CHANNEL_TOKEN or not LINE_USER_ID:
        return False, "LINE Secrets未設定"

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": f"【Threads Bot実況】\n{msg}"}],
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            return True, "OK"
        return False, f"LINE API {res.status_code}: {res.text[:120]}"
    except Exception as e:
        return False, f"LINE送信例外: {e}"


def notify_line(msg, status_area=None):
    ok, detail = send_line(msg)
    if not ok and status_area is not None:
        status_area.warning(f"⚠️ LINE通知失敗: {detail}")
    return ok, detail


def update_sheet_safe(sheet, row, col, val):
    """Googleシートへの書き込みを3回までリトライ"""
    for _ in range(3):
        try:
            sheet.update_cell(row, col, val)
            return True
        except Exception:
            time.sleep(2)
    return False


def post_to_threads(text, reply_to_id=None):
    """Threadsへの投稿とPermalink取得"""
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    payload = {"media_type": "TEXT", "text": text, "access_token": ACCESS_TOKEN}
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id

    try:
        res = requests.post(base_url, data=payload, timeout=60)
        create_data = res.json()
        cid = create_data.get("id")
        if not cid:
            return False, f"API拒否:{create_data}", ""

        publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
        last_error = "公開失敗"
        for attempt in range(6):
            if attempt > 0:
                time.sleep(10)

            res_pub = requests.post(
                publish_url,
                data={"creation_id": cid, "access_token": ACCESS_TOKEN},
                timeout=60,
            )
            pub_data = res_pub.json()
            pid = pub_data.get("id")
            if pid:
                permalink_url = (
                    f"https://graph.threads.net/v1.0/{pid}?fields=permalink&access_token={ACCESS_TOKEN}"
                )
                p_res = requests.get(permalink_url, timeout=30).json()
                return True, pid, p_res.get("permalink", f"https://www.threads.net/t/{pid}")

            last_error = str(pub_data)

        return False, f"公開失敗:{last_error}", ""
    except Exception as e:
        return False, str(e), ""


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"allowed_hours": [9, 12, 15, 18, 21], "max_posts": 5}


def parse_completed_count(status):
    status = (status or "").strip()
    if status.endswith("本完了"):
        try:
            return int(status.replace("本完了", ""))
        except ValueError:
            return 0
    return 0


def is_test_status(status):
    return (status or "").strip().startswith("テスト")


# --- 3. UI・初期化 ---
st.set_page_config(page_title="Threads自動投稿", layout="wide")
st.title("🧵 Threadsツリー管理システム [Public安全運用版]")

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
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"allowed_hours": new_h, "max_posts": new_m}, f)
    st.sidebar.success("保存完了")

if st.sidebar.button("🔔 LINEにテスト送信"):
    ok, detail = send_line("Secrets設定を使用した通知テストです。")
    if ok:
        st.sidebar.success("成功！")
    else:
        st.sidebar.error(f"失敗: {detail}")

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
                    for t in range(REPLY_INTERVAL_SECONDS, 0, -1):
                        prog.warning(f"⏳ 待機中 ({idx}/{len(texts)})\nあと **{t}** 秒...")
                        time.sleep(1)
                prog.info(f"📤 {idx+1}本目を投稿中...")
                ok, res_id, link = post_to_threads(txt, tid)
                if ok:
                    tid = res_id
                    if idx == 0:
                        final_link = link
                    update_sheet_safe(sheet, test_row_idx, 6, f"テスト中:{idx+1}本完了")
                    line_ok, line_detail = notify_line(f"🧪実況: {idx+1}/{len(texts)}本目 成功！\n🔗URL: {final_link}")
                    if not line_ok:
                        st.warning(f"LINE通知失敗: {line_detail}")
                    st.write(f"✅ {idx+1}本目 成功")
                else:
                    st.error(f"❌ 失敗: {res_id}")
                    break
            line_ok, line_detail = notify_line(f"🎊テスト完遂！\n{final_link}")
            if not line_ok:
                st.warning(f"LINE通知失敗: {line_detail}")
    except Exception as e:
        st.sidebar.error(f"エラー: {e}")

# --- 5. データ解析 ---
all_rows = sheet.get_all_values()
data_rows = all_rows[1:]
history, last_t = [], None
today_activity = []
available_data = []

for i, r in enumerate(data_rows, start=2):
    status = r[5] if len(r) > 5 else ""
    has_today_timestamp = len(r) > 6 and r[6] and today_str in r[6]

    if has_today_timestamp and not is_test_status(status):
        today_activity.append({"row": i, "data": r, "status": status})

    if has_today_timestamp and status.strip() == "完了":
        history.append(r)
        try:
            pt = datetime.strptime(r[6], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            if not last_t or pt > last_t:
                last_t = pt
        except Exception:
            pass
    elif r and r[0] and status.strip() != "完了" and not is_test_status(status):
        available_data.append({"row": i, "data": r, "status": status})

available_data.sort(
    key=lambda x: (
        0 if parse_completed_count(x["status"]) > 0 else 1,
        x["row"],
    )
)

today_activity.sort(
    key=lambda x: x["data"][6] if len(x["data"]) > 6 and x["data"][6] else "",
    reverse=True,
)

allowed_slots = sorted(new_h)[:new_m]
schedule = []
used_count = len(history)
slot_count = max(1, len(allowed_slots))

for i, t_info in enumerate(available_data):
    status = t_info["status"]
    texts = [t for t in t_info["data"][0:5] if t.strip()]
    completed_count = parse_completed_count(status)
    last_exec_time = None

    if len(t_info["data"]) > 6 and t_info["data"][6]:
        try:
            last_exec_time = datetime.strptime(t_info["data"][6], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=9))
            )
        except Exception:
            last_exec_time = None

    if completed_count > 0 and completed_count < len(texts):
        stime = (last_exec_time + timedelta(seconds=REPLY_INTERVAL_SECONDS)) if last_exec_time else jst_now
        schedule_type = "続き"
    else:
        idx = used_count + i
        slot_idx = idx % slot_count
        day_offset = idx // slot_count
        base_day = jst_now + timedelta(days=day_offset)
        h = allowed_slots[slot_idx]
        key_date = base_day.strftime("%Y-%m-%d")
        m = int(hashlib.md5(f"{key_date}_{t_info['row']}".encode()).hexdigest(), 16) % 60
        stime = base_day.replace(hour=h, minute=m, second=0, microsecond=0)
        schedule_type = "新規"

    schedule.append({
        "row": t_info["row"],
        "time": stime,
        "data": t_info["data"],
        "status": status,
        "kind": schedule_type,
    })

# --- 6. 自動投稿実行 ---
st.metric("今日の状況", f"{len(history)} / {new_m} 完了")

new_stock_rows = [x for x in available_data if parse_completed_count(x["status"]) == 0 and not x["status"].startswith("エラー")]
new_stock_count = len(new_stock_rows)
stock_alert_threshold = max(3, new_m * 2)
if new_stock_count <= stock_alert_threshold:
    approx_days = (new_stock_count / new_m) if new_m else 0
    st.warning(f"⚠️ 投稿ストックが少なめです。新規投稿候補は残り {new_stock_count} 件（約 {approx_days:.1f} 日分）です。")

if schedule:
    task = schedule[0]
    task_status = task["status"]
    completed_count = parse_completed_count(task_status)
    valid_resume_status = task_status.strip().endswith("本完了") and completed_count > 0
    is_resuming = valid_resume_status
    texts = [t for t in task["data"][0:5] if t.strip()]

    last_exec_time = None
    if len(task["data"]) > 6 and task["data"][6]:
        try:
            last_exec_time = datetime.strptime(task["data"][6], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone(timedelta(hours=9))
            )
        except Exception:
            last_exec_time = None

    time_gap = (jst_now - last_t).total_seconds() if last_t else 9999
    elapsed_since_last_exec = (jst_now - last_exec_time).total_seconds() if last_exec_time else 9999

    ready_for_new_thread = (
        not is_resuming
        and jst_now >= task["time"]
        and time_gap >= NEW_THREAD_INTERVAL_SECONDS
    )
    ready_for_next_reply = (
        is_resuming
        and completed_count < len(texts)
        and elapsed_since_last_exec >= REPLY_INTERVAL_SECONDS
    )

    if ready_for_new_thread or ready_for_next_reply:
        idx = completed_count
        saved_parent_tid = task["data"][7] if len(task["data"]) > 7 and task["data"][7] else None
        current_tid = saved_parent_tid if valid_resume_status else None
        current_link = task["data"][9] if len(task["data"]) > 9 else ""
        reply_to_id = current_tid if idx > 0 else None
        status_area = st.empty()

        status_area.info(f"📤 {idx+1}本目を投稿中...")
        ok, res_id, permalink = post_to_threads(texts[idx], reply_to_id)

        if ok:
            current_tid = res_id
            if idx == 0:
                current_link = permalink

            now_str = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
            update_sheet_safe(sheet, task["row"], 7, now_str)
            update_sheet_safe(sheet, task["row"], 8, current_tid)
            update_sheet_safe(sheet, task["row"], 10, current_link)

            if idx == len(texts) - 1:
                update_sheet_safe(sheet, task["row"], 6, "完了")
                line_ok, line_detail = notify_line(f"🎉 完遂しました！\n{current_link}", status_area)
                st.success(f"✅ {idx+1}/{len(texts)}本目を投稿し、スレッド完了にしました。")
            else:
                update_sheet_safe(sheet, task["row"], 6, f"{idx+1}本完了")
                line_ok, line_detail = notify_line(f"📈 実況: {idx+1}/{len(texts)}本目 成功\n🔗URL: {current_link}", status_area)
                st.success(
                    f"✅ {idx+1}/{len(texts)}本目を投稿しました。次回は {REPLY_INTERVAL_SECONDS} 秒後以降に続きを投稿します。"
                )
        else:
            update_sheet_safe(sheet, task["row"], 6, f"エラー:{res_id[:40]}")
            line_ok, line_detail = notify_line(f"⚠️ エラー: {res_id}", status_area)
            st.error(f"❌ 投稿失敗: {res_id}")

    elif is_resuming and completed_count < len(texts):
        remaining = max(0, int(REPLY_INTERVAL_SECONDS - elapsed_since_last_exec))
        st.info(f"🕒 次のツリー待機中（あと {remaining} 秒）")
    elif time_gap < NEW_THREAD_INTERVAL_SECONDS:
        remaining = max(0, int(NEW_THREAD_INTERVAL_SECONDS - time_gap))
        st.info(f"⏳ 60分間隔ルール待機中（あと {remaining // 60} 分）")
    else:
        display_schedule = [s for s in schedule if s["time"] > jst_now]
        if display_schedule:
            st.info(f"📅 次回: **{display_schedule[0]['time'].strftime('%m/%d %H:%M')}**")

st.divider()
t1, t2 = st.tabs(["📋 今日の履歴", "📅 これからの予定"])
with t1:
    st.table([
        {
            "行": x["row"],
            "時間": x["data"][6].split(" ")[1] if len(x["data"]) > 6 and x["data"][6] else "-",
            "内容": x["data"][0][:20],
            "状態": x["status"] if x["status"] else "-",
        }
        for x in today_activity
    ])
with t2:
    st.table([
        {
            "行": s["row"],
            "予定": s["time"].strftime("%m/%d %H:%M"),
            "種別": s["kind"],
            "状態": s["status"] if s["status"] else "新規",
            "内容": s["data"][0][:20],
        }
        for s in schedule
    ])
