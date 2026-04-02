# CLI リファレンス

`client_v6.py` の全コマンドまとめです。全部 `python agent_sync/client_v6.py <command>` で叩けます。

:::message
ほとんどのコマンドは Copilot が自動的に叩くものなので、人間が使うのは `status`, `say`, `shutdown`, `set-phase` くらいです。
:::

## 接続系

### join — サーバーに参加

```bash
python agent_sync/client_v6.py join <agent> [--port 9800]
```

`AGENTS_LIST` に含まれるエージェント名じゃないと拒否されます。

### status — 全体状態の確認

```bash
python agent_sync/client_v6.py status [--port 9800]
```

人間が一番使うコマンド。今のフェーズ、ラウンド、各エージェントの状態がわかります。

```json
{
  "data": {
    "phase": "IMPLEMENT",
    "round": 3,
    "agents": {
      "agent-a": {"status": "idle", "joined_at": 1234567890.0},
      "agent-b": {"status": "idle", "joined_at": 1234567891.0}
    },
    "implementer": "agent-a"
  }
}
```

### heartbeat — 生存通知

```bash
python agent_sync/client_v6.py heartbeat <agent> [--port 9800]
```

`last_heartbeat` を更新するだけです。

---

## メッセージング

### listen — メッセージ待機（ブロッキング）

```bash
python agent_sync/client_v6.py listen <agent> [--timeout 300] [--port 9800]
```

メッセージが届くかタイムアウトするまで待ちます。**エージェントが一番多く使うコマンド。** フェーズ遷移の通知も議論メッセージもこれで受け取ります。

```json
{
  "messages": [
    {"from": "__server__", "type": "phase_change", "text": "Phase changed: IMPLEMENT -> TEST (round 3)"},
    {"from": "agent-b", "type": "discuss", "text": "stub検出のしきい値30%で同意"}
  ]
}
```

タイムアウトした場合:

```json
{"messages": [], "timeout": true}
```

### peek — 新着チェック（非ブロッキング）

```bash
python agent_sync/client_v6.py peek <agent> [--port 9800]
```

メッセージがあるか確認するだけで、消費はしません。Hook から使うのはこちらで、`listen` を Hook 内で呼ぶとタイムアウトまで固まってしまうので、Hook 内では必ず `peek` を使ってください。

### send — 特定エージェントに送信

```bash
python agent_sync/client_v6.py send <from> <to> "<message>" [--port 9800]
```

### broadcast — 全員に送信

```bash
python agent_sync/client_v6.py broadcast <from> "<message>" [--port 9800]
```

送信者自身には届きません。

### say — 人間からの介入

```bash
# 全員に
python agent_sync/client_v6.py say "次のラウンドでUIテストを追加して" [--port 9800]

# 特定エージェントに
python agent_sync/client_v6.py say "テスト対象を絞って" --to agent-b [--port 9800]
```

人間が途中で指示を追加したいときに使います。`--to` を省略すると全員に送信されます。

---

## フェーズ制御

### impl-done — 実装完了を宣言

```bash
python agent_sync/client_v6.py impl-done <agent> [--summary "変更内容の要約"] [--port 9800]
```

IMPLEMENT → TEST に遷移します。**implementer 以外が呼ぶとエラーになります。**

### test-result — テスト結果の報告

```bash
# 成功
python agent_sync/client_v6.py test-result <agent> --passed [--output "258 passed"] [--port 9800]

# 失敗
python agent_sync/client_v6.py test-result <agent> [--output "失敗ログ"] [--failures test_xxx test_yyy] [--port 9800]
```

TEST → DISCUSS に遷移します。

### discuss — 議論メッセージ

```bash
python agent_sync/client_v6.py discuss <agent> "<意見>" [--port 9800]
```

DISCUSS フェーズ中のみ有効で、相手のメールボックスに配信されます。

### discuss-done — 議論完了の宣言

```bash
python agent_sync/client_v6.py discuss-done <agent> [--next-impl agent-b] [--port 9800]
```

全員が `discuss-done` を送ると次ラウンドの IMPLEMENT に遷移します。`--next-impl` で次の implementer を指定できます。

### get-discussion — 議論ログの取得

```bash
python agent_sync/client_v6.py get-discussion [--round 3] [--port 9800]
```

`--round` で特定ラウンドに絞れます。

### set-phase — フェーズ強制変更

```bash
python agent_sync/client_v6.py set-phase <IMPLEMENT|TEST|DISCUSS|SHUTDOWN> [--port 9800]
```

デバッグ用・緊急時用。普段は使わないです。

### shutdown — 全員停止

```bash
python agent_sync/client_v6.py shutdown [--reason "完了"] [--port 9800]
```

SHUTDOWN フェーズに遷移して、全エージェントに終了通知を送ります。

---

## ログ

### write-log — ラウンドログに追記

```bash
python agent_sync/client_v6.py write-log <agent> "<テキスト>" [--section "IMPL_DONE"] [--port 9800]
```

`logs/v6/round_{N}.md` に保存されます。

---

## 通知（notifier 連携）

### check-notify — 通知の確認

```bash
python agent_sync/client_v6.py check-notify <agent>
```

バックグラウンドの notifier が書き込んだ通知を読みます。サーバーは経由しません。

### clear-notify — 通知のクリア

```bash
python agent_sync/client_v6.py clear-notify <agent>
```

---

## サーバーとモニター

### サーバー起動

```bash
python agent_sync/server_v6.py [--port 9800]
```

3 体以上で動かす場合は `AGENTS_LIST` 環境変数を設定:

```powershell
$env:AGENTS_LIST = "agent-a,agent-b,agent-c"
python agent_sync/server_v6.py --port 9800
```

### モニター

```bash
python agent_sync/monitor.py [--port 9800] [--interval 2]
```

2 秒ごとにサーバーに `status` + `peek` を投げて、ターミナルにライブダッシュボードを表示します。エージェントが何をしているかリアルタイムで見えるので、最初のうちは起動しておくと安心。
