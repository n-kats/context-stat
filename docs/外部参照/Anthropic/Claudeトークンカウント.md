# Claudeトークンカウント

AnthropicのToken Count APIを`anthropic-api`バックエンドへ反映するための参照ログである。ローカルのClaude用トークナイザーは実装せず、APIを使う場合だけ入力を外部へ送信する。

## 参照先

- [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Count tokens in a Message](https://platform.claude.com/docs/en/api/messages/count_tokens)
- [Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Coordinates and bounding boxes](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates)

## 参照時点の確認事項

- Token Count APIは、メッセージ、システムプロンプト、ツール、画像、PDFなど、Messages APIと同じ構造の入力を計測できる。
- 応答には`input_tokens`が含まれる。値はAPIの入力トークン数であり、システム最適化のために追加されるトークンを含む場合がある。
- APIに渡すモデルによって使用されるトークナイザーが変わるため、実際に利用するモデルIDを指定して計測する必要がある。例としてClaude 5系では`claude-sonnet-5`や`claude-opus-5`を指定する。
- Token Count APIの値は、Messages APIの実際の使用量と少し異なる場合がある。
- 画像はbase64のimage content blockとしてMessages API形式へ含められる。形式、寸法、上限、プロバイダー側の正規化はAnthropicの現行仕様に従うため、context-statが独自のリサイズ式へ置き換えない。

## 現行実装への扱い

- `anthropic-api`はextraから導入する選択式バックエンドであり、`auto`から選択しない。
- テキストでは`--text-tokenizer`のモデルIDと本文を1つのuserメッセージとしてAPIへ渡す。
- 画像では`--image-tokenizer anthropic-api`を指定し、`--text-tokenizer`のモデルIDと画像データをAPIへ渡す。
- `--allow-online`がない場合はSDKを読み込まず、入力を送信しない。API計測値は`external=true`として記録する。

## 取り扱い

この文書は仕様検討のための外部参照ログであり、参照先の内容を再配布するものではない。
