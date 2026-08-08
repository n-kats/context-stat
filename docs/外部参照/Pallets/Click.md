# Click

Click採用を決めた時点の参照ログである。現行の依存範囲は`pyproject.toml`と`uv.lock`を参照する。

## 参照先

- [ClickのPyPIページ](https://pypi.org/project/click/)
- [Click公式ドキュメント](https://click.palletsprojects.com/en/stable/)
- [Clickのシェル補完](https://click.palletsprojects.com/en/stable/shell-completion/)

## 確認事項

- Clickはコマンドの任意のネスト、ヘルプの自動生成、サブコマンドの遅延読み込みを提供する。
- Clickはシェル補完機能を提供する。
- 2026年8月7日時点で、PyPIの最新リリースは8.4.2である。
- PyPIのメタデータでは、Pythonの対応範囲は `>=3.10`、開発状態はProduction/Stable、配布wheelは `py3-none-any` である。

## 現行実装との対応

- context-statのCLI実装にClickを使用する。
- Clickは標準インストールに含むコア依存とし、トークナイザーなどのバックエンドextrasとは分離する。
- Pythonの対応範囲はcontext-stat側のCIで検証する。

## 取り扱い

この文書は仕様検討のための外部参照ログであり、参照先の内容を再配布するものではない。
