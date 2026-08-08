from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from jinja2 import TemplateError

from context_stat.adapters.filesystem import (
    collect_files,
    is_image_data,
    is_image_path,
    iter_selected_files,
    read_stdin_item,
)
from context_stat.adapters.git import GitArgumentError, parse_git_diff_args, run_git_diff
from context_stat.adapters.image import ImageMetadataReader, ImageTokenEstimator
from context_stat.adapters.mcp import (
    McpServerConfig,
    OfficialMcpSdkAdapter,
    jsonable,
    list_result_bundle,
    result_bundle,
)
from context_stat.adapters.process import CommandExecution, run_for_path
from context_stat.adapters.templating import render_template
from context_stat.adapters.token import TokenCounterResolver
from context_stat.domain.content import (
    ContentItem,
    ContentKind,
    ImagePayload,
    StructuredPayload,
    TextPayload,
)
from context_stat.domain.errors import ContextStatError
from context_stat.domain.measurement import (
    SORT_KEYS,
    MeasuredItem,
    MeasurementOptions,
    parse_metric_selection,
    parse_sort_selection,
)
from context_stat.domain.parallel import ordered_map
from context_stat.domain.report import Issue, MeasurementGroup, MeasurementReport
from context_stat.domain.service import MeasurementService
from context_stat.output import render_diagnostics, render_report


@dataclass(frozen=True)
class Runtime:
    options: MeasurementOptions
    verbose: bool = False

    def service(self) -> MeasurementService:
        return MeasurementService(
            token_counter=TokenCounterResolver(),
            image_analyzer=ImageMetadataReader(),
            image_estimator=ImageTokenEstimator(),
        )


_GIT_SEPARATOR = "\x00context-stat-git-separator\x00"


@dataclass(frozen=True)
class McpConnection:
    config: McpServerConfig
    config_path: Path | None
    source: str


class GitDiffCommand(click.Command):
    """Keep Git's ``--`` pathspec separator visible to the Git parser."""

    def parse_args(self, context: click.Context, args: list[str]) -> list[str]:
        preserved = [_GIT_SEPARATOR if arg == "--" else arg for arg in args]
        return super().parse_args(context, preserved)


def _runtime() -> Runtime:
    context = click.get_current_context()
    return context.find_root().obj


def _measurement_request() -> dict[str, Any]:
    options = _runtime().options
    return {
        "backend": options.backend,
        "text_tokenizer": options.text_tokenizer,
        "image_tokenizer": options.image_tokenizer,
        "allow_online": options.allow_online,
        "format": options.output_format,
        "metrics": sorted(options.metrics),
        "sort": options.sort,
        "order": options.order,
        "parallel": options.parallel,
        "verbose": _runtime().verbose,
    }


def _emit(report: MeasurementReport) -> None:
    click.echo(
        render_report(
            report,
            _runtime().options.output_format,
            include_issues=False,
            verbose=_runtime().verbose,
        )
    )
    diagnostics = render_diagnostics(report)
    if diagnostics:
        click.echo(diagnostics, err=True)
    if report.errors:
        raise click.exceptions.Exit(1)


def _report_for_items(
    source: str,
    group_name: str,
    items: list[ContentItem],
    facts: dict[str, Any] | None = None,
    *,
    parallel: int = 1,
) -> MeasurementReport:
    runtime = _runtime()
    measured = runtime.service().measure_items(items, runtime.options, parallel=parallel)
    group_facts = {"item_count": len(items), **(facts or {})}
    report = MeasurementReport(
        source=source,
        request=_measurement_request(),
        groups=[MeasurementGroup(group_name, measured, group_facts)],
    )
    _add_measurement_failures(report)
    return report


def _add_measurement_failures(report: MeasurementReport) -> None:
    for group in report.groups:
        for item in group.items:
            for name, metric in item.metrics.items():
                if metric.status.value == "failed":
                    report.errors.append(
                        Issue(
                            "measurement-failed",
                            f"{name}: {metric.reason or 'measurement failed'}",
                            item.item_id,
                        )
                    )
                elif metric.status.value == "skip":
                    report.warnings.append(
                        Issue(
                            "measurement-skipped",
                            f"{name}: {metric.reason or 'measurement skipped'}",
                            item.item_id,
                        )
                    )


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=("Leaf commands: stat, jinja, git diff, mcp list, mcp request, completions."),
)
@click.option("--backend", default="auto", show_default=True)
@click.option("--text-tokenizer", default="o200k_base", show_default=True)
@click.option("--image-tokenizer", default="gpt-5.6-style", show_default=True)
@click.option("--allow-online", is_flag=True)
@click.option("-v", "--verbose", is_flag=True, help="MCP返却結果本文を表示する。")
@click.option(
    "--format",
    "--output-format",
    "output_format",
    type=click.Choice(["table", "json", "tree"]),
    default="table",
    show_default=True,
)
@click.option(
    "--metrics",
    default="token",
    show_default=True,
    help="Comma-separated metrics, or all.",
)
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(SORT_KEYS),
    default="path",
    show_default=True,
)
@click.option(
    "--order",
    type=click.Choice(["asc", "desc"]),
    default="asc",
    show_default=True,
)
@click.option(
    "-p",
    "--parallel",
    type=click.IntRange(min=0),
    default=1,
    show_default=True,
    help="Number of workers for stat; 0 uses the CPU count.",
)
@click.pass_context
def main(
    context: click.Context,
    backend: str,
    text_tokenizer: str,
    image_tokenizer: str,
    allow_online: bool,
    verbose: bool,
    output_format: str,
    metrics: str,
    sort_by: str,
    order: str,
    parallel: int,
) -> None:
    """Measure context-sized inputs for coding agents."""
    try:
        metric_selection = parse_metric_selection(metrics)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--metrics") from exc
    try:
        canonical_sort = parse_sort_selection(sort_by)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--sort") from exc
    if canonical_sort != "path" and canonical_sort not in metric_selection:
        raise click.BadParameter(
            f"--sort {sort_by} requires the same metric in --metrics",
            param_hint="--sort",
        )
    context.ensure_object(dict)
    context.obj = Runtime(
        MeasurementOptions(
            backend=backend,
            text_tokenizer=text_tokenizer,
            image_tokenizer=image_tokenizer,
            allow_online=allow_online,
            output_format=output_format,
            metrics=metric_selection,
            sort=canonical_sort,
            order=order,
            parallel=parallel,
        ),
        verbose=verbose,
    )


def _run_command_for_path(
    command_template: str,
    path: Path,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[ContentItem, CommandExecution]:
    execution = run_for_path(
        command_template,
        path,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    item = ContentItem(
        item_id=f"command:{path}",
        origin="command",
        label=str(path),
        kind=ContentKind.TEXT,
        payload=TextPayload(
            raw=execution.stdout,
            text=execution.stdout.decode("utf-8", errors="replace"),
            encoding="utf-8",
        ),
        metadata={
            "path": str(path),
            "argv": list(execution.argv),
            "returncode": execution.returncode,
            "duration_seconds": execution.duration_seconds,
            "timed_out": execution.timed_out,
            "start_error": execution.start_error,
            "stdout_truncated": execution.stdout_truncated,
            "stderr_truncated": execution.stderr_truncated,
        },
    )
    return item, execution


@main.command()
@click.option("--include-images", is_flag=True)
@click.option("--ignore-gitignore", is_flag=True)
@click.option("--command", "command_template", default=None)
@click.option("--timeout", "timeout_seconds", type=float, default=30.0, show_default=True)
@click.option(
    "--max-output-bytes", type=click.IntRange(min=1), default=10_000_000, show_default=True
)
@click.argument("paths", nargs=-1, type=click.Path(path_type=str))
def stat(
    include_images: bool,
    ignore_gitignore: bool,
    command_template: str | None,
    timeout_seconds: float,
    max_output_bytes: int,
    paths: tuple[str, ...],
) -> None:
    """Measure files, directories, or standard input."""
    parallel = _runtime().options.parallel
    if not paths:
        raise click.UsageError("provide a file, directory, or - for standard input")
    try:
        if command_template is not None:
            if "-" in paths:
                raise click.UsageError("--command cannot be used with standard input")
            direct_files = {Path(raw_path) for raw_path in paths if Path(raw_path).is_file()}

            def is_excluded_image(path: Path) -> bool:
                if include_images or path in direct_files:
                    return False
                if is_image_path(path):
                    return True
                try:
                    return is_image_data(path.read_bytes())
                except OSError:
                    return False

            selected_paths = [
                path
                for path in iter_selected_files(paths, ignore_gitignore=ignore_gitignore)
                if not is_excluded_image(path)
            ]
            results = ordered_map(
                lambda path: _run_command_for_path(
                    command_template,
                    path,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                ),
                selected_paths,
                parallel,
            )
            report = _report_for_items(
                "command",
                "items",
                [item for item, _ in results],
                {"input_paths": list(paths)},
                parallel=parallel,
            )
            for item, execution in results:
                if execution.start_error:
                    report.errors.append(
                        Issue("command-start-failed", execution.start_error, item.item_id)
                    )
                    continue
                if execution.stderr:
                    report.warnings.append(
                        Issue(
                            "command-stderr",
                            execution.stderr.decode("utf-8", errors="replace").strip(),
                            item.item_id,
                        )
                    )
                truncated_streams = [
                    name
                    for name, truncated in (
                        ("stdout", execution.stdout_truncated),
                        ("stderr", execution.stderr_truncated),
                    )
                    if truncated
                ]
                if truncated_streams:
                    report.warnings.append(
                        Issue(
                            "command-output-truncated",
                            (
                                f"{', '.join(truncated_streams)} exceeded "
                                f"{max_output_bytes} bytes and was truncated"
                            ),
                            item.item_id,
                        )
                    )
                if execution.timed_out:
                    report.errors.append(
                        Issue("command-timeout", "command timed out", item.item_id)
                    )
                elif execution.returncode != 0:
                    report.errors.append(
                        Issue(
                            "command-failed",
                            f"command exited with {execution.returncode}",
                            item.item_id,
                        )
                    )
            _emit(report)
            return

        if paths == ("-",):
            _emit(_report_for_items("stdin", "items", [read_stdin_item()]))
            return
        if "-" in paths:
            raise click.UsageError("- cannot be combined with file or directory paths")
        bundle = collect_files(
            paths,
            include_images,
            ignore_gitignore=ignore_gitignore,
            parallel=parallel,
        )
        report = _report_for_items(
            "file",
            "items",
            list(bundle.items),
            bundle.facts,
            parallel=parallel,
        )
        binary_files = bundle.facts.get("binary_files", [])
        if binary_files:
            report.warnings.append(
                Issue(
                    "binary-file-skipped",
                    f"skipped {len(binary_files)} binary file(s): {', '.join(binary_files)}",
                )
            )
        _emit(report)
    except (ContextStatError, GitArgumentError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.option("--params", default="{}", metavar="JSON", show_default=True)
@click.argument("template", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def jinja(params: str, template: Path) -> None:
    """Measure the rendered result of a Jinja template."""
    try:
        parsed = json.loads(params)
        if not isinstance(parsed, dict):
            raise ValueError("--params must contain a JSON object")
        item = render_template(template, parsed)
        _emit(_report_for_items("jinja", "rendered", [item]))
    except (ContextStatError, OSError, ValueError, TemplateError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.group()
def git() -> None:
    """Measure content produced by Git operations."""


@git.command(
    "diff",
    cls=GitDiffCommand,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("git_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def git_diff(context: click.Context, git_args: tuple[str, ...]) -> None:
    """Measure a local ``git diff`` after parsing its arguments."""
    args = tuple("--" if arg == _GIT_SEPARATOR else arg for arg in git_args)
    try:
        spec = parse_git_diff_args(args)
        bundle = run_git_diff(spec)
        report = _report_for_items("git", "diff", list(bundle.items), bundle.facts)
        if bundle.facts.get("numstat_available") is False:
            report.warnings.append(
                Issue(
                    "git-numstat-unavailable",
                    (
                        "Git numstat could not be read; file-level additions and deletions "
                        "are unavailable"
                    ),
                )
            )
        _emit(report)
    except (ContextStatError, GitArgumentError, OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def _resolve_mcp_config(
    config_path: Path | None,
    url: str | None,
    header_from_env: tuple[str, ...],
    *,
    codex_config_path: Path | None = None,
    server_name: str | None = None,
) -> McpConnection:
    sources = [config_path is not None, codex_config_path is not None, url is not None]
    if sum(sources) > 1:
        raise ValueError("--config, --codex-config, and --url cannot be used together")
    if not any(sources):
        raise ValueError("one of --config, --codex-config, or --url is required")
    if config_path is not None:
        if header_from_env or server_name:
            raise ValueError(
                "--header-from-env and --server can only be used with --url or --codex-config"
            )
        return McpConnection(McpServerConfig.from_path(config_path), config_path, "config")
    if codex_config_path is not None:
        if header_from_env:
            raise ValueError("--header-from-env can only be used with --url")
        return McpConnection(
            McpServerConfig.from_codex_path(codex_config_path, server_name),
            codex_config_path,
            "codex-config",
        )
    if server_name:
        raise ValueError("--server can only be used with --codex-config")

    headers: dict[str, str] = {}
    for specification in header_from_env:
        header, separator, environment_name = specification.partition("=")
        if not separator or not header or not environment_name:
            raise ValueError("--header-from-env must use HEADER=ENV format")
        if header in headers:
            raise ValueError(f"duplicate HTTP header in --header-from-env: {header}")
        headers[header] = environment_name
    return McpConnection(
        McpServerConfig(
            transport="streamable-http",
            url=url,
            headers_from_env=headers or None,
        ),
        None,
        "url",
    )


def _mcp_request_options(connection: McpConnection) -> dict[str, Any]:
    result: dict[str, Any] = {
        "config": (str(connection.config_path) if connection.config_path is not None else None),
        "source": connection.source,
    }
    if connection.config.server_name is not None:
        result["server"] = connection.config.server_name
    return result


async def _mcp_list_all(
    client: OfficialMcpSdkAdapter, method_name: str, item_kind: str
) -> tuple[dict[str, Any], int]:
    entries: list[Any] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    pages = 0
    while True:
        result = await getattr(client, method_name)(cursor=cursor)
        value = jsonable(result)
        if not isinstance(value, dict):
            raise ValueError(f"MCP {item_kind}/list returned a non-object result")
        page_entries = value.get(item_kind, [])
        if not isinstance(page_entries, list):
            raise ValueError(f"MCP {item_kind}/list returned an invalid item list")
        entries.extend(page_entries)
        pages += 1
        next_cursor = value.get("nextCursor", value.get("next_cursor"))
        if next_cursor in (None, ""):
            return {item_kind: entries}, pages
        if not isinstance(next_cursor, str):
            raise ValueError(f"MCP {item_kind}/list returned an invalid nextCursor")
        if next_cursor in seen_cursors:
            raise ValueError(f"MCP {item_kind}/list returned a repeated nextCursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


async def _mcp_list_report(
    connection: McpConnection,
    kind: str,
) -> MeasurementReport:
    runtime = _runtime()
    config = connection.config
    requested = ("tools", "resources", "prompts") if kind == "all" else (kind,)
    method_by_kind = {
        "tools": "list_tools",
        "resources": "list_resources",
        "prompts": "list_prompts",
    }
    groups: list[MeasurementGroup] = []
    warnings: list[Issue] = []
    async with OfficialMcpSdkAdapter(config) as client:
        for item_kind in requested:
            capability = getattr(client.server_capabilities, item_kind, None)
            operation = f"{item_kind}/list"
            if capability is None:
                groups.append(
                    MeasurementGroup(
                        item_kind,
                        [],
                        {
                            "item_count": 0,
                            "operation": operation,
                            "available": False,
                            "reason": "server did not advertise this capability",
                        },
                    )
                )
                warnings.append(
                    Issue(
                        "mcp-capability-unavailable",
                        f"MCP server does not advertise {item_kind}",
                    )
                )
                continue
            result, pages = await _mcp_list_all(
                client,
                method_by_kind[item_kind],
                item_kind,
            )
            bundle = list_result_bundle(result, item_kind)
            measured = runtime.service().measure_items(bundle.items, runtime.options)
            groups.append(
                MeasurementGroup(
                    item_kind,
                    measured,
                    {"item_count": len(measured), "pages": pages, **bundle.facts},
                )
            )
    report = MeasurementReport(
        source="mcp-list",
        request={
            **_measurement_request(),
            **_mcp_request_options(connection),
            "transport": config.transport,
        },
        groups=groups,
        warnings=warnings,
    )
    _add_measurement_failures(report)
    return report


def _mcp_request_payload(method: str, name: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "tools/call":
        return {"method": method, "params": {"name": name, "arguments": params}}
    if method == "resources/read":
        if params:
            raise ValueError("resources/read does not accept parameters; use --name for the URI")
        return {"method": method, "params": {"uri": name}}
    if not all(isinstance(value, str) for value in params.values()):
        raise ValueError("prompts/get parameters must have string values")
    return {"method": method, "params": {"name": name, "arguments": params}}


def _mcp_result_items(
    items: tuple[ContentItem, ...], measured: list[MeasuredItem]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    image_reader = ImageMetadataReader()
    for item, measured_item in zip(items, measured, strict=True):
        summary: dict[str, Any] = {
            "label": measured_item.label,
            "kind": measured_item.kind,
        }
        if isinstance(item.payload, ImagePayload):
            media_type = item.payload.media_type
            if media_type:
                summary["media_type"] = media_type
            try:
                metadata = image_reader.read(item.payload.data)
            except ContextStatError:
                summary["dimensions"] = None
            else:
                if "media_type" not in summary:
                    summary["media_type"] = metadata.media_type
                summary["dimensions"] = {
                    "width": metadata.width,
                    "height": metadata.height,
                }
                if metadata.frames != 1:
                    summary["frames"] = metadata.frames
        summaries.append(summary)
    return summaries


def _mcp_image_marker(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "<image dimensions=unknown>"
    media_type = str(summary.get("media_type") or "image")
    dimensions = summary.get("dimensions")
    if isinstance(dimensions, dict):
        width = dimensions.get("width")
        height = dimensions.get("height")
        if isinstance(width, int) and isinstance(height, int):
            return f"<{media_type} {width}x{height}>"
    return f"<{media_type} dimensions=unknown>"


def _sanitize_mcp_value(value: Any, summary: dict[str, Any] | None = None) -> Any:
    if isinstance(value, list):
        return [_sanitize_mcp_value(entry, summary) for entry in value]
    if not isinstance(value, dict):
        return value
    sanitized = {key: _sanitize_mcp_value(entry, summary) for key, entry in value.items()}
    is_image = value.get("type") == "image" or str(value.get("mimeType", "")).startswith("image/")
    if is_image:
        for field in ("data", "blob"):
            if field in value:
                sanitized[field] = _mcp_image_marker(summary)
    return sanitized


def _mcp_result_value(
    value: Any,
    method: str,
    summaries: list[dict[str, Any]],
) -> Any:
    summary_by_label = {
        str(summary["label"]): summary
        for summary in summaries
        if isinstance(summary.get("label"), str)
    }
    display = _sanitize_mcp_value(value)
    if not isinstance(display, dict) or not isinstance(value, dict):
        return display

    for key, label_pattern in (
        ("content", f"{method}.content"),
        ("contents", f"{method}.contents"),
    ):
        entries = value.get(key)
        if not isinstance(entries, list):
            continue
        display[key] = [
            _sanitize_mcp_value(
                entry,
                summary_by_label.get(f"{label_pattern}[{index}]"),
            )
            for index, entry in enumerate(entries)
        ]

    messages = value.get("messages")
    if isinstance(messages, list):
        displayed_messages = []
        for index, message in enumerate(messages):
            summary = summary_by_label.get(f"{method}.messages[{index}]")
            if not isinstance(message, dict):
                displayed_messages.append(_sanitize_mcp_value(message, summary))
                continue
            displayed_message = _sanitize_mcp_value(message)
            if isinstance(message.get("content"), dict):
                displayed_message["content"] = _sanitize_mcp_value(message["content"], summary)
            displayed_messages.append(displayed_message)
        display["messages"] = displayed_messages
    return display


async def _mcp_request_report(
    connection: McpConnection,
    method: str,
    name: str,
    params: dict[str, Any],
) -> MeasurementReport:
    runtime = _runtime()
    config = connection.config
    request_value = _mcp_request_payload(method, name, params)
    generated = ContentItem(
        item_id="mcp:request:generated",
        origin="mcp",
        label=f"{method} request",
        kind=ContentKind.STRUCTURED,
        payload=StructuredPayload(value=request_value),
        metadata={"transport": config.transport},
        direction="client_to_server",
        semantic_role="generated",
    )
    started = time.monotonic()
    async with OfficialMcpSdkAdapter(config) as client:
        if method == "tools/call":
            result = await client.call_tool(name, params)
        elif method == "resources/read":
            result = await client.read_resource(name)
        else:
            result = await client.get_prompt(name, params)
    duration = time.monotonic() - started
    returned_bundle = result_bundle(result, method)
    generated_measured = runtime.service().measure_items([generated], runtime.options)
    returned_measured = runtime.service().measure_items(returned_bundle.items, runtime.options)
    result_value = jsonable(result)
    result_is_error = isinstance(result_value, dict) and result_value.get("isError") is True
    errors: list[Issue] = []
    if result_is_error:
        errors.append(Issue("mcp-request-error", "MCP returned an error result"))
    result_status = "error" if result_is_error else "ok"
    result_items = _mcp_result_items(returned_bundle.items, returned_measured)
    report = MeasurementReport(
        source="mcp-request",
        request={
            **_measurement_request(),
            **_mcp_request_options(connection),
            "transport": config.transport,
            "method": method,
            "name": name,
        },
        groups=[
            MeasurementGroup(
                "generated",
                generated_measured,
                {"item_count": len(generated_measured), "request": request_value},
            ),
            MeasurementGroup(
                "returned",
                returned_measured,
                {
                    "item_count": len(returned_measured),
                    **returned_bundle.facts,
                    "duration_seconds": duration,
                },
            ),
        ],
        facts={
            "result": {
                "status": result_status,
                "is_error": result_is_error,
                "items": result_items,
                "value": _mcp_result_value(result_value, method, result_items),
            },
        },
        errors=errors,
    )
    _add_measurement_failures(report)
    return report


@main.group()
def mcp() -> None:
    """Measure content obtained through an MCP server."""


@mcp.command("list")
@click.option(
    "--kind",
    type=click.Choice(["all", "tools", "resources", "prompts"]),
    default="all",
    show_default=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--codex-config",
    "codex_config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Read an MCP server from a Codex config.toml file.",
)
@click.option(
    "--server",
    "server_name",
    default=None,
    help="Codex MCP server name when the config contains multiple servers.",
)
@click.option("--url", default=None, help="Streamable HTTP server URL.")
@click.option(
    "--header-from-env",
    "header_from_env",
    multiple=True,
    metavar="HEADER=ENV",
    help="Read an HTTP header value from an environment variable; repeatable.",
)
def mcp_list(
    kind: str,
    config_path: Path | None,
    codex_config_path: Path | None,
    server_name: str | None,
    url: str | None,
    header_from_env: tuple[str, ...],
) -> None:
    """List MCP tools, resources, and prompts and measure their definitions."""
    try:
        connection = _resolve_mcp_config(
            config_path,
            url,
            header_from_env,
            codex_config_path=codex_config_path,
            server_name=server_name,
        )
        _emit(asyncio.run(_mcp_list_report(connection, kind)))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@mcp.command("request")
@click.option(
    "--method",
    type=click.Choice(["tools/call", "resources/read", "prompts/get"]),
    default="tools/call",
    show_default=True,
)
@click.option("--name", required=True, help="Tool name, resource URI, or prompt name.")
@click.option("--params", default="{}", metavar="JSON", show_default=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--codex-config",
    "codex_config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Read an MCP server from a Codex config.toml file.",
)
@click.option(
    "--server",
    "server_name",
    default=None,
    help="Codex MCP server name when the config contains multiple servers.",
)
@click.option("--url", default=None, help="Streamable HTTP server URL.")
@click.option(
    "--header-from-env",
    "header_from_env",
    multiple=True,
    metavar="HEADER=ENV",
    help="Read an HTTP header value from an environment variable; repeatable.",
)
def mcp_request(
    method: str,
    name: str,
    params: str,
    config_path: Path | None,
    codex_config_path: Path | None,
    server_name: str | None,
    url: str | None,
    header_from_env: tuple[str, ...],
) -> None:
    """Execute one MCP request and measure generated and returned content."""
    try:
        parsed = json.loads(params)
        if not isinstance(parsed, dict):
            raise ValueError("--params must contain a JSON object")
        connection = _resolve_mcp_config(
            config_path,
            url,
            header_from_env,
            codex_config_path=codex_config_path,
            server_name=server_name,
        )
        _emit(asyncio.run(_mcp_request_report(connection, method, name, parsed)))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completions(shell: str) -> None:
    """Print a shell completion script."""
    from click.shell_completion import get_completion_class

    context = click.get_current_context().find_root()
    completion_class = get_completion_class(shell)
    if completion_class is None:
        raise click.ClickException(f"unsupported shell: {shell}")
    prog_name = context.info_name or "context-stat"
    complete_var = f"_{prog_name.replace('-', '_').upper()}_COMPLETE"
    completion = completion_class(context.command, {}, prog_name, complete_var)
    click.echo(completion.source(), nl=False)
