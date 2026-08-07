# MCPクライアントと通信方式

MCP実機接続を採用する際の参照時点の調査ログである。現行版の挙動は`../../仕様/context-stat機能仕様.md`と`../../現状/context-statの現状.md`を正とする。

## 参照先

- [Architecture overview](https://modelcontextprotocol.io/docs/learn/architecture)
- [Transports](https://modelcontextprotocol.io/specification/draft/basic/transports)
- [Lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)
- [Official SDKs](https://modelcontextprotocol.io/docs/sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)

## 参照時点の確認事項

- MCPはhost、client、serverのクライアント・サーバー構成であり、context-statはMCP serverへ接続するclient側として設計できる。
- 標準transportはstdioとStreamable HTTPである。stdioではclientがserverをサブプロセスとして起動し、Streamable HTTPでは独立したserverへ接続する。
- MCPのデータ層はJSON-RPCを使用し、初期化、プロトコルバージョンと能力の交渉、通常操作、終了のライフサイクルを持つ。
- 実装ではリクエストのタイムアウトが推奨され、stdioではserverの終了待ちと必要に応じた終了処理が必要になる。
- 旧HTTP+SSEを新しい標準transportとして追加せず、Streamable HTTPを使う方針とする。
- 公式Python SDKはMCP clientと標準transportを提供する。現行版の依存範囲は`pyproject.toml`と`uv.lock`で固定している。

## 現行実装との対応

- JSON-RPC、初期化、能力交渉、transportは公式Python SDKをアダプター越しに利用する。
- stdioとStreamable HTTPを設定で選択し、stdioのコマンドと引数は分離して保持する。
- MCPの論理リクエスト、返却content、構造化値を計測し、`--allow-online`とは分離する。
- SDKからwire-levelの値を取得できないため、protocolのトークン計測は`skip`として記録する。

## 更新時の確認事項

- MCPのプロトコル版と公式Python SDKのAPIは変化するため、依存更新時に採用版とtransport APIを再確認する。
- MCP hostがtool callやtool resultをLLMへ渡す具体的なシリアライズはhost実装に依存する。現行版は論理payloadを計測し、wire-levelの値を推定しない。

## 取り扱い

この文書は仕様検討のための外部参照ログであり、参照先の内容を再配布するものではない。
