from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Protocol

from context_stat.domain.errors import (
    BackendUnavailableError,
    ContextStatError,
    OnlineNotAllowedError,
)
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

    def count_image(
        self,
        data: bytes,
        *,
        model: str | None,
        media_type: str,
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
        selected = "tiktoken" if backend == "auto" else backend
        if selected == "tiktoken":
            return self._tiktoken(text, tokenizer)
        if selected == "tokenizers":
            return self._tokenizers(text, tokenizer)
        if selected == "anthropic-api":
            return self._anthropic_text(text, tokenizer, allow_online=allow_online)
        raise ValueError(f"unsupported token backend: {selected}")

    def count_image(
        self,
        data: bytes,
        *,
        model: str | None,
        media_type: str,
        allow_online: bool,
    ) -> MetricValue:
        if not allow_online:
            raise OnlineNotAllowedError(
                "backend anthropic-api requires --allow-online before sending input"
            )
        return self._anthropic_image(
            data,
            model,
            media_type,
            allow_online=allow_online,
        )

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

    @classmethod
    def _anthropic_text(
        cls,
        text: str,
        tokenizer: str | None,
        *,
        allow_online: bool,
    ) -> MetricValue:
        cls._require_online(allow_online)
        model = cls._anthropic_model(tokenizer)
        response = cls._count_anthropic(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return cls._anthropic_metric(response, model=model, input_kind="text")

    @classmethod
    def _anthropic_image(
        cls,
        data: bytes,
        model_name: str | None,
        media_type: str,
        *,
        allow_online: bool,
    ) -> MetricValue:
        model = cls._anthropic_model(model_name)
        cls._require_online(allow_online)
        encoded = base64.standard_b64encode(data).decode("ascii")
        response = cls._count_anthropic(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        }
                    ],
                }
            ],
        )
        return cls._anthropic_metric(response, model=model, input_kind="image")

    @staticmethod
    def _anthropic_model(tokenizer: str | None) -> str:
        if not tokenizer or tokenizer == DEFAULT_TEXT_TOKENIZER:
            raise ValueError(
                "--text-tokenizer must be an Anthropic model ID for --backend anthropic-api"
            )
        return tokenizer

    @staticmethod
    def _require_online(allow_online: bool) -> None:
        if not allow_online:
            raise OnlineNotAllowedError(
                "backend anthropic-api requires --allow-online before sending input"
            )

    @staticmethod
    def _count_anthropic(*, model: str, messages: list[dict[str, Any]]) -> Any:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise BackendUnavailableError(
                'anthropic-api is not installed; install with `uv tool install ".[anthropic-api]"`'
            ) from exc

        try:
            client = Anthropic()
            return client.messages.count_tokens(model=model, messages=messages)
        except Exception as exc:
            raise ContextStatError(
                f"anthropic token count request failed: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _anthropic_metric(response: Any, *, model: str, input_kind: str) -> MetricValue:
        count = getattr(response, "input_tokens", None)
        if count is None and isinstance(response, dict):
            count = response.get("input_tokens")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContextStatError("anthropic token count response has no valid input_tokens")
        return MetricValue.exact(
            count,
            unit="tokens",
            method=f"anthropic-api:{model}",
            external=True,
            details={
                "provider": "anthropic",
                "model": model,
                "input_kind": input_kind,
            },
        )
