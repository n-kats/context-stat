from __future__ import annotations

import base64
import sys
from types import SimpleNamespace

import pytest

from context_stat.adapters.token import TokenCounterResolver
from context_stat.domain.errors import OnlineNotAllowedError


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


def test_anthropic_backend_requires_allow_online_before_importing_sdk() -> None:
    with pytest.raises(OnlineNotAllowedError, match="--allow-online"):
        TokenCounterResolver().count(
            "hello",
            backend="anthropic-api",
            tokenizer="claude-opus-5",
            allow_online=False,
        )


def test_anthropic_backend_counts_text_with_provider_api(monkeypatch) -> None:
    calls = []

    class FakeMessages:
        def count_tokens(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(input_tokens=14)

    class FakeAnthropic:
        def __init__(self):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))

    metric = TokenCounterResolver().count(
        "hello",
        backend="anthropic-api",
        tokenizer="claude-opus-5",
        allow_online=True,
    )

    assert metric.value == 14
    assert metric.method == "anthropic-api:claude-opus-5"
    assert metric.external is True
    assert calls == [
        {
            "model": "claude-opus-5",
            "messages": [{"role": "user", "content": "hello"}],
        }
    ]


def test_anthropic_backend_counts_image_with_base64_content(monkeypatch) -> None:
    calls = []

    class FakeMessages:
        def count_tokens(self, **kwargs):
            calls.append(kwargs)
            return {"input_tokens": 23}

    class FakeAnthropic:
        def __init__(self):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))
    data = b"image bytes"

    metric = TokenCounterResolver().count_image(
        data,
        model="claude-sonnet-5",
        media_type="image/png",
        allow_online=True,
    )

    assert metric.value == 23
    image_source = calls[0]["messages"][0]["content"][0]["source"]
    assert image_source == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.standard_b64encode(data).decode("ascii"),
    }
