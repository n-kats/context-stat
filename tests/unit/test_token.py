from __future__ import annotations

import pytest

from context_stat.adapters.token import TokenCounterResolver


def test_auto_uses_o200k_base_by_default() -> None:
    metric = TokenCounterResolver().count(
        "hello world",
        backend="auto",
        tokenizer=None,
        allow_online=False,
    )

    assert metric.method == "tiktoken:o200k_base"
    assert metric.value == 2
    assert metric.external is False


def test_explicit_text_tokenizer_is_used() -> None:
    metric = TokenCounterResolver().count(
        "hello world",
        backend="tiktoken",
        tokenizer="cl100k_base",
        allow_online=False,
    )

    assert metric.method == "tiktoken:cl100k_base"
    assert metric.value == 2


def test_tokenizers_backend_requires_a_tokenizer_file() -> None:
    with pytest.raises(ValueError, match="--text-tokenizer"):
        TokenCounterResolver().count(
            "hello",
            backend="tokenizers",
            tokenizer=None,
            allow_online=False,
        )


def test_tokenizers_backend_uses_tokenizers_library(tmp_path) -> None:
    pytest.importorskip("tokenizers")
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer = Tokenizer(
        WordLevel(
            vocab={"[UNK]": 0, "hello": 1, "world": 2},
            unk_token="[UNK]",
        )
    )
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.save(str(tokenizer_path))

    metric = TokenCounterResolver().count(
        "hello world",
        backend="tokenizers",
        tokenizer=str(tokenizer_path),
        allow_online=False,
    )

    assert metric.value == 2
    assert metric.method == f"tokenizers:{tokenizer_path}"


def test_tokenizers_backend_reports_a_corrupt_tokenizer_file(tmp_path) -> None:
    pytest.importorskip("tokenizers")
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer_path.write_text("not valid tokenizer json", encoding="utf-8")

    with pytest.raises(ValueError, match="could not load tokenizer file"):
        TokenCounterResolver().count(
            "hello",
            backend="tokenizers",
            tokenizer=str(tokenizer_path),
            allow_online=False,
        )


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported token backend"):
        TokenCounterResolver().count(
            "hello",
            backend="unknown",
            tokenizer=None,
            allow_online=False,
        )
