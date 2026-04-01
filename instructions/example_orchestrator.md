# オーケストレーター 手順書（サンプル）

## 役割
- サーバー起動
- ブランチまとめ（merge）
- テスト実行（pytest）
- 品質判定
- 全エージェントへの指示・DISCUSS 進行
- SHUTDOWN 判断

## 起動手順

### 1. サーバー起動
```powershell
python -m agent_sync server --port 9800
```

### 2. エージェント参加待ち
```powershell
python -m agent_sync status
# agents に全員いることを確認
```

### 3. タスク投入 + IMPLEMENT
```powershell
python -m agent_sync add-task T1 --description "機能A — instructions/01_agent_a.md"
python -m agent_sync add-task T2 --description "機能B — instructions/02_agent_b.md"
python -m agent_sync set-phase IMPLEMENT
```

## ループ手順

### MERGE（全 merge-request 受信後）
```powershell
python -m agent_sync set-phase MERGE
git checkout main
git merge agent/agent-a --no-edit
git merge agent/agent-b --no-edit
```

### TEST
```powershell
python -m agent_sync set-phase TEST
python -m pytest tests/ -v
# 結果を報告
python -m agent_sync test-result --passed --output "All tests passed"
# or
python -m agent_sync test-result --failed --output "2 failures" --failures "test_x" "test_y"
```

### DISCUSS（テスト失敗時）
```powershell
python -m agent_sync set-phase DISCUSS
# 議論ログ確認
python -m agent_sync get-discussion
# 提案を承認
python -m agent_sync approve P1
# → set-phase IMPLEMENT で次ラウンドへ
```

### SHUTDOWN（テスト成功時）
```powershell
python -m agent_sync shutdown --reason "All tests passed"
```
