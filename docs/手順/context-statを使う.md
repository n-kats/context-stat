# context-statを使う

## 導入

```text
uv tool install .
```

`tokenizers`を使う場合だけ追加します。

```text
uv tool install ".[tokenizers]"
```

## ファイルとディレクトリ

```text
context-stat stat README.md
context-stat stat src/
context-stat --format tree --metrics all stat src/
context-stat --format json --sort tokens --order desc stat src/
```

ディレクトリは再帰的に走査します。既定では`.gitignore`を反映し、`--ignore-gitignore`で無視できます。画像を含める場合は`--include-images`を付けます。直接指定した画像は対象になります。

標準入力は`-`です。

```text
printf 'hello\n' | context-stat stat -
```

## 計測と並列実行

```text
context-stat --metrics all stat src/
context-stat --sort tokens --order desc stat src/
context-stat -p 4 stat src/
```

`--sort`を省略した場合はパス順です。`table`、`tree`、`json`は同じ順序を使います。ディレクトリの合計はディレクトリ自身の行に表示し、`TOTAL`行は出しません。

## ファイルごとのコマンド結果

`--command`は各ファイルのパスを`{{path}}`へ渡します。標準出力を計測し、標準エラー、終了状態、タイムアウト、出力切り詰めは診断として扱います。

```text
context-stat stat src/ --command 'cat "{{path}}"'
context-stat stat src/ --command 'cat "{{path}}"' --timeout 5 --max-output-bytes 100000
```

シェルは起動しません。パイプやリダイレクトが必要な場合は、実行するプログラムへ引数として渡してください。

## Jinja

テンプレートをレンダリングした結果だけを計測します。

```text
context-stat jinja prompt.j2 --params '{"name":"Ada"}'
```

## Git差分

Gitの引数は`git diff`と同じ形で指定し、`--`以降をpathspecにします。共通オプションはGitコマンドより前に置きます。

```text
context-stat --format json git diff HEAD -- src/
context-stat --metrics all git diff main HEAD -- README.md
```

差分は変更ファイルごとのpatchとして計測します。`--no-patch`、`--name-only`、`--stat`などpatchを生成しない出力指定は使えません。

## MCP

stdio設定の例です。

```json
{
  "transport": "stdio",
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "/path/to/project"
}
```

```text
context-stat mcp list --config mcp.json
context-stat mcp list --kind tools --config mcp.json
context-stat mcp request --config mcp.json --method tools/call --name echo --params '{"message":"hello"}'
```

Streamable HTTPは設定の`transport`を`streamable-http`、`url`を指定します。認証値は`headers_from_env`で環境変数から読み込みます。`--allow-online`はMCP接続の許可ではありません。

## 出力と診断

計測結果は標準出力、警告とエラーは標準エラーです。画像、バイナリ、壊れた入力、未導入バックエンドなどで対象を計測できない場合は、結果の状態と最後の診断を確認します。

```text
context-stat --format json stat src/ 1>result.json 2>warnings.log
```

## シェル補完

```text
context-stat completions bash
context-stat completions zsh
context-stat completions fish
```
