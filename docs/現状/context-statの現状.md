# context-statの現状

この文書は開発途中の記録であり、`docs/仕様/`に対する未完了・部分実装・確認待ちだけを記載する。実装済みの機能一覧や使い方は、[仕様](../仕様/context-stat機能仕様.md)と[手順](../手順/context-statを使う.md)を参照する。

## 仕様との差分

| 項目 | 現状 | 残っている差分 |
| --- | --- | --- |
| オンライン計測 | オンラインのトークン計測バックエンドは未実装。`--allow-online`は入力送信を発生させない | 送信先、extra、許可条件、エラー処理を定義して実装するまで利用できない |
| 画像方式 | `gpt-5.6-style`以外の画像方式は未実装 | 方式ごとの公式根拠、上限、正規化、テストが必要 |
| MCPのwire-level計測 | 公式SDKから取得できないため、protocolのトークン数は`skip` | SDKが値を公開した場合の取得・計測経路が未実装 |
| 論理レイヤーの分離 | `ContentItem`、`MeasurementService`、`MetricValue`、`MeasurementReport`、`McpServerConfig`などはクラスまたはProtocolとして存在する。一方、`UseCase`、共通の`ContentSource`、`OutputRenderer`、`McpExchangeRecorder`、`McpContentExtractor`は独立クラスではなく、主に`cli.py`、各アダプター、`output.py`の関数で処理している | 論理上の責務は整理済みだが、対応するクラスと共通インターフェースへの分離は未実施。分離する場合の境界と移行手順が未確定 |

## 論理責務と現行実装

設計文書の`UseCase`や`ContentSource`などは、処理を説明するための論理上の責務名である。同名のPythonクラスが存在することを意味しない。現行実装との対応は次のとおり。

| 論理上の責務 | 現行実装 | 分離状況 |
| --- | --- | --- |
| Command / UseCase | `cli.py`のClickコマンドと補助関数 | コマンド単位のUseCaseクラスには分離していない |
| ContentSource | `adapters/filesystem.py`、`process.py`、`git.py`、`templating.py`、`mcp.py`の入力処理 | 入力元ごとの関数・アダプターに分かれているが、共通のSourceクラスにはしていない |
| MeasurementService | `domain/service.py`の`MeasurementService` | クラスとして実装済み |
| TokenCounter | `adapters/token.py`の`TokenCounter` Protocolと`TokenCounterResolver` | 境界を実装済み |
| ImageMetadataReader / ImageTokenEstimator | `adapters/image.py` | クラスとして実装済み |
| MeasurementReport | `domain/report.py`の`MeasurementGroup`、`MeasurementReport`など | クラスとして実装済み |
| OutputRenderer | `output.py`のrenderer関数群 | Rendererクラスには分離していない |
| McpExchangeRecorder / McpContentExtractor | `adapters/mcp.py`の結果変換処理と`cli.py`のMCP処理 | 独立クラスには分離していない |

したがって、現状の差分は計測機能の不足ではなく、論理上の責務を物理的なクラスや共通インターフェースへ移す内部構造上の差分である。

## 次に確認すること

- オンライン計測を追加するか、`--allow-online`を現行CLIから外すか決める。
- 追加画像方式を実装する場合は、外部参照を更新してから仕様・コード・テストを同時に更新する。
- 設計上の論理境界を独立クラスへ分割する必要性を、機能追加時に再評価する。

## 直近の確認結果

- `uv run pytest -q`: 82 passed
- `uv run --extra tokenizers pytest -q`: 82 passed
- `uv run ruff check .`: 問題なし
- `uv run ruff format --check .`: 問題なし
- `uv lock --check`: 問題なし

## 正の情報源

仕様は`../仕様/`、利用方法は`../手順/`、設計上の判断は`../設計判断/`を参照する。この文書は、それらに対する開発中の差分だけを記録する。
