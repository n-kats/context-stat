from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import asdict, dataclass, field
from functools import cmp_to_key
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text
from rich.tree import Tree

from context_stat.domain.measurement import MeasuredItem, MeasurementStatus, MetricValue
from context_stat.domain.report import Issue, MeasurementGroup, MeasurementReport

_METRIC_ORDER = (
    "bytes",
    "characters",
    "lines",
    "max_line_length",
    "tokens",
    "image_tokens",
    "width",
    "height",
    "frames",
    "path_length",
)
_METRIC_LABELS = {
    "max_line_length": "max-line-length",
    "image_tokens": "image-tokens",
    "path_length": "path-length",
}


def metric_to_dict(metric: MetricValue) -> dict[str, Any]:
    result: dict[str, Any] = {
        "value": metric.value,
        "unit": metric.unit,
        "status": metric.status.value,
        "external": metric.external,
    }
    if metric.method is not None:
        result["method"] = metric.method
    if metric.reason is not None:
        result["reason"] = metric.reason
    if metric.details:
        result["details"] = metric.details
    return result


def report_to_dict(
    report: MeasurementReport,
    *,
    include_issues: bool = True,
    verbose: bool = False,
) -> dict[str, Any]:
    facts = _report_facts(report, verbose=verbose)
    groups = []
    for group in report.groups:
        items = _ordered_items(group, report.request)
        group_data: dict[str, Any] = {
            "name": group.name,
            "items": [_item_to_dict(item) for item in items],
            "facts": group.facts,
        }
        nodes = _ordered_path_nodes(group, report.request)
        if nodes is not None:
            group_data["nodes"] = [_node_to_dict(node) for node in nodes]
        else:
            summary = group.totals()
            if summary:
                group_data["summary"] = {
                    name: metric_to_dict(metric) for name, metric in summary.items()
                }
        groups.append(group_data)
    return {
        "schema_version": 1,
        "source": report.source,
        "request": report.request,
        "groups": groups,
        "facts": facts,
        "warnings": [asdict(issue) for issue in report.warnings] if include_issues else [],
        "errors": [asdict(issue) for issue in report.errors] if include_issues else [],
    }


def render_report(
    report: MeasurementReport,
    output_format: str,
    *,
    include_issues: bool = True,
    verbose: bool = False,
) -> str:
    data = report_to_dict(report, include_issues=include_issues, verbose=verbose)
    if output_format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    if output_format == "tree":
        return _render_tree(report, include_issues=include_issues, verbose=verbose)
    if output_format not in {"table", "human"}:
        raise ValueError(f"unsupported output format: {output_format}")
    return _render_table(report, include_issues=include_issues, verbose=verbose)


def _render_table(report: MeasurementReport, *, include_issues: bool, verbose: bool) -> str:
    lines = [f"source: {report.source}"]
    for group in report.groups:
        lines.append(f"[{group.name}]")
        totals = group.totals()
        nodes = _ordered_path_nodes(group, report.request)
        requested = report.request.get("metrics")
        empty_directory = bool(
            nodes
            and not group.items
            and any(node.is_directory for node in nodes)
            and isinstance(requested, list)
        )
        metric_names = _metric_names(
            group,
            totals,
            requested=requested if empty_directory else None,
        )
        if not metric_names:
            lines.append("(no selected metrics)")
            continue
        if nodes is not None:
            rows = [
                [
                    _node_path(node),
                    _node_kind(node),
                    *(_metric_cell(node.metrics.get(name)) for name in metric_names),
                ]
                for node in nodes
            ]
            headers = ["path", "kind", *(_METRIC_LABELS.get(name, name) for name in metric_names)]
            alignments = ["left", "left", *(["right"] * len(metric_names))]
        else:
            items = _ordered_items(group, report.request)
            detail_columns = _mcp_detail_columns(report, group, items)
            rows = [
                [
                    item.label,
                    *(_mcp_detail_value(item, column) for column in detail_columns),
                    *(_metric_cell(item.metrics.get(name)) for name in metric_names),
                ]
                for item in items
            ]
            if totals:
                rows.insert(
                    0,
                    [
                        group.name,
                        *("" for _ in detail_columns),
                        *(_metric_cell(totals.get(name)) for name in metric_names),
                    ],
                )
            headers = [
                "item",
                *detail_columns,
                *(_METRIC_LABELS.get(name, name) for name in metric_names),
            ]
            alignments = [
                "left",
                *("left" for _ in detail_columns),
                *("right" for _ in metric_names),
            ]
        lines.extend(_ascii_table(headers, rows, alignments=alignments))
    lines.extend(_render_mcp_result(report, verbose=verbose))
    if include_issues:
        lines.extend(_render_issues(report))
    return "\n".join(lines)


@dataclass
class _TreeNode:
    label: str
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    children: list[_TreeNode] = field(default_factory=list)
    is_directory: bool = False
    display_path: str | None = None
    item: MeasuredItem | None = None


def _render_tree(report: MeasurementReport, *, include_issues: bool, verbose: bool) -> str:
    sort_by, order = _sort_config(report.request)
    roots: list[_TreeNode] = []
    for group in report.groups:
        path_roots = _sorted_path_nodes(group, report.request)
        if path_roots is not None:
            roots.extend(path_roots)
        else:
            roots.append(_generic_tree(group, report.request))

    if not roots:
        lines = [f"source: {report.source}", "(no selected metrics)"]
    else:
        _sort_tree_nodes(roots, sort_by, order)
        tree = Tree(Text(f"source: {report.source}"))
        for root in roots:
            _add_rich_tree_node(tree, root)
        result = _mcp_result(report)
        if result:
            result_node = tree.add(Text(f"result: {result['status']}"))
            if verbose:
                _add_result_value_tree(result_node, result.get("value"))
        buffer = StringIO()
        Console(
            file=buffer,
            color_system=None,
            force_terminal=False,
            no_color=True,
            width=4096,
        ).print(tree, end="")
        lines = buffer.getvalue().rstrip("\n").splitlines()
    if include_issues:
        lines.extend(_render_issues(report))
    return "\n".join(lines)


def _report_facts(report: MeasurementReport, *, verbose: bool) -> dict[str, Any]:
    if verbose or report.source != "mcp-request":
        return report.facts
    result = report.facts.get("result")
    if not isinstance(result, dict) or "value" not in result:
        return report.facts
    facts = dict(report.facts)
    facts["result"] = {key: value for key, value in result.items() if key != "value"}
    return facts


def _mcp_result(report: MeasurementReport) -> dict[str, Any] | None:
    if report.source != "mcp-request":
        return None
    result = report.facts.get("result")
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    items = result.get("items")
    if not isinstance(status, str) or not isinstance(items, list):
        return None
    return {"status": status, "items": items, "value": result.get("value")}


def _add_result_value_tree(parent: Tree, value: Any) -> None:
    if isinstance(value, dict):
        node = parent.add(Text("response"))
        for key, entry in value.items():
            _add_result_value_tree_entry(node, str(key), entry)
        return
    parent.add(Text(f"response: {json.dumps(value, ensure_ascii=False)}"))


def _add_result_value_tree_entry(parent: Tree, label: str, value: Any) -> None:
    if isinstance(value, dict):
        node = parent.add(Text(label))
        for key, entry in value.items():
            _add_result_value_tree_entry(node, str(key), entry)
        return
    if isinstance(value, list):
        node = parent.add(Text(label))
        for index, entry in enumerate(value):
            _add_result_value_tree_entry(node, f"[{index}]", entry)
        return
    parent.add(Text(f"{label}: {json.dumps(value, ensure_ascii=False)}"))


def _mcp_result_item_text(item: Any) -> str:
    if not isinstance(item, dict):
        return "unknown"
    label = str(item.get("label", "result"))
    kind = str(item.get("kind", "structured"))
    if kind != "image":
        return f"{label}: {kind}"
    media_type = str(item.get("media_type") or "image")
    dimensions = item.get("dimensions")
    if isinstance(dimensions, dict):
        width = dimensions.get("width")
        height = dimensions.get("height")
        if isinstance(width, int) and isinstance(height, int):
            size = f"{width}x{height}"
        else:
            size = "dimensions=unknown"
    else:
        size = "dimensions=unknown"
    frames = item.get("frames")
    frame_suffix = f", {frames} frames" if isinstance(frames, int) and frames != 1 else ""
    return f"{label}: {media_type} {size}{frame_suffix}"


def _render_mcp_result(report: MeasurementReport, *, verbose: bool) -> list[str]:
    result = _mcp_result(report)
    if result is None:
        return []
    lines = [f"result: {result['status']}"]
    if not verbose:
        return lines
    lines.append("response:")
    value = result.get("value")
    if value is not None:
        rendered = json.dumps(value, ensure_ascii=False, indent=2)
        lines.extend(f"  {line}" for line in rendered.splitlines())
    else:
        lines.extend(f"  {_mcp_result_item_text(item)}" for item in result["items"])
    return lines


def _add_rich_tree_node(parent: Tree, node: _TreeNode) -> None:
    child = parent.add(Text(_tree_label(node)))
    for grandchild in node.children:
        _add_rich_tree_node(child, grandchild)


def _tree_label(node: _TreeNode) -> str:
    return f"{node.label} [{_tree_summary(node.metrics)}]"


def _item_to_dict(item: MeasuredItem) -> dict[str, Any]:
    return {
        "id": item.item_id,
        "origin": item.origin,
        "label": item.label,
        "kind": item.kind,
        "direction": item.direction,
        "semantic_role": item.semantic_role,
        "limit_status": item.limit_status.value if item.limit_status is not None else None,
        "metrics": {name: metric_to_dict(metric) for name, metric in item.metrics.items()},
        "metadata": item.metadata,
    }


def _node_to_dict(node: _TreeNode) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _node_path(node),
        "kind": _node_kind(node),
        "metrics": {name: metric_to_dict(metric) for name, metric in node.metrics.items()},
    }
    if node.item is not None:
        result["item"] = _item_to_dict(node.item)
    return result


def _node_path(node: _TreeNode) -> str:
    return node.display_path or node.label


def _node_kind(node: _TreeNode) -> str:
    return "dir" if node.is_directory or node.children else "file"


def _flatten_tree(nodes: list[_TreeNode]) -> list[_TreeNode]:
    flattened: list[_TreeNode] = []
    for node in nodes:
        flattened.append(node)
        flattened.extend(_flatten_tree(node.children))
    return flattened


def _sorted_path_nodes(group: MeasurementGroup, request: dict[str, Any]) -> list[_TreeNode] | None:
    nodes = _path_tree(group, request)
    if nodes is None:
        return None
    sort_by, order = _sort_config(request)
    _sort_tree_nodes(nodes, sort_by, order)
    return nodes


def _ordered_path_nodes(group: MeasurementGroup, request: dict[str, Any]) -> list[_TreeNode] | None:
    nodes = _path_tree(group, request)
    if nodes is None:
        return None
    sort_by, order = _sort_config(request)
    return sorted(
        _flatten_tree(nodes),
        key=cmp_to_key(
            lambda left, right: _compare_records(
                _node_path(left),
                left.metrics,
                _node_path(right),
                right.metrics,
                sort_by,
                order,
            )
        ),
    )


def _generic_tree(group: MeasurementGroup, request: dict[str, Any]) -> _TreeNode:
    return _TreeNode(
        label=group.name,
        metrics=group.totals(),
        children=[
            _TreeNode(item.label, dict(item.metrics), display_path=_item_path(item), item=item)
            for item in _ordered_items(group, request)
        ],
    )


def _path_tree(group: MeasurementGroup, request: dict[str, Any]) -> list[_TreeNode] | None:
    raw_paths = group.facts.get("input_paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return None
    path_items = {
        item.item_id: (_lexical_absolute(Path(str(item.metadata["path"]))), item)
        for item in _ordered_items(group, request)
        if isinstance(item.metadata.get("path"), str)
    }
    roots: list[_TreeNode] = []
    assigned: set[str] = set()
    seen_roots: set[Path] = set()
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or raw_path == "-":
            continue
        input_path = Path(raw_path)
        absolute_input = _lexical_absolute(input_path)
        if absolute_input in seen_roots:
            continue
        seen_roots.add(absolute_input)
        if input_path.is_dir():
            root = _TreeNode(
                str(input_path),
                is_directory=True,
                display_path=str(input_path),
            )
            descendants: list[MeasuredItem] = []
            for item_id, (item_path, item) in path_items.items():
                try:
                    relative = item_path.relative_to(absolute_input)
                except ValueError:
                    continue
                _insert_tree_item(root, relative.parts, item)
                descendants.append(item)
                assigned.add(item_id)
            root.metrics = _aggregate_tree_items(descendants)
            roots.append(root)
            continue

        for item_id, (item_path, item) in path_items.items():
            if item_id in assigned or item_path != absolute_input:
                continue
            roots.append(
                _TreeNode(
                    item.label,
                    dict(item.metrics),
                    display_path=item.label,
                    item=item,
                )
            )
            assigned.add(item_id)
            break

    for item_id, (_, item) in path_items.items():
        if item_id not in assigned:
            roots.append(
                _TreeNode(
                    item.label,
                    dict(item.metrics),
                    display_path=item.label,
                    item=item,
                )
            )
    return roots


def _lexical_absolute(path: Path) -> Path:
    """Normalize ``..`` without resolving symlinks in a displayed path."""
    return Path(os.path.abspath(path))


def _sort_config(request: dict[str, Any]) -> tuple[str, str]:
    return str(request.get("sort", "path")), str(request.get("order", "asc"))


def _item_path(item: MeasuredItem) -> str:
    value = item.metadata.get("path")
    return str(value) if isinstance(value, str) else item.label


def _ordered_items(group: MeasurementGroup, request: dict[str, Any]) -> list[MeasuredItem]:
    sort_by, order = _sort_config(request)
    return sorted(
        group.items,
        key=cmp_to_key(
            lambda left, right: _compare_records(
                _item_path(left),
                left.metrics,
                _item_path(right),
                right.metrics,
                sort_by,
                order,
            )
        ),
    )


def _sort_tree_nodes(nodes: list[_TreeNode], sort_by: str, order: str) -> None:
    nodes.sort(
        key=cmp_to_key(
            lambda left, right: _compare_records(
                left.display_path or left.label,
                left.metrics,
                right.display_path or right.label,
                right.metrics,
                sort_by,
                order,
            )
        )
    )
    for node in nodes:
        _sort_tree_nodes(node.children, sort_by, order)


def _compare_records(
    left_path: str,
    left_metrics: dict[str, MetricValue],
    right_path: str,
    right_metrics: dict[str, MetricValue],
    sort_by: str,
    order: str,
) -> int:
    left_value = left_path if sort_by == "path" else _metric_sort_value(left_metrics, sort_by)
    right_value = right_path if sort_by == "path" else _metric_sort_value(right_metrics, sort_by)
    left_missing = left_value is None
    right_missing = right_value is None
    if left_missing != right_missing:
        return 1 if left_missing else -1
    if not left_missing and left_value != right_value:
        result = -1 if left_value < right_value else 1
        return result if order == "asc" else -result
    if left_path == right_path:
        return 0
    return -1 if left_path < right_path else 1


def _metric_sort_value(metrics: dict[str, MetricValue], name: str) -> int | float | None:
    metric = metrics.get(name)
    if metric is None or metric.status is not MeasurementStatus.MEASURED:
        return None
    return metric.value


def _insert_tree_item(node: _TreeNode, parts: tuple[str, ...], item: MeasuredItem) -> None:
    if not parts:
        node.metrics = dict(item.metrics)
        return
    label = parts[0]
    child = next((candidate for candidate in node.children if candidate.label == label), None)
    if child is None:
        display_path = str(Path(node.display_path or node.label) / label)
        child = _TreeNode(
            label,
            is_directory=len(parts) > 1,
            display_path=display_path,
        )
        node.children.append(child)
    if len(parts) == 1:
        child.metrics = dict(item.metrics)
        child.is_directory = False
        child.item = item
        return
    _insert_tree_item(child, parts[1:], item)
    child.metrics = _aggregate_tree_leaves(child)


def _aggregate_tree_items(items: list[MeasuredItem]) -> dict[str, MetricValue]:
    return MeasurementGroup("tree", items).totals()


def _aggregate_tree_leaves(node: _TreeNode) -> dict[str, MetricValue]:
    leaves: list[MeasuredItem] = []
    _collect_tree_leaves(node, leaves)
    return _aggregate_tree_items(leaves)


def _collect_tree_leaves(node: _TreeNode, leaves: list[MeasuredItem]) -> None:
    if not node.children:
        if node.item is not None:
            leaves.append(node.item)
        return
    for child in node.children:
        _collect_tree_leaves(child, leaves)


def _metric_names(
    group: Any,
    totals: dict[str, MetricValue],
    extra: dict[str, MetricValue] | None = None,
    requested: Any = None,
) -> list[str]:
    names = set(totals)
    names.update(extra or {})
    if isinstance(requested, list):
        names.update(name for name in requested if isinstance(name, str))
    for item in group.items:
        names.update(item.metrics)
    return [name for name in _METRIC_ORDER if name in names] + sorted(
        names.difference(_METRIC_ORDER)
    )


def _mcp_detail_columns(
    report: MeasurementReport, group: MeasurementGroup, items: list[MeasuredItem]
) -> list[str]:
    if report.source != "mcp-list":
        return []
    columns: list[str] = []
    if any(isinstance(item.metadata.get("mcp_description"), str) for item in items):
        columns.append("description")
    if group.name == "resources" and any(
        isinstance(item.metadata.get("mcp_uri"), str) and item.metadata["mcp_uri"] != item.label
        for item in items
    ):
        columns.append("uri")
    return columns


def _mcp_detail_value(item: MeasuredItem, column: str) -> str:
    value = item.metadata.get(f"mcp_{column}")
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _metric_cell(metric: MetricValue | None) -> str:
    return "-" if metric is None or metric.value is None else str(metric.value)


def _tree_summary(metrics: dict[str, MetricValue]) -> str:
    names = [name for name in _METRIC_ORDER if name in metrics]
    names.extend(sorted(set(metrics).difference(_METRIC_ORDER)))
    if not names:
        return "-"
    if len(names) == 1:
        return _tree_metric_value(metrics[names[0]])
    return ", ".join(
        f"{_METRIC_LABELS.get(name, name)}={_tree_metric_value(metrics[name])}" for name in names
    )


def _tree_metric_value(metric: MetricValue) -> str:
    return "-" if metric.value is None else f"{metric.value} {metric.unit}"


def _ascii_table(
    headers: list[str], rows: list[list[str]], *, alignments: list[str] | None = None
) -> list[str]:
    values = [headers, *rows]
    widths = [max(_display_width(row[index]) for row in values) for index in range(len(headers))]
    cell_alignments = alignments or ["left"] * len(headers)
    if len(cell_alignments) != len(headers):
        raise ValueError("table alignments must match the number of columns")
    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def render_row(row: list[str]) -> str:
        return (
            "| "
            + " | ".join(
                _pad_cell(cell, width, alignment)
                for cell, width, alignment in zip(row, widths, cell_alignments, strict=True)
            )
            + " |"
        )

    return [
        separator,
        render_row(headers),
        separator,
        *[render_row(row) for row in rows],
        separator,
    ]


def _display_width(value: str) -> int:
    width = 0
    for character in value:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def _pad_cell(value: str, width: int, alignment: str = "left") -> str:
    padding = " " * max(0, width - _display_width(value))
    if alignment == "right":
        return padding + value
    return value + padding


def _render_issues(report: MeasurementReport) -> list[str]:
    lines = []
    for issue in report.warnings:
        lines.append(f"warning [{issue.code}]{_issue_target(issue)}: {issue.message}")
    for issue in report.errors:
        lines.append(f"error [{issue.code}]{_issue_target(issue)}: {issue.message}")
    return lines


def render_diagnostics(report: MeasurementReport) -> str:
    return "\n".join(_render_issues(report))


def _issue_target(issue: Issue) -> str:
    if issue.item_id is None:
        return ""
    return f" [{issue.item_id}]"
