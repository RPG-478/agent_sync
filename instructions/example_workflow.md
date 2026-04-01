# エージェント共通ワークフロー（サンプル）

## あなたの立場

あなたは専門エージェントです。
全体のテストが通り、オーケストレーターが `shutdown` を発行するまで **絶対に** 稼働し続けてください。

## フェーズ一覧

| フェーズ | やること |
|---------|--------|
| **IMPLEMENT** | ブランチで実装 → 完了したら `merge-request` → `listen` で待機 |
| **MERGE** | 待機（オーケストレーターがマージ中） |
| **TEST** | 待機（オーケストレーターがテスト中） |
| **DISCUSS** | テスト結果を読み、`discuss` で意見 / `propose` で修正案を提出 |
| **SHUTDOWN** | 終了してよい |

## 手順

### IMPLEMENT フェーズ

```powershell
# ブランチ作成（初回のみ）
git checkout main
git checkout -b agent/<your_name>
python -m agent_sync set-branch <YOUR_NAME> agent/<your_name>

# 実装...

# 完了
git add -A
git commit -m "<概要>"
python -m agent_sync merge-request <YOUR_NAME> --branch agent/<your_name> --message "<概要>"

# 待機（帰るな）
python -m agent_sync listen <YOUR_NAME> --timeout 900
```

### DISCUSS フェーズ

```powershell
# 議論に参加
python -m agent_sync discuss <YOUR_NAME> "問題の原因は〇〇だと思う"

# 修正案を提出
python -m agent_sync propose <YOUR_NAME> "〇〇を修正する"

# 承認を待つ
python -m agent_sync listen <YOUR_NAME> --timeout 900
```

## 重要ルール

1. **merge-request を出す前に必ず git commit**
2. **merge-request 後は自分のブランチで待機** — main を直接触らない
3. **shutdown が届くまで帰らない**
