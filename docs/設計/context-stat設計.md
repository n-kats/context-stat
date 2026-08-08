# context-stat設計

この文書は、現行実装の責務と論理的な境界を説明する。後半の`UseCase`や`ContentSource`などの名前は責務の単位であり、すべてが同名のPythonクラスとして存在することを意味しない。実際の配置は`../目次.md`、未完了の構造上の差分は`../現状/context-statの現状.md`を参照する。

現行実装のファイル責務と、まだ分離していない論理境界を同じ図で示す。現行実装は`cli.py`から各アダプターとドメインサービスを呼び出す構成である。実際に存在する型・関数を確認するときはソースコードと`../現状/`を参照し、論理名を実装済みクラス名として扱わない。

## 設計方針

- CLIは引数の解釈、入力アダプターの起動、レポートと診断の出力を担当し、計測式は`MeasurementService`へ集約する。
- ファイル、標準入力、コマンド結果、Jinjaの結果、Git差分、MCPの送受信内容を、共通の計測対象に変換する。
- トークン計測、画像計測、外部接続、出力形式は交換可能な境界を持たせる。
- ドメイン層はClick、Git、MCP SDK、各トークナイザーなどの外部ライブラリに依存しない。
- MCPクライアント用の公式Python SDKとtiktokenはコア依存として標準インストールに含める。追加のトークンバックエンドはextraから遅延ロードする。
- 画像トークン方式は、画像ライブラリの既定動作ではなく、context-stat側のコードとテストで管理する。
- MCPは、context-statがMCPサーバーに接続して実機の一覧取得またはリクエスト実行を行う構成だけを扱う。MCPサーバー自体をcontext-statに組み込む機能や、MCP形式の記録ファイルを直接集計する機能は設計対象にしない。

## レイヤー

```text
CLI
  -> Application use case
       -> Input / external adapter
       -> Measurement domain service
            -> text tokenizer backend
            -> image policy and estimator
       -> Report
  -> Output renderer
```

依存方向は、外側の実装から内側のドメインへ向ける。ドメインが外部ライブラリを直接呼び出さず、Protocolまたはインターフェースを介してアダプターを受け取る。

## 対象ディレクトリ構造

現行実装では、責務が小さいものを無理に分割せず、次の配置にまとめている。論理上のレイヤーと責務の関係はこのファイルの後半で定義し、物理的な一覧は`../目次.md`に記載する。

```text
pyproject.toml
src/
  context_stat/
    __init__.py
    __main__.py
    cli.py
    domain/
      content.py
      errors.py
      measurement.py
      parallel.py
      report.py
      service.py
    adapters/
      filesystem.py
      git.py
      image.py
      mcp.py
      process.py
      templating.py
      token.py
    output.py
tests/
  unit/
    test_adapters.py
    test_cli.py
    test_image.py
    test_mcp_config.py
    test_output.py
    test_process.py
    test_service.py
    test_token.py
  fixtures/
    mcp_stdio_server.py  # stdio/Streamable HTTP実機確認用
```

## 論理責務と実装単位

この設計で示す`Command`、`UseCase`、`ContentSource`、`OutputRenderer`、`McpExchangeRecorder`、`McpContentExtractor`は、責務を表す論理名である。現行実装では、すべてを同名のPythonクラスへ分離していない。

| 論理上の責務 | 現行実装 | 状態 |
| --- | --- | --- |
| Command / UseCase | `cli.py`のClickコマンドと補助関数 | コマンド処理と入力・計測・出力の組み立てを同じモジュールで行う |
| ContentSource | `adapters/filesystem.py`、`process.py`、`git.py`、`templating.py`、`mcp.py` | 入力元ごとの関数・アダプターとして実装し、共通Sourceクラスにはしていない |
| MeasurementService | `domain/service.py`の`MeasurementService` | クラスとして実装済み |
| TokenCounter | `adapters/token.py`の`TokenCounter` Protocolと`TokenCounterResolver` | Protocolと解決処理を実装済み |
| ImageMetadataReader / ImageTokenEstimator | `adapters/image.py` | クラスとして実装済み |
| MeasurementReport | `domain/report.py`の`MeasurementGroup`、`MeasurementReport`など | クラスとして実装済み |
| OutputRenderer | `output.py`のrenderer関数群 | Rendererクラスには分離していない |
| McpExchangeRecorder / McpContentExtractor | `adapters/mcp.py`の結果変換処理と`cli.py`のMCP処理 | 独立クラスには分離していない |

この対応表は、設計上の責務と実際のクラス・関数を混同しないためのものである。現行版では、機能追加に必要な境界だけをクラスまたはProtocolとして実装し、残りの分離は将来の内部改善として扱う。

MCPの通信方式とJSON-RPCライフサイクルは公式Python SDKに任せ、`adapters/mcp.py`へ閉じ込める。context-stat固有の`McpClientPort`は論理的な一覧取得・リクエスト実行の境界とし、wire transportの詳細をドメインへ公開しない。SDKからwire-levelの情報を取得できることは前提にしない。

## 基本的なドメインオブジェクト

### `ContentItem`

各入力元から出てくる1つの計測対象を表す。対象の種類と出所を保持し、テキストと画像を同じ文字列として扱わない。

- `origin`: ファイルパス、標準入力、コマンド、Git、MCPなどの出所
- `label`: 表示用の名前
- `kind`: `text`、`image`、または`structured`
- `payload`: `TextPayload`、`ImagePayload`、`StructuredPayload`のいずれか
- `metadata`: パス、コマンド、MCPの方向などの補足情報

`TextPayload`は元のバイト列、デコード済みテキスト、エンコーディング、デコード状態を保持する。`ImagePayload`はファイルまたはMCPから読み込んだ画像バイト列と、任意のメディア型・出所を保持する。画像メタデータは計測時に画像バイト列から読み取る。`StructuredPayload`はMCPなどの構造化値と、その計測用シリアライズを分けて保持する。

入力元が`ContentItem`以外の構造化事実を返す場合は、`ContentBundle`として次を分ける。

```text
ContentBundle
  items: ContentItem[]
  facts: SourceFacts
```

`items`は計測対象、`facts`はGitの変更ファイル数など、トークン合計へ自動加算しない構造化事実とする。

### `MeasurementOptions`

1回の計測条件をまとめる。CLIのClickコンテキストをそのまま下位層へ渡さない。

- テキスト用バックエンド
- テキスト用トークナイザー
- 画像用トークナイザー方式
- オンライン許可
- 画像を含める指定
- 出力形式
- 計測項目の選択
- ソートキーと順序

### `MeasurementResult` と `MeasurementReport`

`MeasurementResult`は1対象の値、`MeasurementReport`は対象一覧と合計を表す。値だけでなく、計測条件、状態、外部送信の有無、警告、エラーを保持する。

```text
measurement_status: measured | skip | failed
limit_status: within | over | provider_normalizes | unknown
```

`MetricValue`は値、単位、method、reason、details、外部送信の有無を持つ。MCPでは、`direction`と`semantic_role`を別に持たせ、送信側と返却側を別の結果として保持し、protocolメッセージをコンテキスト合計へ自動加算しない。

## 基本クラスの関係

```text
Command
  -> UseCase
       -> ContentSource
            -> ContentItem[]
       -> MeasurementService
            -> TextMetricsCalculator
            -> TokenCounter
                 -> TiktokenBackend / TokenizersBackend / AnthropicApiBackend
            -> ImageMetricsCalculator
                 -> ImageMetadataReader
                 -> ImageTokenPolicyRegistry
                 -> ImageTokenEstimator
                 -> AnthropicApiBackend
       -> MeasurementReport
       -> OutputRenderer
```

主要な責務は次のとおりとする。

- `UseCase`: コマンドごとの処理順序を組み立てる。計測式は持たない。
- `ContentSource`: 入力元を読み、`ContentItem`を返す。
- `MeasurementService`: 共通の文字数、行数、バイト数、トークン数、画像属性の計測を実行する。
- `TokenCounter`: 指定されたテキスト用バックエンドとトークナイザーでテキストトークン数を返す。`AnthropicApiBackend`はモデルIDを受け取り、APIの`input_tokens`を外部計測値として返す。
- `ImageTokenPolicy`: `gpt-5.6-style`など、画像トークン方式の計算条件と対応状態を定義する。
- `ImageTokenEstimator`: 解決された画像方式に従って画像トークン数と上限判定を返す。`anthropic-api`の場合は`AnthropicApiBackend`へ画像を渡す。対応外形式、アニメーション、未実装方式は`skip`を返す。画像の読み取り失敗は、画像属性を要求していれば属性側を`failed`、画像トークン側を`skip`として計測サービスが扱う。
- `OutputRenderer`: RichのTreeなどを使ってレポートを人間向けまたはJSON形式へ変換する。skipやfailedの注記は対象行へ重複表示せず、診断へ集約する。

## 入力元とユースケース

```text
StatCommand       -> StatUseCase       -> FileSource / StdinSource / CommandSource
JinjaCommand      -> JinjaUseCase      -> JinjaRenderer -> ContentItem
  GitDiffCommand    -> GitDiffUseCase    -> GitDiffArgumentParser -> GitRunner
  McpListCommand    -> McpListUseCase    -> McpClientPort -> OfficialMcpSdkAdapter
  McpRequestCommand -> McpRequestUseCase -> McpClientPort -> OfficialMcpSdkAdapter
```

- `FileSource`はファイルと再帰ディレクトリを列挙する。既定で`.gitignore`を反映し、`--ignore-gitignore`でignore規則を無効にする。非画像バイナリはテキスト計測へ渡さず、除外パスを`ContentBundle.facts`と警告へ記録する。画像を含めるかは`MeasurementOptions`または入力側の選択条件として扱う。
- ファイル単位の処理は、statの並列数に従って順序を保持したまま実行する。Gitignoreのパス判定はシンボリックリンクを解決せず、入力されたリポジトリ内のパスとしてGitへ渡す。
- `CommandSource`はパスからコマンドを生成して実行し、標準出力を`ContentItem`にする。終了状態と標準エラーは計測対象本文とは分ける。
- `JinjaUseCase`はテンプレートをレンダリングし、レンダリング結果だけを`ContentItem`にする。
- `GitDiffUseCase`はGit差分専用パーサーの構造化結果からGit実行用argvを作り、結果とファイル別差分情報を受け取る。CLIの未知引数素通しは使わない。patch本文を生成しないGit出力モードは事前に拒否する。

## トークンと画像の境界

```text
TokenBackendResolver
  -> TokenCounter
       -> TiktokenBackend
       -> TokenizersBackend
       -> AnthropicApiBackend

ImageTokenPolicyRegistry
  -> ImageTokenPolicy
       -> image metadata / limits / detail / normalization rule
  -> ImageTokenEstimator
  -> AnthropicApiBackend
```

`TokenBackendResolver`は`--backend`、`--text-tokenizer`、インストール済みextra、外部通信許可を見てテキスト用バックエンドを解決する。`auto`はtiktokenを選択し、不整合時にはフォールバックせずエラーにする。`anthropic-api`はextraから遅延ロードし、`--text-tokenizer`をモデルIDとして`messages/count_tokens`を呼び出す。`--allow-online`がない状態ではSDKのimportと入力送信を行わない。

画像は通常、テキスト用`TokenCounter`へ渡さない。`ImageTokenEstimator`は元画像のメタデータを受け取り、画像方式に基づいて次を返す。`--image-tokenizer anthropic-api`の場合だけ、画像データとメディアタイプを`AnthropicApiBackend`へ渡し、`--text-tokenizer`のモデルIDでAPI計測する。

既定の`gpt-5.6-style`は元画像の幅と高さから32x32パッチ数を算出する。`anthropic-api`はbase64のimage content blockをAPIへ送り、返却された`input_tokens`を使う。どちらの方式でもcontext-statはリサイズを実行しない。GPT-5.6の入力形式に含まれない形式とアニメーションGIFは、ローカル方式では`skip`にする。

- 元画像の属性
- 画像方式の制約
- 必要な場合の計算上の有効寸法
- 画像トークン数と計測状態
- 上限超過時の扱い

画像ライブラリを利用する場合も、形式と寸法の読み取りに限定する。任意の補間法で画像をリサイズする処理は持たせない。

## MCPサーバー接続の設計

MCPは、設定されたサーバーへ接続するクライアントとして設計する。JSON-RPC、初期化、能力交渉、stdio、Streamable HTTPの詳細は公式Python SDKに任せ、context-stat側は論理操作と計測記録を担当する。

```text
McpListUseCase / McpRequestUseCase
  -> McpServerConfig
  -> McpClientPort
       -> OfficialMcpSdkAdapter
            -> official mcp SDK
                 -> stdio / Streamable HTTP
  -> McpExchangeRecorder
       -> generated / returned
  -> McpContentExtractor
       -> ContentItem[]
```

### `McpServerConfig`

サーバーの起動または接続に必要な設定を表す。コマンド、引数、環境変数、接続先、接続方式などを保持する。秘密情報そのものをレポートやログへ出力する責務は持たない。

CLIではJSON設定を`--config`で指定する方法、CodexのTOML設定を`--codex-config`で指定する方法、Streamable HTTPの接続先を`--url`で直接指定する方法を提供する。Codex設定に複数の有効なMCPサーバーがある場合は`--server NAME`で選択する。直接指定時のHTTPヘッダーは`--header-from-env HEADER=ENV`で環境変数名だけを渡し、URLとヘッダー値はレポートへ出力しない。`--config`、`--codex-config`、`--url`は同時に指定しない。

context-stat用の設定ファイルはJSONオブジェクトとし、Codex設定はTOMLの`[mcp_servers.<名前>]`を使う。context-stat用JSONのstdioは次の形式を使う。

```json
{
  "transport": "stdio",
  "command": "uv",
  "args": ["run", "python", "server.py"],
  "cwd": "/path/to/project",
  "env": {"MCP_MODE": "test"}
}
```

Streamable HTTPは`url`を必須とし、認証値は環境変数名だけを設定する。

```json
{
  "transport": "streamable-http",
  "url": "https://example.invalid/mcp",
  "headers_from_env": {"Authorization": "MCP_AUTHORIZATION"}
}
```

`env`はstdio子プロセスへ渡す環境変数、`headers_from_env`はHTTP接続時に読み込む環境変数名であり、値そのものは設定ファイルへ書かない。Codex設定を使う場合は、`[mcp_servers.<名前>]`の接続情報を`McpServerConfig`へ変換する。Codexの`http_headers`は静的ヘッダー、`env_http_headers`と`bearer_token_env_var`は環境変数から読むヘッダーとして扱う。OAuth保存情報やChatGPTセッション認証はアダプターへ渡さない。現行の公式SDK依存範囲は`pyproject.toml`の`mcp>=2,<2.1`で固定する。

### `McpClientPort`

一覧取得、リクエスト実行、実行時間、エラーをcontext-statの論理操作として定義する。wire transportの型やSDK固有の型を返さない。

### `OfficialMcpSdkAdapter`

公式Python SDKのclient sessionとtransportを`McpClientPort`へ変換する。SDKの版変更はこのアダプター内に閉じ込める。wire-levelのJSON-RPC envelopeや通知は、SDKから取得できてもcontext-statの計測対象にはしない。

### `McpExchangeRecorder`

論理リクエスト、返却結果、content、実行時間、エラーを記録する。結果には`direction`と`semantic_role`を持たせる。`generated`と`returned`は別合計にし、initializeなどのprotocolメッセージは計測対象にもコンテキスト合計にも含めない。wire-levelのprotocol値は`skip`や推定値として記録しない。MCPが`isError: true`を返した場合は、返却結果の状態を`facts.result`へ記録し、通信・プロトコル例外とは区別する。返却結果の表示値は、画像データを寸法表示へ置き換えたサニタイズ済み値とし、本文の表示は`-v`/`--verbose`指定時に限る。

### `McpContentExtractor`

レスポンス内のtext、image、structuredContentなどのcontentを抽出する。画像contentは画像計測へ、text contentはテキスト計測へ渡す。MCP envelope全体とcontent本文を同じ合計へ二重計上しない。各itemは、元メッセージID、contentのパス、シリアライズ方法、合計への採用有無を追跡できるようにする。

## 出力の責務

`MeasurementReport`は出力形式を知らず、`output.py`のrenderer関数が表示を担当する。JSONは`schema_version=1`の公開フィールドへ明示的に変換し、ドメインオブジェクトを直接JSON化しない。path groupではファイルnodeとディレクトリ集計nodeを別に作り、ディレクトリnodeは配下の測定済みファイルを集計する。path group以外ではグループ全体の集計値を`summary`として出力し、tableでもグループ名の先頭行に表示する。`mcp request`では結果状態を表の外側に表示し、`-v`/`--verbose`指定時だけ返却結果本文を続けて表示する。画像contentのデータはMIME typeと寸法へ置き換える。全角文字を含む表はUnicodeの表示幅を使って列を整列し、警告・エラーは診断出力として標準エラーへ分離する。公開フィールドの詳細は機能仕様の「JSON出力の現行スキーマ」を参照する。

## 現行実装で確定した事項

- MCP設定はJSONまたはCodex TOMLとし、stdioは`command`、Streamable HTTPは`url`を必須とする。Codex TOMLは`[mcp_servers.<名前>]`から接続設定を変換する。
- MCPのSDK依存は`mcp>=2,<2.1`とし、wire-levelのprotocolメッセージは計測対象にしない。
- payloadは計測対象を保持する不変データクラスとし、ストリーミング再読込は現行版の対象外とする。
- Git差分はファイル単位のpatchを`ContentItem`として扱い、変更ファイル数・追加行数・削除行数は`ContentBundle.facts`へ分離する。
- JSONの公開スキーマは`schema_version=1`とし、機能仕様に定義する。
- 画像方式は現行版では`gpt-5.6-style`と`anthropic-api`を実装し、公式根拠のない方式へフォールバックしない。

## 将来拡張

- 公式仕様と入力条件が確定した追加の画像トークン方式。
