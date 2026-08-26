#!/usr/bin/env bash
# 「マリン秘書bot」として Slack にメッセージを投稿するヘルパー。
# 送信にはSlack アプリ「マリン秘書bot」(旧TikTok朝ブリーフ) の Bot Token を使う。
# アプリ名自体がマリン秘書botのため表示名の上書きは不要。
#
# 使い方:
#   SLACK_MARIN_BOT_TOKEN=xoxb-... ./notify_marin_bot.sh "#チャンネル名" "メッセージ本文"
#
# チャンネルはチャンネルID (C0XXXXXXX) でも #名前 でも可。
# 非公開チャンネルへは事前に /invite @TikTok朝ブリーフ が必要。
# 表示名/アイコンは環境変数 MARIN_BOT_USERNAME / MARIN_BOT_ICON で変更可能。

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <channel> <message>" >&2
  exit 1
fi

: "${SLACK_MARIN_BOT_TOKEN:?環境変数 SLACK_MARIN_BOT_TOKEN が未設定です}"

channel="$1"
message="$2"
username="${MARIN_BOT_USERNAME:-マリン秘書bot}"
icon="${MARIN_BOT_ICON:-:woman_office_worker:}"

payload=$(python3 - "$channel" "$message" "$username" "$icon" <<'PY'
import json, sys
print(json.dumps({
    "channel": sys.argv[1],
    "text": sys.argv[2],
    "username": sys.argv[3],
    "icon_emoji": sys.argv[4],
}))
PY
)

res=$(curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer ${SLACK_MARIN_BOT_TOKEN}" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data "$payload")

ok=$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("ok"))' <<<"$res")
if [[ "$ok" != "True" ]]; then
  echo "Slack 投稿に失敗しました: $res" >&2
  exit 1
fi
echo "${username} として投稿しました: $channel"
