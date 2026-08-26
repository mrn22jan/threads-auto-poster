# マリン秘書bot — Slack 通知の送信元を bot にする仕組み

## 背景

Claude のルーティン（定期タスク）からの Slack 通知は、Slack コネクタ（MCP）経由だと
**本人のアカウントからの投稿**になってしまい、自分の投稿には Slack の通知が鳴らない。

これを解決するため、専用の Slack アプリ **「マリン秘書bot」** を作り、
すべてのルーティン通知をこの bot から投稿する。bot からの投稿なら通常のメッセージと
同じように通知が届く。

## 初回セットアップ（1回だけ・約5分）

1. https://api.slack.com/apps → **Create New App** → **From scratch**
   - App Name: `マリン秘書bot`
   - Workspace: `tatsumiplanning`
2. 左メニュー **OAuth & Permissions** → **Bot Token Scopes** に以下を追加:
   - `chat:write`
   - `chat:write.public`（公開チャンネルに招待なしで投稿するため）
3. 左メニュー **Basic Information** → **Display Information** でアイコンと名前を設定
4. ページ上部の **Install to Workspace** で承認 →
   **OAuth & Permissions** に表示される **Bot User OAuth Token**（`xoxb-` で始まる）をコピー
5. トークンを Claude Code の実行環境の環境変数に登録:
   - claude.ai/code → 環境（Environment）の設定 → Environment variables に
     `SLACK_MARIN_BOT_TOKEN = xoxb-...` を追加
6. 非公開チャンネル（例: #kondate-memo）に投稿させたい場合は、そのチャンネルで
   `/invite @マリン秘書bot` を実行しておく

## ルーティンからの使い方

各ルーティンのプロンプトで、Slack コネクタでの送信の代わりに以下を指示する:

```
Slack への通知は Slack コネクタ（MCP）を使わず、必ず「マリン秘書bot」として送ること。
環境変数 SLACK_MARIN_BOT_TOKEN を使い、次の curl で chat.postMessage を呼ぶ:

curl -sS -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $SLACK_MARIN_BOT_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data '{"channel": "#チャンネル名", "text": "通知本文"}'

レスポンスの "ok": true を確認すること。
```

このリポジトリを clone しているセッションなら、ヘルパースクリプトも使える:

```bash
./scripts/notify_marin_bot.sh "#たらこ日次パフォーマンス" "本日のレポートです..."
```

## 補足

- 装飾は Slack の mrkdwn（`*太字*`、`> 引用` など）が使える。`text` に含めればよい。
- トークンはプロンプトに直接書かず、必ず環境変数で渡す。
- Cowork（デスクトップ）のスケジュールタスクなど別環境で動くルーティンにも、
  同じ curl スニペット＋トークンを環境変数か指示文で渡せば同様に使える。
