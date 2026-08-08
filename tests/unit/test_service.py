from __future__ import annotations

import io

from PIL import Image

from context_stat.adapters.image import ImageMetadataReader, ImageTokenEstimator
from context_stat.domain.content import ContentItem, ContentKind, ImagePayload, TextPayload
from context_stat.domain.errors import ContextStatError
from context_stat.domain.measurement import (
    ALL_METRICS,
    MeasurementOptions,
    MetricValue,
    parse_metric_selection,
)
from context_stat.domain.service import MeasurementService


class FakeTokenCounter:
    def count(self, text: str, **_: object) -> MetricValue:
        return MetricValue.exact(len(text.split()), unit="tokens", method="test")


class FailingImageAnalyzer:
    def read(self, _data: bytes) -> None:
        raise ContextStatError("image metadata could not be read")


def make_service() -> MeasurementService:
    return MeasurementService(
        token_counter=FakeTokenCounter(),
        image_analyzer=ImageMetadataReader(),
        image_estimator=ImageTokenEstimator(),
    )


def test_metric_selection_supports_token_all_and_multiple_values() -> None:
    assert parse_metric_selection("token") == {"tokens", "image_tokens"}
    assert parse_metric_selection("token,bytes") == {"tokens", "image_tokens", "bytes"}
    assert parse_metric_selection("all") == ALL_METRICS


def test_text_metrics_are_measured_separately() -> None:
    item = ContentItem(
        item_id="text:1",
        origin="test",
        label="example",
        kind=ContentKind.TEXT,
        payload=TextPayload(b"hello world\nagain", "hello world\nagain", "utf-8"),
    )

    measured = make_service().measure_item(
        item,
        MeasurementOptions(metrics=ALL_METRICS),
    )

    assert measured.metrics["bytes"].value == 17
    assert measured.metrics["characters"].value == 17
    assert measured.metrics["lines"].value == 2
    assert measured.metrics["tokens"].value == 3
    assert measured.metrics["tokens"].method == "test"


def test_image_metadata_and_default_tokenizer_policy() -> None:
    output = io.BytesIO()
    Image.new("RGB", (32, 16), color="white").save(output, format="PNG")
    item = ContentItem(
        item_id="image:1",
        origin="test",
        label="image.png",
        kind=ContentKind.IMAGE,
        payload=ImagePayload(output.getvalue(), source="image.png"),
    )

    measured = make_service().measure_item(
        item,
        MeasurementOptions(metrics=ALL_METRICS),
    )

    assert measured.metrics["width"].value == 32
    assert measured.metrics["height"].value == 16
    assert measured.metrics["image_tokens"].value == 1
    assert measured.metrics["image_tokens"].status.value == "measured"
    assert measured.limit_status.value == "within"


def test_image_anthropic_backend_uses_online_token_counter() -> None:
    output = io.BytesIO()
    Image.new("RGB", (32, 16), color="white").save(output, format="PNG")

    class OnlineTokenCounter(FakeTokenCounter):
        def count_image(self, data: bytes, **kwargs: object) -> MetricValue:
            assert data == output.getvalue()
            assert kwargs == {
                "model": "claude-sonnet-5",
                "media_type": "image/png",
                "allow_online": True,
            }
            return MetricValue.exact(
                19,
                unit="tokens",
                method="anthropic-api:claude-sonnet-5",
                external=True,
            )

    item = ContentItem(
        item_id="image:online",
        origin="test",
        label="image.png",
        kind=ContentKind.IMAGE,
        payload=ImagePayload(output.getvalue(), source="image.png"),
    )
    service = MeasurementService(
        token_counter=OnlineTokenCounter(),
        image_analyzer=ImageMetadataReader(),
        image_estimator=ImageTokenEstimator(),
    )

    measured = service.measure_item(
        item,
        MeasurementOptions(
            text_tokenizer="claude-sonnet-5",
            image_tokenizer="anthropic-api",
            allow_online=True,
            metrics=frozenset({"image_tokens"}),
        ),
    )

    assert measured.metrics["image_tokens"].value == 19
    assert measured.metrics["image_tokens"].external is True


def test_failed_image_metrics_are_inserted_in_a_stable_order() -> None:
    item = ContentItem(
        item_id="image:failed",
        origin="test",
        label="broken.png",
        kind=ContentKind.IMAGE,
        payload=ImagePayload(b"broken", source="broken.png"),
    )
    service = MeasurementService(
        token_counter=FakeTokenCounter(),
        image_analyzer=FailingImageAnalyzer(),
        image_estimator=ImageTokenEstimator(),
    )

    measured = service.measure_item(
        item,
        MeasurementOptions(metrics=frozenset({"frames", "image_tokens", "height", "width"})),
    )

    assert list(measured.metrics) == ["width", "height", "frames", "image_tokens"]
