# Codex MCP設定

## 参照元

- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

## 確認内容

CodexのTOML設定では、MCPサーバーを`[mcp_servers.<名前>]`テーブルで定義する。

- stdio: `command`、`args`、`env`、`cwd`
- Streamable HTTP: `url`
- HTTPヘッダー: `http_headers`、`env_http_headers`、`bearer_token_env_var`
- 有効状態: `enabled`

Codex設定にはOAuth保存情報、ChatGPTセッション認証、ツールの許可・拒否設定などもあるが、これらはcontext-statのMCP接続へそのまま渡せない。

## context-statへの反映

`--codex-config FILE`でTOMLを読み取り、有効な接続設定が1つなら自動選択する。複数ある場合は`--server NAME`で選択する。context-statは接続設定だけを`McpServerConfig`へ変換し、Codexの保存済み認証やツール権限制御は再利用しない。

この文書は参照時点の調査ログであり、現行の対応範囲は`../../仕様/context-stat機能仕様.md`を参照する。
