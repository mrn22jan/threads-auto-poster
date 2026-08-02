"""Threads投稿の点検モジュール（ブラウザ・ログイン不要）

ログイン済みブラウザでの目視確認に頼らず、Threads Graph APIだけで
「ツリー欠落」「ad表記・リンクの欠落」「未返信リプ」を検出する。
"""

import re
import time
from datetime import datetime, timedelta, timezone

import requests

JST = timezone(timedelta(hours=9))
API_BASE = "https://graph.threads.net/v1.0"

# 商品投稿に必須の表記。いずれかにマッチすればad表記ありとみなす
AD_PATTERNS = [
    re.compile(r"(?<![a-zA-Z])ad(?![a-zA-Z])", re.IGNORECASE),
    re.compile(r"(?<![a-zA-Z])pr(?![a-zA-Z])", re.IGNORECASE),
    re.compile(r"広告"),
]
URL_PATTERN = re.compile(r"https?://\S+")

# 商品投稿ではない＝ad/リンク必須の対象外とみなすキーワード
DEFAULT_EXCLUDE_KEYWORDS = ["在宅ワーク", "募集", "お知らせ"]


# --- API取得 ---
def _get(url, params, timeout=30):
    """GETを3回までリトライし、JSONを返す"""
    last_error = None
    for attempt in range(3):
        if attempt > 0:
            time.sleep(2)
        try:
            res = requests.get(url, params=params, timeout=timeout)
            data = res.json()
            if "error" in data:
                last_error = data["error"].get("message", str(data["error"]))
                continue
            return data, None
        except Exception as e:
            last_error = str(e)
    return None, last_error


def fetch_own_posts(access_token, user_id, since_dt, until_dt):
    """指定期間に自分が投稿したスレッド（親投稿・返信を含む）を取得"""
    params = {
        "fields": "id,text,timestamp,permalink,is_reply,has_replies,root_post,replied_to",
        "since": int(since_dt.timestamp()),
        "until": int(until_dt.timestamp()),
        "limit": 100,
        "access_token": access_token,
    }
    posts, url = [], f"{API_BASE}/{user_id}/threads"
    while url:
        data, err = _get(url, params)
        if err:
            return posts, err
        posts.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None  # nextにはクエリが含まれる
    return posts, None


def fetch_conversation(access_token, root_id):
    """親投稿IDからツリー全体（自分の連投＋読者リプ）を取得"""
    params = {
        "fields": "id,text,timestamp,username,is_reply,replied_to,hide_status",
        "limit": 100,
        "access_token": access_token,
    }
    items, url = [], f"{API_BASE}/{root_id}/conversation"
    while url:
        data, err = _get(url, params)
        if err:
            return items, err
        items.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None
    return items, None


# --- 判定ロジック ---
def normalize(text):
    """比較用に空白を潰す"""
    return re.sub(r"\s+", "", text or "")


def texts_match(expected, actual):
    """投稿本文の一致判定。前方一致も許容する（絵文字置換などのゆらぎ対策）"""
    e, a = normalize(expected), normalize(actual)
    if not e:
        return False
    if e == a:
        return True
    head = e[:40]
    return bool(head) and head in a


def has_ad_mark(text):
    return any(p.search(text or "") for p in AD_PATTERNS)


def has_link(text):
    return bool(URL_PATTERN.search(text or ""))


def is_product_thread(texts, exclude_keywords):
    """除外キーワードを含むスレッドは商品投稿ではないと判定"""
    joined = "".join(texts)
    return not any(kw and kw in joined for kw in exclude_keywords)


def audit_row(access_token, row_index, row, exclude_keywords):
    """シート1行分を点検して結果dictを返す"""
    expected = [t for t in row[0:5] if (t or "").strip()]
    posted_at = row[6] if len(row) > 6 else ""
    root_id = row[7] if len(row) > 7 and row[7] else ""
    permalink = row[9] if len(row) > 9 else ""

    result = {
        "row": row_index,
        "title": (expected[0][:24] if expected else "-"),
        "posted_at": posted_at,
        "permalink": permalink,
        "expected_count": len(expected),
        "posted_count": 0,
        "missing": [],
        "is_product": is_product_thread(expected, exclude_keywords),
        "has_ad": has_ad_mark(expected[0] if expected else ""),
        "has_link": any(has_link(t) for t in expected),
        "pending_replies": [],
        "error": None,
    }

    if not root_id:
        result["error"] = "親投稿IDが未記録のためツリー照合不可"
        return result

    conversation, err = fetch_conversation(access_token, root_id)
    if err:
        result["error"] = f"API取得失敗: {err}"
        return result

    actual_texts = [c.get("text", "") for c in conversation]
    for idx, exp in enumerate(expected):
        if any(texts_match(exp, act) for act in actual_texts):
            result["posted_count"] += 1
        else:
            result["missing"].append({"index": idx + 1, "text": exp[:40]})

    # 自分以外のユーザーによるリプ＝読者リプ
    own_texts = [normalize(t) for t in expected]
    for c in conversation:
        body = normalize(c.get("text", ""))
        if not body or body in own_texts:
            continue
        if any(texts_match(exp, c.get("text", "")) for exp in expected):
            continue
        result["pending_replies"].append({
            "id": c.get("id"),
            "username": c.get("username", "?"),
            "text": (c.get("text") or "")[:60],
            "hidden": c.get("hide_status") == "HIDDEN",
        })

    return result


def audit_sheet_rows(access_token, rows_with_index, exclude_keywords=None, since_dt=None):
    """点検対象の行をまとめて処理する

    rows_with_index: [(行番号, 行データ), ...]
    since_dt: 指定するとこの時刻以降に投稿された行のみ対象
    """
    if exclude_keywords is None:
        exclude_keywords = DEFAULT_EXCLUDE_KEYWORDS

    results = []
    for row_index, row in rows_with_index:
        posted_at = row[6] if len(row) > 6 else ""
        if since_dt and posted_at:
            try:
                pt = datetime.strptime(posted_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
                if pt < since_dt:
                    continue
            except ValueError:
                pass
        results.append(audit_row(access_token, row_index, row, exclude_keywords))
    return results


# --- レポート生成 ---
def summarize(results):
    """点検結果を集計する"""
    tree_gaps = [r for r in results if r["missing"] and not r["error"]]
    ad_issues = [
        r for r in results
        if r["is_product"] and not r["error"] and (not r["has_ad"] or not r["has_link"])
    ]
    errors = [r for r in results if r["error"]]
    pending = [r for r in results if r["pending_replies"]]
    return {
        "checked": len(results),
        "tree_gaps": tree_gaps,
        "ad_issues": ad_issues,
        "errors": errors,
        "pending": pending,
    }


def format_report(results, now=None):
    """LINE通知向けのテキストを組み立てる"""
    now = now or datetime.now(JST)
    s = summarize(results)
    lines = [f"🔍 投稿点検レポート（{now.strftime('%m/%d %H:%M')} JST）"]
    lines.append(f"対象 {s['checked']} スレッド / API直接確認のためログイン不要")

    if s["tree_gaps"]:
        lines.append(f"\n⚠️ ツリー欠落 {len(s['tree_gaps'])} 件")
        for r in s["tree_gaps"]:
            nums = "・".join(str(m["index"]) for m in r["missing"])
            lines.append(f"・行{r['row']} {r['title']}: {r['expected_count']}本中 {nums}本目が未投稿")
    else:
        lines.append("\n✅ ツリー欠落 0 件")

    if s["ad_issues"]:
        lines.append(f"\n⚠️ ad表記・リンク欠落 {len(s['ad_issues'])} 件")
        for r in s["ad_issues"]:
            lack = []
            if not r["has_ad"]:
                lack.append("ad表記なし")
            if not r["has_link"]:
                lack.append("リンクなし")
            lines.append(f"・行{r['row']} {r['title']}: {'／'.join(lack)}")
    else:
        lines.append("✅ ad表記・リンク欠落 0 件")

    reply_count = sum(len(r["pending_replies"]) for r in s["pending"])
    lines.append(f"\n💬 読者リプ {reply_count} 件")

    if s["errors"]:
        lines.append(f"\n❗ 点検不能 {len(s['errors'])} 件")
        for r in s["errors"]:
            lines.append(f"・行{r['row']}: {r['error']}")

    return "\n".join(lines)
