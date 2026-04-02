# Hook — Copilot を「帰らせない」仕組み

v6 のアーキテクチャよりも、**この Hook が v6 を v6 たらしめている** と思っています。正直、サーバー側の変更（フラット化・N-agent 対応）は設計の話なので誰でも思いつくんですが、Hook をサーバーと連携させるアイデアが v6 の肝です。

## 何が問題だったか

Copilot は仕事が終わったと判断すると `task_complete` を呼んで停止します。指示書に「shutdown が届くまで帰るな」と書いても、セッションが長くなったりコンテキストが溢れたりすると、**勝手に帰ってしまう**。

v3 では人間が定期的に画面を監視して、止まったエージェントに手動でプロンプトを再送するという運用をしていました。週 11 時間しか PC を触れないのに、その半分を監視に使っていたのは正直バカバカしかった。

## VS Code Agent Hook とは

エージェントのライフサイクルの特定タイミングで、外部コマンドを差し込める仕組みです。コマンドは標準入力で JSON を受け取り、標準出力で JSON を返す。Python に限らず何でも書けます。

v6 で使っている Hook は 3 本:

| Hook | いつ発火 | 何をする | ファイル |
|------|---------|---------|---------|
| **Stop** | Copilot が止まろうとした瞬間 | サーバーに確認して、SHUTDOWN 以外なら阻止 | `block_stop.py` |
| **PostToolUse** | ツール実行が完了した後 | サーバーに新着メッセージがないか確認 | `check_messages.py` |
| **PreToolUse** | ツール実行の前 | ユーザーへの質問を禁止 | `block_questions.py` |

## Stop Hook: 一番大事なやつ

Copilot が `task_complete` を呼ぼうとした瞬間に発火します。ここで agent_sync サーバーに TCP で `peek` して、今の状態を確認します。

判定ロジックはこんな感じです:

```
サーバーに接続できない？ → 止まってOK（サーバーが落ちてるなら仕方ない）

phase == SHUTDOWN？ → 止まってOK

メッセージが溜まってる？ → 阻止！（何度でも。メッセージを消費するまで帰さない）

2回目の停止試行？（stop_hook_active == true）→ 止まってOK（無限ブロック防止）

1回目の停止試行？ → 阻止。「listen で次の指示を待て」と注入
```

コードの核心部分:

```python
if pending > 0:
    reason = (
        f"メールボックスに{pending}件のメッセージ。今すぐ取得:\n"
        f"  python agent_sync/client_v6.py listen {agent} ..."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "decision": "block",
            "reason": reason,
        }
    }))
```

`reason` に具体的なコマンドを書いておくのがミソで、Copilot はこれを見て自発的に `listen` を実行してくれます。「なんで止まれないの？」→「メッセージが来てるから受信しろ」という流れが自然にできる。

### stop_hook_active の話

VS Code は Stop Hook に `stop_hook_active` というフラグを渡してきます。

- `false`: 1 回目の停止試行。Hook がブロックできる
- `true`: 2 回目の停止試行（前回ブロックされた後の再試行）

v6 では **「メッセージが残っている限り何度でもブロック」「メッセージがなくて 2 回目なら解放」** というロジックにしています。無限ブロックを防ぎつつ、重要なメッセージを見逃しません。

### 指示書の再注入

Stop Hook で復帰したエージェントは、たまにコンテキストを見失います。「自分が何者で何をすべきか」を忘れるんですよね。

対策として、`.agent.md` の本文（先頭 600 文字）を `reason` に注入しています:

```python
def load_agent_body(agent: str) -> str:
    path = f".github/agents/{agent}.agent.md"
    text = open(path, encoding="utf-8").read()
    parts = text.split("---", 2)
    body = parts[2].strip()
    return body[:600]
```

これで「あ、自分は agent-a で、agent_sync のチームメンバーで、listen して待機すべきだった」と思い出してくれます。

## PostToolUse Hook: リアルタイムの新着チェック

ツールを実行するたびに発火します。サーバーに `peek` して、新着メッセージがあったら Copilot に教えます。

```python
if pending > 0:
    ctx = (
        f"🔔 [agent_sync] {pending}件の新着メッセージ "
        f"(phase={phase}, round={round_num})\n"
        f"今すぐ確認: python agent_sync/client_v6.py listen ..."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "additionalContext": ctx,
        }
    }))
```

**ただし、高頻度ツールではスキップします。** `read_file` とか `grep_search` は何十回も呼ばれるので、毎回 TCP 通信すると体感で 2-3 倍遅くなります。実際にコードを変更するツール（`run_in_terminal`, `replace_string_in_file` 等）の後だけチェックする設計にしています。

```python
SKIP_TOOLS = {
    "read_file", "grep_search", "file_search",
    "list_dir", "semantic_search", "view_image"
}
```

## PreToolUse Hook: 質問禁止

マルチエージェントで動かしているとき、エージェントがユーザーに質問して待機するのは害しかないです。人間が答えるまでエージェントが止まるし、他のエージェントとの同期が崩れる。

不明点があったら DISCUSS フェーズで相方と議論すればいいので、質問ツールは丸ごとブロックします:

```python
BLOCKED_TOOLS = {"vscode_askQuestions"}

if tool in BLOCKED_TOOLS:
    print(json.dumps({
        "hookSpecificOutput": {
            "decision": "block",
            "reason": "質問は禁止。最も合理的な仮定を立てて作業を続行せよ。",
        }
    }))
```

## .agent.md での設定

Hook は `.agent.md` の YAML フロントマターで設定します:

```yaml
---
name: "Agent-A"
description: "Flat 2-agent team member."
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
```

`env` で `AGENT_SYNC_NAME` と `AGENT_SYNC_PORT` を渡すことで、同じスクリプトを全エージェントで使い回せます。エージェントを増やすときは `.agent.md` をコピーして `AGENT_SYNC_NAME` を変えるだけです。

## 実際に効いた場面

5 ラウンドの品質改善セッションで、何度も Stop Hook が発火してエージェントの停止を阻止しました。典型パターン:

1. **Agent-A が `impl-done` を送った直後。** 「やることない」と判断して止まろうとするけど、Stop Hook が「TEST フェーズ中。listen せよ」と蹴り返す
2. **Agent-B がテスト結果を報告した直後。** DISCUSS への遷移通知が来ているのに止まろうとするけど、PostToolUse Hook が「1 件の新着メッセージ」と教える
3. **DISCUSS で相方のメッセージを待っている間。** listen がタイムアウトして「もう終わりかな」と止まろうとするけど、Stop Hook が再度 listen を指示

結果、**人間がキーボードに触れたのは、最初の指示出しと最後の SHUTDOWN だけ** でした。v3 のときの画面張り付きと比べると、完全に解放された感じです。

## ハマりポイント

### Hook の stdout は JSON じゃないとサイレントに死ぬ

`print()` デバッグを入れると JSON パースに失敗して Hook が効かなくなります。**デバッグ出力は `sys.stderr` に書くこと。** これで 3 時間溶かしました。

### タイムアウトは余裕を持つ

Stop Hook を短くしすぎると TCP 通信が間に合わなくてエージェントが止まります。10 秒あれば往復に十分余裕があります。PostToolUse は頻繁に呼ばれるので 5 秒に絞っています。

### Hook でブロックするたびに CP を消費する

Hook でブロックすると Copilot は reason を読んで次のアクションを考えるので、プレミアムリクエストを消費します。無駄にブロックし続けると CP がどんどん減るので、`stop_hook_active` での 2 段階制御はコスト節約の意味もあります。

### peek と listen を間違えない

Hook 内で `listen`（ブロッキング）を呼ぶとタイムアウトまで固まります。Hook では必ず `peek`（非ブロッキング）を使うこと。
