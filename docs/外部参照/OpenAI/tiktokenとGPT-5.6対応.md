# tiktokenとGPT-5.6対応

## 参照先

- [Model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [tiktoken model.py](https://github.com/openai/tiktoken/blob/main/tiktoken/model.py)
- [tiktoken CHANGELOG](https://github.com/openai/tiktoken/blob/main/CHANGELOG.md)

## 確認日

2026-08-07 UTC

## 参照時点の確認事項

- OpenAI公式のモデルガイドは、GPT-5.6のエイリアスが`gpt-5.6-sol`へルーティングされること、`gpt-5.6-terra`と`gpt-5.6-luna`が別のGPT-5.6系モデルIDであることを記載している。
- tiktoken公式の`model.py`は、`gpt-5`と`gpt-5-`で始まるモデルを`o200k_base`へ対応付けている。
- tiktoken公式の`model.py`には、`gpt-5.6`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`の直接エントリはない。`gpt-5.6`は`gpt-5-`という接頭辞にも一致しない。
- tiktoken公式の変更履歴にはGPT-5対応の記載はあるが、GPT-5.6の直接対応は確認できない。
- 2026-08-07時点の`uv.lock`にあるtiktokenは`0.13.0`であり、4つのGPT-5.6系IDはいずれも`encoding_for_model`で未登録となることを確認した。

## 現行実装との対応

- 現行CLIはモデルIDを受け取らず、`--text-tokenizer`で指定された`tiktoken`のエンコーディングをそのまま計測条件とする。
- GPT-5.6向けに使用する場合も、既定の`o200k_base`をモデル推定値として表示せず、選択されたトークナイザーによる計測値として扱う。現行出力に`exact`や`estimated`の精度分類は設けない。
- GPT-5.6系で使うエンコーディングの変更や追加登録がtiktoken側で行われた場合は、依存更新時に方式とテストを再確認する。
