# context-stat

AIへの入力に含めるファイル、コマンド結果、Git差分、MCPの内容をローカルで計測するCLIです。

## インストール

GitHubリポジトリから直接導入する場合は、次を実行します。

```text
uv tool install git+https://github.com/n-kats/context-stat
```

`tokenizers`バックエンドもGitHubから導入する場合は、extraを指定します。

```text
uv tool install "context-stat[tokenizers] @ git+https://github.com/n-kats/context-stat"
```

開発中のチェックアウトから導入する場合は、次を使います。

```text
uv tool install .
```

`tokenizers`バックエンドを使う場合だけ追加します。

```text
uv tool install ".[tokenizers]"
```

## 基本操作

```text
context-stat stat path/to/file
context-stat stat path/to/directory
context-stat stat -
context-stat jinja template.j2 --params '{"name":"Ada"}'
context-stat git diff HEAD -- src/
context-stat mcp list --config mcp.json
context-stat -v mcp request --config mcp.json --method tools/call --name echo --params '{"message":"hello"}'
context-stat mcp list --codex-config ~/.codex/config.toml --server docs
context-stat mcp list --url https://example.test/mcp
context-stat completions bash
```

共通オプションはサブコマンドより前に置きます。Gitの引数は`--`を含めてGit差分専用パーサーが解釈します。

```text
context-stat --format json --metrics all --sort tokens --order desc git diff HEAD -- src/
```

## 主なオプション

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--format` | `table` | `table`、`tree`、`json` |
| `--metrics` | `token` | 計測項目。`all`またはカンマ区切り |
| `--sort` | `path` | `path`、`tokens`、`bytes`など |
| `--order` | `asc` | `asc`または`desc` |
| `-p`、`--parallel` | `1` | `stat`のワーカー数。`0`はCPU数 |
| `-v`、`--verbose` | オフ | MCP返却結果本文を表示 |
| `--backend` | `auto` | 現在は`tiktoken`を選択 |
| `--text-tokenizer` | `o200k_base` | テキスト方式 |
| `--image-tokenizer` | `gpt-5.6-style` | 画像方式 |

`stat`固有の`--include-images`、`--ignore-gitignore`、`--command`、`--timeout`、`--max-output-bytes`は`stat`の後に置きます。

## 動作上の注意

- ディレクトリは再帰的に走査し、既定では`.gitignore`を反映します。`--ignore-gitignore`で無視できます。
- 直接指定したファイルは`.gitignore`に関係なく対象です。非画像バイナリはスキップします。
- 画像は直接指定なら対象です。ディレクトリでは`--include-images`を指定します。
- ディレクトリの合計はディレクトリ行に表示し、`TOTAL`行は出しません。
- `git diff`は変更ファイルごとのpatchを計測します。`--no-patch`などpatchを生成しない指定は拒否します。
- 警告とエラーの診断は標準エラーへまとめ、標準出力には計測結果を出します。
- `mcp request`は通常、計測表と結果状態だけを表示します。`-v`/`--verbose`を指定した場合だけ、表の外側にMCPから返った結果本文を表示します。画像のBase64は表示せず、MIME typeと幅・高さへ置き換えます。
- `--allow-online`はオンライン型トークンバックエンドの許可だけに使い、MCPとは関係しません。現行の標準バックエンドは外部送信しません。
- MCPは`--config FILE`、Codexの`--codex-config FILE`、またはStreamable HTTPの`--url URL`で接続できます。Codex設定に複数の有効なサーバーがある場合は`--server NAME`で選択します。認証ヘッダーは`--header-from-env HEADER=ENV`またはCodex設定のヘッダー指定から読み込みます。

## ドキュメント

- [docs/README.md](docs/README.md): 文書の入口
- [手順](docs/手順/context-statを使う.md): 用途別の使い方
- [仕様](docs/仕様/context-stat機能仕様.md): 現行仕様
- [現状](docs/現状/context-statの現状.md): 未完了事項、仕様との差分、直近の検証結果
- [設計](docs/設計/context-stat設計.md): 実装設計
- [設計判断](docs/設計判断/決定事項.md): 決定事項
- [目次](docs/目次.md): 文書と実装ファイルの一覧

## 開発

```text
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv lock --check
uv tool install .
```
