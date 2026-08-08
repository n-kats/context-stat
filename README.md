# context-stat

AIへの入力に含めるファイル、コマンド結果、Git差分、MCPの内容を計測するCLIです。通常はローカルで完結し、明示指定した場合だけ外部のToken Count APIへ入力を送信します。

## インストール

GitHubリポジトリから直接導入する場合は、次を実行します。

```console
uv tool install git+https://github.com/n-kats/context-stat
```

開発中のチェックアウトから導入する場合は、次を使います。

```console
uv tool install .
```

## バックエンド

`--backend`はテキストのトークン計測に使う実装を選び、`--text-tokenizer`はその実装で使うエンコーディングまたは`tokenizer.json`を指定します。画像の計測は別系統で、`--image-tokenizer`で方式を指定します。

現行版で使えるバックエンドは次のとおりです。

| 指定 | 内容 | 追加導入 | 外部送信 |
| --- | --- | --- | --- |
| `auto` | `tiktoken`を選択する既定値 | 不要 | しない |
| `tiktoken` | `o200k_base`など`tiktoken`のエンコーディングで計測 | 不要 | しない |
| `tokenizers` | Hugging Face形式の`tokenizer.json`で計測 | `tokenizers` extraが必要 | しない |
| `anthropic-api` | AnthropicのToken Count APIで計測。`--text-tokenizer`にモデルIDを指定 | `anthropic-api` extraが必要 | する |

画像はテキスト用バックエンドとは別に、既定の`gpt-5.6-style`で計測します。正常な画像では、元画像を32x32ピクセルのパッチで覆うために必要な数を画像トークン数とし、`ceil(width / 32) * ceil(height / 32)`で計算します。context-stat自身が画像をリサイズすることはありません。

通常は既定値のまま使えます。

```console
context-stat stat README.md
```

`tokenizers`を使う場合は、バックエンドを指定してextraを導入します。GitHubから導入する場合は次のとおりです。

```console
uv tool install "context-stat[tokenizers] @ git+https://github.com/n-kats/context-stat"
```

チェックアウトから導入する場合は次のとおりです。

```console
uv tool install ".[tokenizers]"
```

導入後、`--backend tokenizers`と`--text-tokenizer`で`tokenizer.json`を指定します。extraがない場合に、別のバックエンドへ黙って切り替えることはありません。

```console
context-stat --backend tokenizers --text-tokenizer ./tokenizer.json stat src/
```

`anthropic-api`を使う場合は、バックエンドと同名のextraを導入し、`--text-tokenizer`へAnthropicのモデルIDを指定します。GitHubから導入する例は次のとおりです。

```console
uv tool install "context-stat[anthropic-api] @ git+https://github.com/n-kats/context-stat"
```

チェックアウトから導入する場合は次のとおりです。

```console
uv tool install ".[anthropic-api]"
```

`ANTHROPIC_API_KEY`を設定し、`--allow-online`を付けた場合だけ入力をAnthropicへ送信します。テキストは`messages/count_tokens`の1つのuserメッセージとして計測されます。

```console
context-stat --backend anthropic-api --text-tokenizer claude-opus-5 --allow-online stat README.md
```

画像をAnthropic APIで計測する場合は、`--image-tokenizer anthropic-api`を指定します。モデルは`--text-tokenizer`の値を使います。

```console
context-stat --backend anthropic-api --text-tokenizer claude-opus-5 --image-tokenizer anthropic-api --allow-online stat image.png
```

## 基本操作

共通オプションはサブコマンドより前に置きます。Gitの引数は`--`を含めてGit差分専用パーサーが解釈します。

```console
context-stat --format json --metrics all --sort tokens --order desc git diff HEAD -- src/
```

以下では各操作の用途と、代表的な結果の形を示します。トークン数は入力内容と使用する方式によって変わります。

### ファイル、ディレクトリ、標準入力: `stat`

ファイルまたはディレクトリを計測します。ディレクトリは再帰的に走査し、既定では`.gitignore`を反映します。`-`を指定すると標準入力を1つの対象として計測します。

```console
context-stat stat README.md
context-stat --format tree stat src/
printf 'hello\n' | context-stat stat -
```

ファイルを指定した場合は、対象ファイルとトークン数などを表で返します。

```text
source: file
[items]
+-----------+------+--------+
| path      | kind | tokens |
+-----------+------+--------+
| README.md | file |   <値> |
+-----------+------+--------+
```

ディレクトリでは、ディレクトリ自身の合計と配下のファイルを`tree`で確認できます。`TOTAL`という別行は作りません。

```text
source: file
└── src [<合計> tokens]
    ├── context_stat [<合計> tokens]
    │   └── cli.py [<値> tokens]
    └── README.md [<値> tokens]
```

標準入力の例では、計測対象と合計が表示されます。

```text
source: stdin
[items]
+-------+--------+
| item  | tokens |
+-------+--------+
| items |      2 |
| -     |      2 |
+-------+--------+
```

`--command`を付けると、ディレクトリ内の各ファイルについて指定したコマンドを実行し、その標準出力を計測します。`{{path}}`は対象ファイルのパスに置き換わります。

```console
context-stat stat src/ --command 'cat "{{path}}"'
```

この場合は`source: command`となり、ファイルごとのコマンド出力、終了状態、標準エラー、タイムアウトや出力切り詰めの診断が結果に反映されます。

### テンプレートのレンダリング結果: `jinja`

JinjaテンプレートをJSONパラメータでレンダリングし、テンプレートそのものではなく、レンダリング後のテキストを計測します。

```console
context-stat jinja prompt.j2 --params '{"name":"Ada"}'
```

`prompt.j2`が`Hello {{ name }}`なら、結果は`source: jinja`、グループ`rendered`として表示され、`Hello Ada`のトークン数が計測されます。

```text
source: jinja
[rendered]
+-----------+--------+
| item      | tokens |
+-----------+--------+
| prompt.j2 |  <値>  |
+-----------+--------+
```

### Gitのファイル別差分: `git diff`

`git diff`と同じ比較対象・オプションを解釈し、変更ファイルごとのpatchを計測します。`--`以降はpathspecです。`--no-patch`、`--name-only`、`--stat`などpatchを生成しない指定は使えません。

```console
context-stat git diff HEAD -- src/
context-stat --format json --metrics all git diff main HEAD -- README.md
```

結果は`source: git`、グループ`diff`となり、差分全体の集計とファイルごとの値を返します。

```text
source: git
[diff]
+------------+--------+
| item       | tokens |
+------------+--------+
| diff       |  <合計> |
| src/app.py |   <値> |
+------------+--------+
```

### MCPの一覧取得: `mcp list`

MCPサーバーへ実際に接続し、提供されているtools、resources、promptsの定義、説明、パラメータSchemaを取得して計測します。通常、ツール自体は実行しません。

```console
context-stat mcp list --config mcp.json
context-stat mcp list --codex-config ~/.codex/config.toml --server docs
context-stat mcp list --url https://example.test/mcp
```

設定ファイル、Codexの`config.toml`、Streamable HTTPのURLのいずれかで接続します。結果はグループごとに分かれ、項目名、説明、URI、トークン数などを表示します。

```text
source: mcp-list
[tools]
+--------+--------------------------+--------+
| item   | description              | tokens |
+--------+--------------------------+--------+
| echo   | Return the supplied ...   |  <値>  |
+--------+--------------------------+--------+
[resources]
(no selected metrics)
```

### MCPリクエスト: `mcp request`

MCPのtool呼び出し、resource読み取り、prompt取得を実行し、送信側の論理リクエストと返却側のcontentを分けて計測します。

```console
context-stat -v mcp request --config mcp.json \
  --method tools/call --name echo --params '{"message":"hello"}'
```

表には`generated`と`returned`のグループが出力され、その後に結果状態が出ます。`-v`/`--verbose`を指定した場合だけ、さらに返却本文が表の外側へ表示されます。

```text
source: mcp-request
[generated]
+---------------------+--------+
| item                | tokens |
+---------------------+--------+
| generated           |  <値>  |
| tools/call request  |  <値>  |
+---------------------+--------+
[returned]
+---------------------+--------+
| item                | tokens |
+---------------------+--------+
| returned            |  <値>  |
| tools/call.content  |  <値>  |
+---------------------+--------+
result: ok
response:
  {
    "content": [
      {"type": "text", "text": "hello"}
    ]
  }
```

`-v`を付けない場合は`response:`以降を表示せず、`result: ok`または`result: error`と計測値だけを表示します。画像contentはBase64を表示せず、`<image/png 48x24>`のような形式へ置き換えます。`isError: true`の場合は結果を計測したうえで診断を標準エラーへ出し、終了コードは失敗になります。

### シェル補完: `completions`

指定したシェル向けの補完スクリプトを標準出力へ出します。計測表は出力しません。

```console
context-stat completions bash
context-stat completions zsh
context-stat completions fish
```

結果はシェル関数のスクリプトです。

```text
_context_stat_completion() {
    ...
}
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
| `--backend` | `auto` | `auto`、`tiktoken`、`tokenizers`、`anthropic-api` |
| `--text-tokenizer` | `o200k_base` | テキスト方式。`anthropic-api`ではClaudeモデルID |
| `--image-tokenizer` | `gpt-5.6-style` | 画像方式。`anthropic-api`で外部計測 |

`stat`固有の`--include-images`、`--ignore-gitignore`、`--command`、`--timeout`、`--max-output-bytes`は`stat`の後に置きます。

## 動作上の注意

- ディレクトリは再帰的に走査し、既定では`.gitignore`を反映します。`--ignore-gitignore`で無視できます。
- 直接指定したファイルは`.gitignore`に関係なく対象です。非画像バイナリはスキップします。
- 画像は直接指定なら対象です。ディレクトリでは`--include-images`を指定します。
- ディレクトリの合計はディレクトリ行に表示し、`TOTAL`行は出しません。
- `git diff`は変更ファイルごとのpatchを計測します。`--no-patch`などpatchを生成しない指定は拒否します。
- 警告とエラーの診断は標準エラーへまとめ、標準出力には計測結果を出します。
- `mcp request`は通常、計測表と結果状態だけを表示します。`-v`/`--verbose`を指定した場合だけ、表の外側にMCPから返った結果本文を表示します。画像のBase64は表示せず、MIME typeと幅・高さへ置き換えます。
- `--allow-online`は選択したトークン計測バックエンドの外部通信許可にだけ使います。`anthropic-api`では必須で、指定がなければ入力を送信しません。
- MCPは`--config FILE`、Codexの`--codex-config FILE`、またはStreamable HTTPの`--url URL`で接続できます。Codex設定に複数の有効なサーバーがある場合は`--server NAME`で選択します。認証ヘッダーは`--header-from-env HEADER=ENV`またはCodex設定のヘッダー指定から読み込みます。

## ドキュメント

- [docs/README.md](docs/README.md): 文書の入口
- [手順](docs/手順/context-statを使う.md): 用途別の使い方
- [仕様](docs/仕様/context-stat機能仕様.md): 現行仕様
- [現状](docs/現状/context-statの現状.md): 未完了事項、仕様との差分、確認待ち
- [設計](docs/設計/context-stat設計.md): 実装設計
- [設計判断](docs/設計判断/決定事項.md): 決定事項
- [目次](docs/目次.md): 文書と実装ファイルの一覧

## 開発

```console
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv lock --check
uv tool install .
```
