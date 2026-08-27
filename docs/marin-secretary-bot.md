# マリン秘書bot — Slack 通知の送信元を bot にする仕組み

## 背景

Claude のルーティン（定期タスク）からの Slack 通知は、Slack コネクタ（MCP）経由だと
**本人のアカウントからの投稿**になってしまい、自分の投稿には Slack の通知が鳴らない。

これを解決するため、Slack アプリ **「マリン秘書bot」**（旧 TikTok朝ブリーフ、App ID
A0B6JSY5X9A）の Bot Token で `chat.postMessage` を直接呼んで通知を送る。
bot からの投稿なら通常のメッセージと同じように通知が届く。

## 前提（設定済み）

- Slack アプリ「マリン秘書bot」に Bot Token Scopes: `chat:write`, `chat:write.public`
- Install to Workspace 済み → Bot User OAuth Token（`xoxb-...`）発行済み
- 非公開チャンネル（例: #kondate-memo）に投稿する場合のみ、そのチャンネルで
  `/invite @マリン秘書bot` が必要（公開チャンネルは不要）

## ルーティン／タスクへの組み込み方

通知を送っている各ルーティン（Cowork のスケジュールタスクなど）の指示文で、
「Slack で通知する」の部分を以下に置き換える。`<BOT_TOKEN>` は実際の
`xoxb-` トークンに置き換えること（トークンは Slack アプリの
OAuth & Permissions ページでいつでも確認できる）。

```
【Slack通知のルール】
Slackへの通知はSlackコネクタ(MCP)を使わず、必ず「マリン秘書bot」名義で送ること。
Bash で次の curl を実行して chat.postMessage を呼ぶ:

curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer <BOT_TOKEN>" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data '{"channel": "#通知先チャンネル", "text": "通知本文"}'

応答の "ok": true を確認し、false ならエラー内容を報告する。
本文は Slack の mrkdwn（*太字* など）が使える。
```

## 実行環境ごとの注意

- **Cowork（Mac のデスクトップアプリ）のタスク**: そのまま動く（ネットワーク制限なし）。
- **claude.ai/code のクラウド環境で動くルーティン**: 環境のネットワークポリシーが
  「制限付き」だと slack.com に接続できない。環境設定（入力欄上の雲アイコン → 環境の
  歯車 → Network access）で Full にするか slack.com を許可し、Environment variables に
  `SLACK_MARIN_BOT_TOKEN=xoxb-...` を登録すれば、このリポジトリの
  `scripts/notify_marin_bot.sh` がそのまま使える。

## セキュリティ

- トークンを公開リポジトリや公開の場に書かないこと（このドキュメントにも書かない）。
- 漏れた疑いがあれば Slack アプリの OAuth & Permissions で
  トークンを Rotate（再発行）する。
