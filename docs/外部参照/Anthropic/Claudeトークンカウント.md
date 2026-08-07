# Claudeトークンカウント

Claude対応を採用する前の参照時点の調査ログである。現行版にClaude用バックエンド、モデル選択、画像方式は実装していない。

## 参照先

- [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Count tokens in a Message](https://platform.claude.com/docs/en/api/messages/count_tokens)
- [Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Coordinates and bounding boxes](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates)

## 参照時点の確認事項

- Token Count APIは、メッセージ、システムプロンプト、ツール、画像、PDFなどを含む入力のトークン数を計測できる。
- Token Count APIの結果は推定値であり、実際の入力トークン数と少し異なる場合がある。
- APIに渡すモデルによって使用されるトークナイザーが変わるため、モデルを指定して計測する必要がある。
- Visionの画像トークン数は、画像の幅と高さを28ピクセル単位のパッチに分けた概算式で説明されている。
- 画像がモデルの上限を超える場合、Claude側がアスペクト比を維持して縮小し、必要に応じて28の倍数になるようパディングしてから画像トークン数を扱う仕様がある。
- Claude Fable 5、Claude Mythos 5、Claude Sonnet 5は高解像度層（長辺2576px、4784 visual tokens）として扱い、Claude Opus 5は公式一覧上の高解像度層に含まれないため標準層（長辺1568px、1568 visual tokens）として扱う。
- Visionで受け付ける画像形式はJPEG、PNG、GIF、WebPで、アニメーションは最初のフレームだけが使われる。最大寸法は8000x8000px、Claude APIへ直接渡す画像のbase64後サイズ上限は10MBである。

## 現行実装への扱い

- 現行版では、このログの内容を計測方式やバックエンドとして使用しない。
- Claude対応を追加する場合は、公式仕様を再確認したうえで、方式名、外部送信条件、画像処理規則、テストを別途定義する。

## 取り扱い

この文書は仕様検討のための外部参照ログであり、参照先の内容を再配布するものではない。
