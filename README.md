# agent_sync — GitHub Copilot マルチエージェント協調 CLI

自作 TCP サーバーで **GitHub Copilot を N体並列に動かして、勝手に協調させる**仕組みです。

v3 ではオーケストレーター 1体 + 専門エージェント 5体の構成で動かしていましたが、**Copilot が勝手に止まる問題**がどうしても解決できず、人間が画面に張り付く運用になっていました。v6 では VS Code の Agent Hook を使って、この問題を根本的に潰しています。Hook 3本（合計 100行ちょっと）でエージェントが勝手にサーバーと同期し続ける仕組みができて、人間は最初に指示を出したら SHUTDOWN まで放置できるようになりました。

## v3 → v6 で何が変わった？

| | v3 | v6 |
|---|---|---|
| 構成 | オーケストレーター 1 + 専門 5 | **全員フラット（対等）** |
| ブランチ | エージェントごとに別ブランチ | **同一ブランチ** |
| マージ | オーケストレーターが手動マージ | **不要** |
| Copilot が勝手に止まる | 人間が監視して手動再送 | **Stop Hook で自動阻止** |
| メッセージ検知 | listen のタイムアウト待ち | **PostToolUse Hook で即時通知** |
| エージェント数 | 固定 6体 | **N体（環境変数で変更可）** |

## ファイル構成

```
agent_sync/
├── server_v6.py        # TCP サーバー（フェーズ管理・メッセージキュー）
├── client_v6.py        # CLI クライアント（Copilot がターミナルで叩く）
├── monitor.py          # ライブダッシュボード（人間が眺める用）
├── notifier.py         # バックグラウンド通知ウォッチャー
├── docs/               # ドキュメント
├── hooks/              # VS Code Agent Hook スクリプト
├── examples/           # .agent.md テンプレート
└── tests/              # テスト

# v3 のファイル（レガシー）
├── server.py           # v3 サーバー
├── client.py           # v3 クライアント
└── instructions/       # v3 用の指示書テンプレート
```

## セットアップ

```bash
git clone https://github.com/RPG-478/agent_sync.git
cd agent_sync
```

**依存ライブラリなし。** Python 3.10+ の標準ライブラリだけで動きます。

## とりあえず動かしたい人

→ [docs/QUICKSTART.md](docs/QUICKSTART.md)

## ドキュメント

| ファイル | 内容 |
|---------|------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | ゼロから動かすまでの手順 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | なぜこの設計にしたか、フェーズの流れ、プロトコル |
| [docs/HOOKS.md](docs/HOOKS.md) | Hook 3本の仕組みと「なぜ必要か」 |
| [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) | 全コマンドの使い方 |

## バージョンの変遷

| Version | 構成 | 一言 |
|---------|------|------|
| v3 | 6体（オーケストレーター1 + 専門5） | 動いたけど、オーケストレーターが単一障害点 |
| v4 | 3体（コンダクター1 + エンジニア2） | v3 の軽量版。まだコンダクター依存 |
| v5 | 2体（コンダクター1 + エンジニア1） | さらに絞った。でもまだ止まる |
| **v6** | **N体（全員フラット）** | **Hook で止まらない。オーケストレーター不要。完成形** |

## 関連記事

- [Zenn: 6体の Copilot を自作サーバーで協調させた話（v3）](https://zenn.dev/midomo/articles/40cd64af2d617a)

## v3 について

v3 のファイル（`server.py`, `client.py`, `instructions/`）はレガシーとしてそのまま残してあります。v3 の使い方は上の Zenn 記事を参照してください。

## 必要なもの

- VS Code + GitHub Copilot（Pro 以上推奨。Free だとリクエスト制限に引っかかります）
- Python 3.10+

## ライセンス

MIT