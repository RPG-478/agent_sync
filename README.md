# agent_sync — GitHub Copilot マルチエージェント協調ツール

VS Code の複数タブで GitHub Copilot エージェントを並列に動かし、TCP サーバー経由で連携させるためのツールです。

## 全体像

```
┌───────────────────────────────────────────────────────────────┐
│              agent_sync server (TCP :9800)                     │
│    タスクキュー / フェーズ同期 / メッセージ / 議論ログ              │
└──┬───────┬───────┬───────┬──────┬───────┬─────────────────────┘
   │       │       │       │      │       │
 Copilot  Copilot Copilot Copilot Copilot Copilot
  タブ0    タブ1   タブ2   タブ3   タブ4   タブ5
 Orche-   Agent   Agent   Agent   Agent   Agent
 strator    A       B       C       D       E
```

オーケストレーター 1体 + 専門エージェント N体 が、各自のブランチで実装 → マージ → テスト → 失敗したら議論して修正、というサイクルを自律的に回します。

## 必要なもの

- Python 3.12+
- VS Code + GitHub Copilot
- 外部ライブラリ不要（標準ライブラリのみ）

## インストール

```bash
git clone https://github.com/RPG-478/agent_sync.git
cd agent_sync
```

パッケージとして使う場合:

```bash
pip install -e .
```

または、プロジェクトのサブディレクトリとしてコピーするだけでも動きます。

## クイックスタート（5分）

### 1. サーバー起動

```powershell
python -m agent_sync server --port 9800
```

### 2. 各タブの Copilot に役割を伝える

**タブ 0（オーケストレーター）:**

```
あなたはオーケストレーターです。
まず python -m agent_sync server --port 9800 でサーバーを起動してください。
全エージェントの参加を確認したら set-phase IMPLEMENT でフェーズを開始してください。
全 merge-request が揃ったらマージ → テスト → 議論ループを回してください。
```

**タブ 1〜N（専門エージェント）:**

```
あなたの名前は AgentA です。
まず以下を実行してサーバーに参加してください:

python -m agent_sync join AgentA
git checkout -b agent/agent-a
python -m agent_sync set-branch AgentA agent/agent-a

[ここにタスクの説明を書く]

実装が終わったら:
git add -A && git commit -m "AgentA: <概要>"
python -m agent_sync merge-request AgentA --branch agent/agent-a --message "<概要>"

その後 listen で待機してください。shutdown が届くまで帰らないでください。
```

### 3. 進捗確認

```powershell
python -m agent_sync status
```

## ワークフロー

```
IMPLEMENT → MERGE → TEST → DISCUSS → IMPLEMENT に戻る
                      ↓
                   SHUTDOWN（テスト成功時）
```

| フェーズ | 内容 |
|---------|------|
| **IMPLEMENT** | 各エージェントがブランチで実装 → `merge-request` |
| **MERGE** | オーケストレーターが全ブランチをマージ |
| **TEST** | オーケストレーターが `pytest` を実行 |
| **DISCUSS** | テスト失敗 → 全員で議論 → `propose` で修正案を提出 |
| **SHUTDOWN** | テスト成功 → 全エージェントに終了通知 |

## CLI コマンド一覧

すべて `python -m agent_sync <command>` で実行します。

### 基本

| コマンド | 説明 |
|---------|------|
| `server --port 9800` | サーバー起動 |
| `join <名前>` | サーバーに登録 |
| `status` | 全エージェントの状態確認 |
| `listen <名前> --timeout 600` | メッセージ待ち（ブロック） |
| `send <送信元> <宛先> <メッセージ>` | DM 送信 |
| `broadcast <送信元> <メッセージ>` | 全員に通知 |
| `barrier <ID> <名前> --expected N` | 全員揃うまで待機 |
| `heartbeat <名前>` | ハートビート送信 |

### タスク管理

| コマンド | 説明 |
|---------|------|
| `add-task <ID> --description "..."` | タスクをキューに追加 |
| `wait-task <名前> --timeout 600` | タスクが割り当てられるまで待機 |
| `done-task <名前> --message "..."` | タスク完了報告 |

### ブランチ・フェーズ管理

| コマンド | 説明 |
|---------|------|
| `set-branch <名前> <ブランチ>` | 作業ブランチ宣言 |
| `merge-request <名前> --branch ... --message ...` | マージリクエスト |
| `set-phase <IMPLEMENT\|MERGE\|TEST\|DISCUSS\|SHUTDOWN>` | フェーズ切り替え |
| `wait-phase <名前> <フェーズ> --timeout 600` | 特定フェーズまで待機 |
| `test-result --passed/--failed --output ... --failures ...` | テスト結果報告 |

### 議論

| コマンド | 説明 |
|---------|------|
| `discuss <名前> <テキスト>` | 議論に参加 |
| `propose <名前> <テキスト>` | 修正案を提出 |
| `approve <提案ID>` | 提案を承認 |
| `reject <提案ID> --reason "..."` | 提案を却下 |
| `get-discussion --round N` | 議論ログ取得 |
| `shutdown --reason "..."` | 全エージェント終了 |

## 指示書の書き方

`instructions/` フォルダにサンプルがあります。

ポイント:
- **担当ファイル**: 具体的なパスを列挙
- **やること**: 変更内容を箇条書き
- **完了条件**: テストが通る、特定の機能が動く、等
- **実装方法は指定しない**: Copilot の自律性に任せる

## プロトコル

改行区切りの JSON over TCP。

```json
// リクエスト
{"cmd": "join", "agent": "AgentA"}

// レスポンス
{"ok": true, "message": "Joined as AgentA"}
```

## 設計判断

- **TCP (not HTTP/WebSocket)**: Copilot が CLI でそのまま叩ける
- **永続化なし**: 1セッション（数時間）で完結する前提
- **外部ライブラリゼロ**: Python 標準ライブラリのみ
- **localhost 限定**: ネットワーク越しの利用は想定外

## ライセンス

MIT
