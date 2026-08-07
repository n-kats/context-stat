from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

ALL_METRICS = frozenset(
    {
        "bytes",
        "characters",
        "lines",
        "max_line_length",
        "tokens",
        "path_length",
        "width",
        "height",
        "frames",
        "image_tokens",
    }
)

SORT_KEYS = (
    "path",
    "tokens",
    "bytes",
    "characters",
    "lines",
    "max-line-length",
    "image-tokens",
    "width",
    "height",
    "frames",
    "path-length",
)

_SORT_ALIASES = {
    "path": "path",
    "token": "tokens",
    "tokens": "tokens",
    "byte": "bytes",
    "bytes": "bytes",
    "character": "characters",
    "characters": "characters",
    "line": "lines",
    "lines": "lines",
    "max-line-length": "max_line_length",
    "max_line_length": "max_line_length",
    "image-token": "image_tokens",
    "image-tokens": "image_tokens",
    "image_tokens": "image_tokens",
    "width": "width",
    "height": "height",
    "frame": "frames",
    "frames": "frames",
    "path-length": "path_length",
    "path_length": "path_length",
}

_METRIC_ALIASES = {
    "byte": "bytes",
    "bytes": "bytes",
    "character": "characters",
    "characters": "characters",
    "line": "lines",
    "lines": "lines",
    "max-line-length": "max_line_length",
    "max_line_length": "max_line_length",
    "path-length": "path_length",
    "path_length": "path_length",
    "width": "width",
    "height": "height",
    "frame": "frames",
    "frames": "frames",
    "image-token": "image_tokens",
    "image-tokens": "image_tokens",
    "image_tokens": "image_tokens",
}


def parse_metric_selection(value: str) -> frozenset[str]:
    """Parse the CLI metric selection into canonical metric names."""
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise ValueError("--metrics must not be empty")

    selected: set[str] = set()
    for name in names:
        if name == "all":
            continue
        if name in {"token", "tokens"}:
            selected.update({"tokens", "image_tokens"})
            continue
        canonical = _METRIC_ALIASES.get(name)
        if canonical is None:
            choices = "all, token, bytes, characters, lines, max-line-length, path-length"
            raise ValueError(f"unknown metric {name!r}; choose from {choices}")
        selected.add(canonical)
    if "all" in names:
        return ALL_METRICS
    return frozenset(selected)


def parse_sort_selection(value: str) -> str:
    """Parse a sort key into its canonical metric name."""
    canonical = _SORT_ALIASES.get(value.strip().lower())
    if canonical is None:
        choices = ", ".join(SORT_KEYS)
        raise ValueError(f"unknown sort key {value!r}; choose from {choices}")
    return canonical


class MeasurementStatus(StrEnum):
    MEASURED = "measured"
    SKIP = "skip"
    FAILED = "failed"


class LimitStatus(StrEnum):
    WITHIN = "within"
    OVER = "over"
    PROVIDER_NORMALIZES = "provider_normalizes"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MetricValue:
    value: int | float | None
    unit: str
    status: MeasurementStatus
    method: str | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    external: bool | None = None

    @classmethod
    def exact(
        cls,
        value: int | float,
        unit: str = "count",
        method: str = "builtin",
        *,
        external: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> MetricValue:
        return cls(
            value,
            unit,
            MeasurementStatus.MEASURED,
            method=method,
            details=details or {},
            external=external,
        )

    @classmethod
    def skip(
        cls,
        unit: str = "count",
        reason: str = "skipped",
        *,
        details: dict[str, Any] | None = None,
    ) -> MetricValue:
        return cls(
            None,
            unit,
            MeasurementStatus.SKIP,
            reason=reason,
            details=details or {},
        )

    @classmethod
    def failed(
        cls,
        unit: str = "count",
        reason: str = "failed",
        *,
        details: dict[str, Any] | None = None,
    ) -> MetricValue:
        return cls(
            None,
            unit,
            MeasurementStatus.FAILED,
            reason=reason,
            details=details or {},
        )


@dataclass(frozen=True)
class MeasurementOptions:
    backend: str = "auto"
    text_tokenizer: str = "o200k_base"
    image_tokenizer: str = "gpt-5.6-style"
    allow_online: bool = False
    output_format: str = "table"
    metrics: frozenset[str] = frozenset({"tokens", "image_tokens"})
    sort: str = "path"
    order: str = "asc"
    parallel: int = 1


@dataclass(frozen=True)
class MeasuredItem:
    item_id: str
    origin: str
    label: str
    kind: str
    metrics: dict[str, MetricValue]
    metadata: dict[str, Any] = field(default_factory=dict)
    direction: str | None = None
    semantic_role: str | None = None
    limit_status: LimitStatus | None = None
