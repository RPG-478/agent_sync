# クイックスタート

ゼロから agent_sync v6 を動かすまでの手順です。自分がやったときは 10 分くらいで動きました。

## 前提

- **VS Code** がインストールされている
- **GitHub Copilot** が有効（Pro 以上を推奨。Free だとリクエスト上限に引っかかる可能性あり）
- **Python 3.10+** がインストールされている

:::message
2 体で 5 ラウンド回すと数百リクエスト消費します。Free/Pro だと途中で止まることがあるので、本気で使うなら Pro+ をおすすめします。
:::

## 1. ファイルを配置

既存プロジェクトにコピーするなら、こんな構成になります:

```
your-project/
├── agent_sync/
│   ├── server_v6.py
│   ├── client_v6.py
│   ├── monitor.py
│   └── notifier.py
└── .github/
    ├── agents/
    │   ├── agent-a.agent.md
    │   └── agent-b.agent.md
    └── hooks/
        ├── block_stop.py
        ├── check_messages.py
        └── block_questions.py
```

## 2. .agent.md を作成

`.github/agents/` に各エージェントの定義ファイルを置きます。

### agent-a.agent.md の例

```yaml
---
name: "Agent-A"
description: "Flat 2-agent team member. No hierarchy — equal peer to Agent-B."
tools:
  - run_in_terminal
  - edit
  - search
  - read_file
  - list_dir
  - create_file
  - replace_string_in_file
  - multi_replace_string_in_file
  - get_errors
  - file_search
  - grep_search
  - semantic_search
  - fetch_webpage
  - manage_todo_list
  - memory
hooks:
  Stop:
    - type: command
      command: "python .github/hooks/block_stop.py"
      env:
        AGENT_SYNC_NAME: "agent-a"
        AGENT_SYNC_PORT: "9800"
      timeout: 10
  PostToolUse:
    - type: command
      command: "python .github/hooks/check_messages.py"
      env:
        AGENT_SYNC_NAME: "agent-a"
        AGENT_SYNC_PORT: "9800"
      timeout: 5
  PreToolUse:
    - type: command
      command: "python .github/hooks/block_questions.py"
      timeout: 3
---

# Agent-A — agent_sync v6 フラットチームメンバー

## 🚨 停止禁止

- あなたは agent_sync 協調システムの一員。**自分からタスク完了を宣言して停止してはいけない**。
- 常に `python agent_sync/client_v6.py listen agent-a --timeout 30 --port 9800` で次の指示を待つ。
- SHUTDOWN フェーズでのみ停止を許可。

## フェーズサイクル

IMPLEMENT → TEST → DISCUSS → IMPLEMENT (round+1)

### IMPLEMENT
- `status` で自分が implementer か確認
- implementer なら実装、そうでなければ listen で待機
- 完了: `impl-done agent-a --summary "要約"`

### TEST
- implementer でない方がテスト実行
- 結果報告: `test-result agent-a --passed`

### DISCUSS
- 議論: `discuss agent-a "意見"`
- 合意: `discuss-done agent-a`
```

Agent-B も同じ要領で作ります。`agent-a` を `agent-b` に置換するだけです。

## 3. サーバーを起動

```powershell
python agent_sync/server_v6.py --port 9800
```

3 体以上で動かす場合:

```powershell
$env:AGENTS_LIST = "agent-a,agent-b,agent-c"
python agent_sync/server_v6.py --port 9800
```

## 4. VS Code でエージェントを起動

### タブ 1: Agent-A

1. VS Code でチャットパネルを開く
2. `@Agent-A` と入力してエージェントを呼び出す
3. 指示を出す:

```
サーバーに join して、以下のタスクを実装してください:
- <具体的な実装内容>

まず python agent_sync/client_v6.py join agent-a --port 9800 で参加してください。
```

### タブ 2: Agent-B

別のチャットタブで:

```
サーバーに join して、Agent-A の実装をテスト・レビューしてください。

まず python agent_sync/client_v6.py join agent-b --port 9800 で参加してください。
```

あとは放置です。Hook が勝手に面倒を見てくれます。

## 5. モニターで確認（任意）

別のターミナルで:

```powershell
python agent_sync/monitor.py --port 9800
```

こんな感じのダッシュボードが出ます:

```
════════════════════════════════════════════════════
  agent_sync v6 — Live Monitor
════════════════════════════════════════════════════
  🔨 Phase: IMPLEMENT   Round: 1   Implementer: agent-a
────────────────────────────────────────────────────
  Agents:
    agent-a  📭 0 pending
    agent-b  📭 0 pending
────────────────────────────────────────────────────
  💬 Discussion (last 10):
    (no discussion yet)
────────────────────────────────────────────────────
```

最初のうちは起動しておくとどう動いてるか見えて安心です。慣れたらなくても大丈夫。

## 6. 途中で介入したくなったら

### 全員にメッセージを送る

```bash
python agent_sync/client_v6.py say "次のラウンドでパフォーマンステストも追加して"
```

### 特定エージェントに送る

```bash
python agent_sync/client_v6.py say "テスト範囲を広げて" --to agent-b
```

### 強制終了

```bash
python agent_sync/client_v6.py shutdown --reason "手動終了"
```

## 典型的な流れ

```
[人間] サーバー起動 + 2つのタブで Agent-A/B に指示
  ↓
[Agent-A] join → 実装開始
[Agent-B] join → listen で待機
  ↓
[Agent-A] impl-done → TEST フェーズへ
  ↓
[Agent-B] PostToolUse Hook で通知検知 → テスト実行 → test-result
  ↓
[Agent-A & B] DISCUSS で議論 → discuss-done
  ↓
（Round 2, 3, ... 繰り返し）
  ↓
[Agent-A or B] shutdown → 全員停止
[人間] 成果物を確認
```

## Tips

- **指示は具体的に。** 「品質を上げて」じゃなくて「sandbox_executor.py にスタブ検出を追加して。stub 率 > 30% なら FAIL」くらい書く
- **テストを用意しておく。** pytest で回せるテストがあると TEST フェーズが自動化できる
- **DISCUSS はサボらせない。** 指示書に「DISCUSS では必ず次ラウンドの方針を提案すること」と書いておくと、議論の質が上がる
- **最初は 2 体で。** いきなりたくさん動かすとカオスになるので、まずは 2 体で 1-2 ラウンド試すのがおすすめ
