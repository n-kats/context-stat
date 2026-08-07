from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

type JSONValue = Any


class ContentKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    STRUCTURED = "structured"


@dataclass(frozen=True)
class TextPayload:
    raw: bytes
    text: str | None
    encoding: str | None = None
    decode_error: str | None = None


@dataclass(frozen=True)
class ImagePayload:
    data: bytes
    media_type: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class StructuredPayload:
    value: JSONValue
    representation: str = "canonical-json"


type Payload = TextPayload | ImagePayload | StructuredPayload


@dataclass(frozen=True)
class ContentItem:
    item_id: str
    origin: str
    label: str
    kind: ContentKind
    payload: Payload
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    direction: str | None = None
    semantic_role: str | None = None


@dataclass(frozen=True)
class ContentBundle:
    items: tuple[ContentItem, ...]
    facts: dict[str, JSONValue] = field(default_factory=dict)
