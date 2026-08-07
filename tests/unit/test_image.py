from __future__ import annotations

import io

import pytest
from PIL import Image

from context_stat.adapters.image import ImageMetadata, ImageTokenEstimator
from context_stat.domain.errors import ContextStatError
from context_stat.domain.measurement import LimitStatus, MeasurementStatus


def metadata(
    *,
    width: int,
    height: int,
    image_format: str = "PNG",
    size_bytes: int = 100,
    frames: int = 1,
) -> ImageMetadata:
    return ImageMetadata(
        size_bytes=size_bytes,
        media_type="image/png",
        format=image_format,
        width=width,
        height=height,
        frames=frames,
        mode="RGB",
    )


def test_gpt56_style_image_tokens_use_original_32px_patches() -> None:
    result = ImageTokenEstimator().estimate(metadata(width=32, height=32))

    assert result.metric.value == 1
    assert result.metric.status is MeasurementStatus.MEASURED
    assert result.metric.method == "openai-gpt-5.6-patch32"
    assert result.limit_status is LimitStatus.WITHIN
    assert result.metric.details["original_patch_count"] == 1
    assert result.metric.details["resized"] is False
    assert result.metric.details["image_tokenizer"] == "gpt-5.6-style"


def test_gpt56_style_image_tokens_round_up_each_dimension() -> None:
    result = ImageTokenEstimator().estimate(metadata(width=33, height=65))

    assert result.metric.value == 6
    assert result.metric.details["patch_width"] == 2
    assert result.metric.details["patch_height"] == 3


def test_gpt56_style_image_policy_skips_unsupported_format() -> None:
    result = ImageTokenEstimator().estimate(metadata(width=32, height=32, image_format="TIFF"))

    assert result.metric.value is None
    assert result.metric.status is MeasurementStatus.SKIP
    assert result.limit_status is LimitStatus.UNKNOWN
    assert "TIFF" in result.metric.reason


def test_gpt56_style_image_policy_skips_animated_gif() -> None:
    result = ImageTokenEstimator().estimate(
        metadata(width=32, height=32, image_format="GIF", frames=2)
    )

    assert result.metric.status is MeasurementStatus.SKIP
    assert result.limit_status is LimitStatus.UNKNOWN
    assert "animated GIF" in result.metric.reason


def test_gpt56_style_image_policy_reports_payload_limit() -> None:
    result = ImageTokenEstimator().estimate(
        metadata(width=32, height=32, size_bytes=512 * 1024 * 1024 + 1)
    )

    assert result.metric.value == 1
    assert result.limit_status is LimitStatus.OVER


def test_unknown_image_tokenizer_is_skipped() -> None:
    result = ImageTokenEstimator().estimate(metadata(width=32, height=32), "future-style")

    assert result.metric.status is MeasurementStatus.SKIP
    assert result.metric.reason == "image tokenizer 'future-style' is not implemented"


def test_image_metadata_reader_rejects_truncated_image() -> None:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), color="white").save(output, format="PNG")

    from context_stat.adapters.image import ImageMetadataReader

    with pytest.raises(ContextStatError) as error:
        ImageMetadataReader().read(output.getvalue()[:-8])

    assert str(error.value) == "image metadata could not be read"
