from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from context_stat.domain.content import (
    ContentItem,
    ContentKind,
    ImagePayload,
    StructuredPayload,
    TextPayload,
)
from context_stat.domain.errors import ContextStatError
from context_stat.domain.measurement import (
    LimitStatus,
    MeasuredItem,
    MeasurementOptions,
    MetricValue,
)
from context_stat.domain.parallel import ordered_map


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class MeasurementService:
    def __init__(self, token_counter: Any, image_analyzer: Any, image_estimator: Any) -> None:
        self._token_counter = token_counter
        self._image_analyzer = image_analyzer
        self._image_estimator = image_estimator

    def measure_items(
        self,
        items: Iterable[ContentItem],
        options: MeasurementOptions,
        *,
        parallel: int = 1,
    ) -> list[MeasuredItem]:
        values = list(items)
        return ordered_map(
            lambda item: self.measure_item(item, options),
            values,
            parallel,
        )

    def measure_item(self, item: ContentItem, options: MeasurementOptions) -> MeasuredItem:
        if item.kind is ContentKind.TEXT:
            metrics = self._measure_text(item.payload, options)
            limit_status = None
        elif item.kind is ContentKind.STRUCTURED:
            metrics = self._measure_structured(item.payload, options)
            limit_status = None
        elif item.kind is ContentKind.IMAGE:
            metrics, limit_status = self._measure_image(item.payload, options)
        else:
            metrics = {"bytes": MetricValue.skip(reason="unknown content kind")}
            limit_status = None

        if "path" in item.metadata and "path_length" in options.metrics:
            metrics["path_length"] = MetricValue.exact(len(str(item.metadata["path"])))

        return MeasuredItem(
            item_id=item.item_id,
            origin=item.origin,
            label=item.label,
            kind=item.kind.value,
            metrics=metrics,
            metadata=item.metadata,
            direction=item.direction,
            semantic_role=item.semantic_role,
            limit_status=limit_status,
        )

    def _measure_text(
        self, payload: TextPayload, options: MeasurementOptions
    ) -> dict[str, MetricValue]:
        metrics: dict[str, MetricValue] = {}
        if "bytes" in options.metrics:
            metrics["bytes"] = MetricValue.exact(len(payload.raw), unit="bytes")
        if payload.text is None:
            reason = payload.decode_error or "text decoding failed"
            if "characters" in options.metrics:
                metrics["characters"] = MetricValue.failed(unit="characters", reason=reason)
            if "lines" in options.metrics:
                metrics["lines"] = MetricValue.failed(unit="lines", reason=reason)
            if "max_line_length" in options.metrics:
                metrics["max_line_length"] = MetricValue.failed(unit="characters", reason=reason)
            if "tokens" in options.metrics:
                metrics["tokens"] = MetricValue.failed(unit="tokens", reason=reason)
            return metrics

        if "characters" in options.metrics:
            metrics["characters"] = MetricValue.exact(len(payload.text), unit="characters")
        if {"lines", "max_line_length"} & options.metrics:
            lines = payload.text.splitlines()
            if "lines" in options.metrics:
                metrics["lines"] = MetricValue.exact(len(lines), unit="lines")
            if "max_line_length" in options.metrics:
                metrics["max_line_length"] = MetricValue.exact(
                    max((len(line) for line in lines), default=0), unit="characters"
                )
        if "tokens" in options.metrics:
            metrics["tokens"] = self._safe_token_count(payload.text, options)
        return metrics

    def _measure_structured(
        self, payload: StructuredPayload, options: MeasurementOptions
    ) -> dict[str, MetricValue]:
        selected = options.metrics & {
            "bytes",
            "characters",
            "lines",
            "max_line_length",
            "tokens",
        }
        if not selected:
            return {}
        try:
            text = canonical_json(payload.value)
        except (TypeError, ValueError) as exc:
            reason = f"structured value is not JSON serializable: {exc}"
            return {
                name: MetricValue.failed(
                    unit="characters" if name in {"characters", "max_line_length"} else name,
                    reason=reason,
                )
                for name in selected
            }
        metrics: dict[str, MetricValue] = {}
        if "bytes" in selected:
            metrics["bytes"] = MetricValue.exact(len(text.encode("utf-8")), unit="bytes")
        if "characters" in selected:
            metrics["characters"] = MetricValue.exact(len(text), unit="characters")
        if {"lines", "max_line_length"} & selected:
            lines = text.splitlines()
            if "lines" in selected:
                metrics["lines"] = MetricValue.exact(len(lines), unit="lines")
            if "max_line_length" in selected:
                metrics["max_line_length"] = MetricValue.exact(
                    max((len(line) for line in lines), default=0),
                    unit="characters",
                )
        if "tokens" in selected:
            metrics["tokens"] = self._safe_token_count(text, options)
        return metrics

    def _safe_token_count(self, text: str, options: MeasurementOptions) -> MetricValue:
        try:
            return self._token_counter.count(
                text,
                backend=options.backend,
                tokenizer=options.text_tokenizer,
                allow_online=options.allow_online,
            )
        except (ContextStatError, ValueError) as exc:
            return MetricValue.failed(unit="tokens", reason=str(exc))

    def _measure_image(
        self, payload: ImagePayload, options: MeasurementOptions
    ) -> tuple[dict[str, MetricValue], LimitStatus | None]:
        metrics: dict[str, MetricValue] = {}
        if "bytes" in options.metrics:
            metrics["bytes"] = MetricValue.exact(len(payload.data), unit="bytes")
        metadata_metrics = tuple(
            name for name in ("width", "height", "frames") if name in options.metrics
        )
        need_image_metadata = bool(metadata_metrics or "image_tokens" in options.metrics)
        if not need_image_metadata:
            return metrics, None
        try:
            metadata = self._image_analyzer.read(payload.data)
        except ContextStatError as exc:
            for name in metadata_metrics:
                unit = "pixels" if name in {"width", "height"} else "frames"
                metrics[name] = MetricValue.failed(unit=unit, reason=str(exc))
            if "image_tokens" in options.metrics:
                metrics["image_tokens"] = MetricValue.skip(
                    unit="tokens",
                    reason=f"image could not be read; image tokens skipped: {exc}",
                )
            return metrics, LimitStatus.UNKNOWN

        if "width" in options.metrics:
            metrics["width"] = MetricValue.exact(metadata.width, unit="pixels")
        if "height" in options.metrics:
            metrics["height"] = MetricValue.exact(metadata.height, unit="pixels")
        if "frames" in options.metrics:
            metrics["frames"] = MetricValue.exact(metadata.frames, unit="frames")
        if "image_tokens" not in options.metrics:
            return metrics, LimitStatus.UNKNOWN
        if options.image_tokenizer == "anthropic-api":
            metrics["image_tokens"] = self._safe_image_token_count(
                payload,
                metadata.media_type,
                options,
            )
            return metrics, LimitStatus.UNKNOWN
        image_result = self._image_estimator.estimate(metadata, options.image_tokenizer)
        metrics["image_tokens"] = image_result.metric
        return metrics, image_result.limit_status

    def _safe_image_token_count(
        self,
        payload: ImagePayload,
        media_type: str,
        options: MeasurementOptions,
    ) -> MetricValue:
        try:
            return self._token_counter.count_image(
                payload.data,
                model=options.text_tokenizer,
                media_type=media_type,
                allow_online=options.allow_online,
            )
        except (ContextStatError, ValueError) as exc:
            return MetricValue.failed(unit="tokens", reason=str(exc))
