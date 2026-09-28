"""2026-09-28 Claude in Chrome 全件収集CSV（raw_260928_chrome_Ddx3eDIFKFN.csv）を既存台帳に統合する。
- Chrome版を正本として全行を台帳形式に変換
- 既存行（スクショ書き起こし）はChrome版に対応行があれば置き換え、無ければ残す
"""
import csv, re
from pathlib import Path
here = Path(__file__).parent
RAW = here/"raw_260928_chrome_Ddx3eDIFKFN.csv"
OLD = here/"看護師実声_採取台帳_追記_260927_意識低い系.csv"
URL = "https://www.threads.com/@moose.6927422/post/Ddx3eDIFKFN"
norm = lambda s: re.sub(r"[^\w]", "", s)

chrome = list(csv.DictReader(RAW.open(encoding="utf-8-sig")))
old = list(csv.reader(OLD.open(encoding="utf-8-sig")))
header, old_rows = old[0], old[1:]

# 自動照合で拾えなかった既存行の手動対応（スクショの判読不可・絵文字差・誤読が原因。いずれもChrome版が正）
MANUAL = {"〔判読不可〕所🏠": "78", "スーパーでシャンプーとか": "93", "〔判読不可〕です〜看取りも": "205",
          "外来はしごできナースと見た": "191", "コミュニケーションのされ方が": "135"}

def match(o):
    for k, n in MANUAL.items():
        if o[3].startswith(k): return next(c for c in chrome if c["番号"] == n)
    m = re.search(r"返信者@([^／（]+)", o[8]); u = m.group(1).strip() if m else ""
    frags = [norm(f) for f in re.split(r"〔[^〕]*〕", o[3]) if len(norm(f)) >= 3]
    for c in chrome:
        cu = c["返信者"]
        uu = u.replace("（投稿者）", "").split("（")[0]
        if "判読不可" in uu:
            if not cu.endswith(uu.replace("〔判読不可〕", "")): continue
        elif uu and cu != uu: continue
        ct = norm(c["原文"])
        if frags and all(f in ct for f in frags): return c
    return None

matched_ids, unmatched = set(), []
for o in old_rows:
    c = match(o)
    if c: matched_ids.add(c["番号"])
    else: unmatched.append(o)

rows = []
for c in chrome:
    who = c["返信者"] + ("（投稿者）" if c["投稿者か"] == "はい" else "")
    note = [f"返信者@{who}", f"返信先:{c['返信先']}", f"表示:{c['相対時刻']}・♡{c['いいね数']}・返信{c['返信数']}",
            f"Chrome全件収集2026-09-28 #{c['番号']}", "元投稿=@moose.6927422「意識低い系看護師」"]
    if c["備考"]: note.append(c["備考"])
    if "▓" in c["原文"]: note.append("▓＝取得時に絵文字が文字化け（原文は絵文字）")
    if c["番号"] not in matched_ids: note.append("2026-09-28新規")
    rows.append(["2026-09-28", URL, "Threadsリプ", c["原文"], "", "", "", "", "／".join(note)])
for o in unmatched:
    o = o[:]; o[8] += "／Chrome全件収集(2026-09-28)に該当行なし＝削除・非表示の可能性"; rows.append(o)

with OLD.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f); w.writerow(header); w.writerows(rows)
print("chrome", len(chrome), "matched", len(matched_ids), "new", len(chrome)-len(matched_ids),
      "old_unmatched", len(unmatched), "total", len(rows))
for o in unmatched: print("UNMATCHED:", o[8][:60], "|", o[3][:30].replace("\n"," "))
