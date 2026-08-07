from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from context_stat.domain.errors import ContextStatError
from context_stat.domain.measurement import LimitStatus, MetricValue

DEFAULT_IMAGE_TOKENIZER = "gpt-5.6-style"
_GPT56_PATCH_SIZE = 32
_GPT56_MAX_REQUEST_BYTES = 512 * 1024 * 1024
_GPT56_SUPPORTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF"})


@dataclass(frozen=True)
class ImageMetadata:
    size_bytes: int
    media_type: str
    format: str
    width: int
    height: int
    frames: int
    mode: str


@dataclass(frozen=True)
class ImageTokenResult:
    metric: MetricValue
    limit_status: LimitStatus


class ImageMetadataReader:
    def read(self, data: bytes) -> ImageMetadata:
        try:
            with Image.open(io.BytesIO(data)) as image:
                frames = getattr(image, "n_frames", 1)
                image_format = (image.format or "").upper()
                media_type = Image.MIME.get(image_format, "application/octet-stream")
                image.verify()
                return ImageMetadata(
                    size_bytes=len(data),
                    media_type=media_type,
                    format=image_format,
                    width=image.width,
                    height=image.height,
                    frames=frames,
                    mode=image.mode,
                )
        except (
            DecompressionBombError,
            EOFError,
            OSError,
            SyntaxError,
            UnidentifiedImageError,
            ValueError,
        ) as exc:
            raise ContextStatError("image metadata could not be read") from exc


class ImageTokenEstimator:
    """Image-token policy resolver; no image resampling is performed."""

    def estimate(
        self,
        metadata: ImageMetadata,
        tokenizer: str = DEFAULT_IMAGE_TOKENIZER,
    ) -> ImageTokenResult:
        common_details = {
            "provider": "openai",
            "image_tokenizer": tokenizer,
            "detail": "auto/original",
            "original_width": metadata.width,
            "original_height": metadata.height,
            "format": metadata.format,
            "frames": metadata.frames,
        }
        if tokenizer != DEFAULT_IMAGE_TOKENIZER:
            return ImageTokenResult(
                MetricValue.skip(
                    unit="tokens",
                    reason=f"image tokenizer {tokenizer!r} is not implemented",
                    details=common_details,
                ),
                LimitStatus.UNKNOWN,
            )

        if metadata.format not in _GPT56_SUPPORTED_FORMATS:
            return ImageTokenResult(
                MetricValue.skip(
                    unit="tokens",
                    reason=(
                        f"image format {metadata.format or '<unknown>'!r} is not supported "
                        "by the GPT-5.6 image input policy"
                    ),
                    details=common_details,
                ),
                LimitStatus.UNKNOWN,
            )
        if metadata.format == "GIF" and metadata.frames != 1:
            return ImageTokenResult(
                MetricValue.skip(
                    unit="tokens",
                    reason="animated GIF is not supported by the GPT-5.6 image input policy",
                    details=common_details,
                ),
                LimitStatus.UNKNOWN,
            )
        if metadata.width < 1 or metadata.height < 1:
            return ImageTokenResult(
                MetricValue.failed(
                    unit="tokens",
                    reason="image dimensions must be positive",
                    details=common_details,
                ),
                LimitStatus.UNKNOWN,
            )

        patch_width = (metadata.width + _GPT56_PATCH_SIZE - 1) // _GPT56_PATCH_SIZE
        patch_height = (metadata.height + _GPT56_PATCH_SIZE - 1) // _GPT56_PATCH_SIZE
        patch_count = patch_width * patch_height
        limit_status = (
            LimitStatus.OVER
            if metadata.size_bytes > _GPT56_MAX_REQUEST_BYTES
            else LimitStatus.WITHIN
        )
        details = {
            **common_details,
            "patch_size": _GPT56_PATCH_SIZE,
            "patch_width": patch_width,
            "patch_height": patch_height,
            "original_patch_count": patch_count,
            "resized": False,
            "max_request_bytes": _GPT56_MAX_REQUEST_BYTES,
            "limit_status": limit_status.value,
        }
        return ImageTokenResult(
            MetricValue.exact(
                patch_count,
                unit="tokens",
                method="openai-gpt-5.6-patch32",
                external=False,
                details=details,
            ),
            limit_status,
        )
