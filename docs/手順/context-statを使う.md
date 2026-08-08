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
context-stat -v mcp request --config mcp.json --method tools/call --name echo --params '{"message":"hello"}'
context-stat mcp list --codex-config ~/.codex/config.toml --server docs
context-stat -v mcp request --codex-config ~/.codex/config.toml --server docs --method tools/call --name echo --params '{"message":"hello"}'
context-stat mcp list --url https://example.test/mcp
context-stat -v mcp request --url https://example.test/mcp --header-from-env Authorization=MCP_AUTHORIZATION --method tools/call --name echo --params '{"message":"hello"}'
```

`mcp request`は計測表の後にMCP結果の状態を表示する。`-v`/`--verbose`を共通オプションとして付けた場合だけ、その後に返却結果本文を表示する。返却contentに画像がある場合は、Base64を表示せず、MIME typeと幅・高さへ置き換える。MCPサーバーが`isError: true`を返した場合も結果状態と計測値を出力し、標準エラーへ診断を出したうえで終了コードは失敗になる。

MCP接続は`--config FILE`、Codex設定の`--codex-config FILE`、`--url URL`のいずれかを指定します。`--url`はStreamable HTTPとして扱われます。Codex設定は`[mcp_servers.<名前>]`を読み取り、有効なサーバーが1つなら自動選択します。複数ある場合は`--server NAME`を指定します。`--config`、`--codex-config`、`--url`は同時に指定できません。`--allow-online`はMCP接続の許可ではありません。

Codex設定からは、stdioの`command`、`args`、`cwd`、`env`と、Streamable HTTPの`url`、`headers`、`env_http_headers`、`bearer_token_env_var`を読み取ります。CodexのOAuth保存情報やChatGPTセッション認証はcontext-statから利用しません。

## 出力と診断

計測結果は標準出力、警告とエラーは標準エラーです。画像、バイナリ、壊れた入力、未導入バックエンドなどで対象を計測できない場合は、結果の状態と最後の診断を確認します。

```text
context-stat --format json stat src/ 1>result.json 2>warnings.log
```

## 出力形式の例

標準入力を`hello`として計測した場合の主な形式は次のとおりです。

```text
$ printf 'hello\n' | context-stat stat -
source: stdin
[items]
+-------+--------+
| item  | tokens |
+-------+--------+
| items |      2 |
| -     |      2 |
+-------+--------+
```

`tree`は対象の階層を罫線で表示します。

```text
$ printf 'hello\n' | context-stat --format tree stat -
source: stdin
└── items [2 tokens]
    └── - [2 tokens]
```

`json`では、計測条件、項目別の値、グループの集計値、診断配列を分けて取得できます。MCPの`mcp request`では、`facts.result`に結果状態と返却contentの要約が入り、`-v`/`--verbose`指定時だけ`value`に返却結果本文が入ります。画像データはMIME typeと寸法の表示へ置き換わります。

```text
$ jq '.facts.result.value | {content, structuredContent}' mcp-result.json
{
  "content": [
    {"type": "text", "text": "hello"}
  ],
  "structuredContent": {"echo": "hello"}
}
```

上の`jq`例の`mcp-result.json`は、`context-stat -v --format json mcp request ...`で作成したJSONを想定しています。`mcp request`の人間向け出力では、計測表の後に結果状態が表示され、`-v`/`--verbose`指定時だけ返却結果本文が続きます。画像は例えば`<image/png 48x24>`のように表示され、Base64は出力されません。`isError: true`の場合は結果状態を表示した後、`-v`指定時は本文も表示し、標準エラーへ診断を出して終了コードを失敗にします。

## 診断の例

計測結果は標準出力、警告とエラーは標準エラーへ出力されます。診断には種類と対象が含まれます。

```text
warning [measurement-skipped] [item-id]: tokens: image tokenizer is not implemented
error [measurement-failed] [item-id]: tokens: text decoding failed
```

## シェル補完

```text
context-stat completions bash
context-stat completions zsh
context-stat completions fish
```
