# agent_sync — GitHub Copilot マルチエージェント協調 CLI

自作 TCP サーバーで複数の GitHub Copilot エージェントを連携させるツール。

VS Code のチャットタブを複数開き、各タブの Copilot に別の役割を与えて並列に動かす。サーバーがメッセージング・フェーズ同期・議論ループを管理する。

## セットアップ

```bash
git clone https://github.com/RPG-478/agent_sync.git
cd agent_sync
```

**依存ライブラリなし。** Python 3.10+ の標準ライブラリだけで動きます。

## クイックスタート

### 1. サーバー起動

```powershell
python -m agent_sync server --port 9800
```

### 2. Copilot タブに役割を渡す

`instructions/` フォルダに各エージェント用の指示書（Markdown）を置いて、各タブの Copilot にこう伝えます：

**オーケストレーター（タブ 0）：**
```
あなたはオーケストレーターです。
instructions/00_orchestrator.md を読んで指示に従ってください。
全エージェントの参加を確認したら set-phase IMPLEMENT でフェーズを開始してください。
```

**専門エージェント（タブ 1〜N）：**
```
あなたの名前は PromptForge です。
instructions/01_prompt_forge.md を読んで指示に従ってください。
まず以下を実行してサーバーに参加してください:

python -m agent_sync join PromptForge
git checkout -b agent/prompt-forge
python -m agent_sync set-branch PromptForge agent/prompt-forge

実装が終わったら:
git add -A && git commit -m "PromptForge: <概要>"
python -m agent_sync merge-request PromptForge --branch agent/prompt-forge --message "<概要>"

その後 listen で待機してください。shutdown が届くまで帰らないでください。
```

### 3. 進捗確認

```powershell
python -m agent_sync status
```

## フェーズ管理

```
IMPLEMENT → MERGE → TEST → DISCUSS → IMPLEMENT に戻る or SHUTDOWN
```

| フェーズ | 内容 |
|---------|------|
| IMPLEMENT | 各エージェントがブランチで実装。完了したら `merge-request` |
| MERGE | オーケストレーターが全ブランチをマージ |
| TEST | オーケストレーターがテスト実行 |
| DISCUSS | テスト失敗時に全員で議論 → `propose` で修正案提出 |
| SHUTDOWN | 全目標達成。全エージェントに終了通知 |

## CLI コマンド一覧

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

### タスク管理

| コマンド | 説明 |
|---------|------|
| `add-task <タスクID> --description "..."` | タスクをキューに追加 |
| `wait-task <名前> --timeout 600` | タスク割り当てまでブロック |
| `done-task <名前> --message "..."` | タスク完了を報告 |
| `heartbeat <名前>` | 生存通知 |

### ワークフロー

| コマンド | 説明 |
|---------|------|
| `set-branch <名前> <ブランチ>` | 作業ブランチを宣言 |
| `merge-request <名前> --branch ... --message ...` | 実装完了の申告 |
| `set-phase <IMPLEMENT\|MERGE\|TEST\|DISCUSS\|SHUTDOWN>` | フェーズ切り替え |
| `wait-phase <名前> <フェーズ> --timeout 600` | 指定フェーズまでブロック |
| `test-result --passed / --failed --output ... --failures ...` | テスト結果の報告 |

### 議論

| コマンド | 説明 |
|---------|------|
| `discuss <名前> <テキスト>` | 議論に参加 |
| `propose <名前> <テキスト>` | 修正案を提出 |
| `approve <提案ID>` | 提案を承認 |
| `reject <提案ID> --reason "..."` | 提案を却下 |
| `get-discussion --round N` | 議論ログ取得 |
| `shutdown --reason "完了"` | 全エージェント終了 |

## 指示書の書き方

`instructions/` フォルダに Markdown を置きます。最低限必要なのは：

```markdown
# エージェント名

## 担当ファイル
- path/to/file1.py
- path/to/file2.py

## やること
- 具体的な変更内容1
- 具体的な変更内容2

## 完了条件
- テストが通ること
- 既存の機能を壊していないこと
```

**コツ:** ファイルパス・変更内容・完了条件を具体的に書く。実装方法は指定しない。

## プロトコル

改行区切りの JSON over TCP。

```json
→ {"cmd": "join", "agent": "PromptForge"}
← {"ok": true, "message": "Joined as PromptForge"}

→ {"cmd": "listen", "agent": "PromptForge", "timeout": 600}
← {"ok": true, "messages": [{"from": "Guardian", "text": "...", "ts": 1234}]}
```

## 詳しい解説

Zenn 記事: https://zenn.dev/midomo/articles/40cd64af2d617a

## License

MIT
