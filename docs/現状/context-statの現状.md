# context-statの現状

## 実装済みコマンド

- `stat`: ファイル、ディレクトリ、標準入力、ファイルごとのコマンド結果
- `jinja`: Jinjaレンダリング結果
- `git diff`: 変更ファイルごとのpatch
- `mcp list`: tools、resources、promptsの一覧
- `mcp request`: `tools/call`、`resources/read`、`prompts/get`
- `completions`: bash、zsh、fish

## 現在の既定値

- 出力: `table`
- 計測: `token`
- 並び順: `path`の昇順
- テキスト: `auto`から`tiktoken:o200k_base`
- 画像: `gpt-5.6-style`
- 並列数: `1`

## 対応範囲

- `table`、`tree`、`json`を出力できます。
- ディレクトリの`.gitignore`を既定で反映できます。
- 画像は直接指定、または`--include-images`付きの再帰走査で計測します。
- MCPはstdioとStreamable HTTPのサーバーへ接続します。
- MCP一覧のページング、埋め込みリソース、MCP本文のテキスト・画像を扱います。
- ファイル単位のコマンド起動失敗や計測状態は、他のコマンド対象を止めずに診断へ集約します。

## 制約

- 画像方式は現行版では`gpt-5.6-style`だけです。対応外形式、アニメーション、破損画像は画像トークンを計測せず、診断を出します。
- `tokenizers`は`.[tokenizers]`で追加導入します。自動インストールや別方式への黙った切り替えはしません。
- オンライン型トークン計測バックエンドは未実装です。`--allow-online`は将来のバックエンド用で、MCPとは無関係です。
- Gitはpatchを生成する出力だけに対応します。patchを生成しないGit出力モードは拒否します。
- MCPのwire-levelメッセージは、公式SDKから取得できないため計測対象にしません。
- 利用回数の記録、履歴の一括集計、LLM自身の呼び出しは対象外です。

## 検証

標準の確認手順は次のとおりです。

```text
uv run pytest
uv run --extra tokenizers pytest
uv run ruff check .
uv run ruff format --check .
uv lock --check
uv tool install .
```

## 正の情報源

コマンドの利用方法は`../手順/`、仕様は`../仕様/`、設計は`../設計/`を参照します。ここには実装済み範囲と制約だけを記録します。
