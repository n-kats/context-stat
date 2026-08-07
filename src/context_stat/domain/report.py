from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from context_stat.domain.measurement import MeasuredItem, MetricValue


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    item_id: str | None = None


@dataclass
class MeasurementGroup:
    name: str
    items: list[MeasuredItem] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def totals(self) -> dict[str, MetricValue]:
        additive_metrics = {
            "bytes",
            "characters",
            "lines",
            "tokens",
            "path_length",
            "image_tokens",
            "frames",
        }
        totals: dict[str, MetricValue] = {}
        for item in self.items:
            for name, metric in item.metrics.items():
                if metric.status.value != "measured" or metric.value is None:
                    continue
                if name not in additive_metrics and name != "max_line_length":
                    continue
                current = totals.get(name)
                if current is None:
                    totals[name] = metric
                elif current.value is not None:
                    if name == "max_line_length":
                        value = max(current.value, metric.value)
                        method = "max"
                    else:
                        value = current.value + metric.value
                        method = "sum"
                    totals[name] = MetricValue(
                        value=value,
                        unit=metric.unit,
                        status=metric.status,
                        method=method,
                        external=(
                            current.external if current.external == metric.external else None
                        ),
                    )
        return totals


@dataclass
class MeasurementReport:
    source: str
    request: dict[str, Any]
    groups: list[MeasurementGroup] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    warnings: list[Issue] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)
