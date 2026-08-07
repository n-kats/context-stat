from __future__ import annotations

from pathlib import Path
from typing import Protocol

from context_stat.domain.errors import BackendUnavailableError
from context_stat.domain.measurement import MetricValue

DEFAULT_TEXT_TOKENIZER = "o200k_base"


class TokenCounter(Protocol):
    def count(
        self,
        text: str,
        *,
        backend: str,
        tokenizer: str | None,
        allow_online: bool,
    ) -> MetricValue: ...


class TokenCounterResolver:
    def count(
        self,
        text: str,
        *,
        backend: str,
        tokenizer: str | None,
        allow_online: bool,
    ) -> MetricValue:
        del allow_online
        selected = "tiktoken" if backend == "auto" else backend
        if selected == "tiktoken":
            return self._tiktoken(text, tokenizer)
        if selected == "tokenizers":
            return self._tokenizers(text, tokenizer)
        raise ValueError(f"unsupported token backend: {selected}")

    @staticmethod
    def _tiktoken(text: str, tokenizer: str | None) -> MetricValue:
        try:
            import tiktoken
        except ImportError as exc:
            raise BackendUnavailableError(
                "tiktoken is not installed; reinstall context-stat with its standard dependencies"
            ) from exc

        encoding_name = tokenizer or DEFAULT_TEXT_TOKENIZER
        encoding = tiktoken.get_encoding(encoding_name)
        count = len(encoding.encode(text))
        return MetricValue.exact(
            count,
            unit="tokens",
            method=f"tiktoken:{encoding_name}",
            external=False,
        )

    @staticmethod
    def _tokenizers(text: str, tokenizer: str | None) -> MetricValue:
        if not tokenizer:
            raise ValueError("--text-tokenizer must point to a tokenizer.json file for tokenizers")
        try:
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise BackendUnavailableError(
                'tokenizers is not installed; install with `uv tool install ".[tokenizers]"`'
            ) from exc
        path = Path(tokenizer)
        if not path.is_file():
            raise ValueError(f"tokenizer file does not exist: {path}")
        try:
            loaded = Tokenizer.from_file(str(path))
        except Exception as exc:
            raise ValueError(f"could not load tokenizer file {path}: {exc}") from exc
        count = len(loaded.encode(text).ids)
        return MetricValue.exact(
            count,
            unit="tokens",
            method=f"tokenizers:{path}",
            external=False,
        )
