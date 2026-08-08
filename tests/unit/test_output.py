from __future__ import annotations

import json

from context_stat.domain.measurement import MeasuredItem, MetricValue
from context_stat.domain.report import MeasurementGroup, MeasurementReport
from context_stat.output import _ascii_table, _display_width, render_report


def test_table_keeps_columns_aligned_for_wide_characters() -> None:
    lines = _ascii_table(
        ["対象", "tokens"],
        [["日本語のファイル", "3"], ["plain", "10"]],
        alignments=["left", "right"],
    )

    line_widths = {_display_width(line) for line in lines}
    assert len(line_widths) == 1
    assert lines[3].endswith("|      3 |")
    assert lines[4].endswith("|     10 |")


def test_mcp_list_table_shows_definition_identity_and_description() -> None:
    report = MeasurementReport(
        source="mcp-list",
        request={"metrics": ["tokens"]},
        groups=[
            MeasurementGroup(
                "tools",
                [
                    MeasuredItem(
                        item_id="mcp:tools:0",
                        origin="mcp",
                        label="echo",
                        kind="structured",
                        metrics={"tokens": MetricValue.exact(12, unit="tokens")},
                        metadata={"mcp_description": "Return the supplied message."},
                    )
                ],
            )
        ],
    )

    output = render_report(report, "table")

    assert "description" in output
    assert "echo" in output
    assert "Return the supplied message." in output


def test_mcp_resource_table_shows_uri() -> None:
    report = MeasurementReport(
        source="mcp-list",
        request={"metrics": ["tokens"]},
        groups=[
            MeasurementGroup(
                "resources",
                [
                    MeasuredItem(
                        item_id="mcp:resources:0",
                        origin="mcp",
                        label="guide",
                        kind="structured",
                        metrics={"tokens": MetricValue.exact(8, unit="tokens")},
                        metadata={"mcp_uri": "resource://guide"},
                    )
                ],
            )
        ],
    )

    output = render_report(report, "table")

    assert "uri" in output
    assert "resource://guide" in output


def test_mcp_result_body_is_verbose_only() -> None:
    report = MeasurementReport(
        source="mcp-request",
        request={"metrics": ["tokens"]},
        groups=[
            MeasurementGroup(
                "returned",
                [
                    MeasuredItem(
                        item_id="mcp:return:0",
                        origin="mcp",
                        label="tools/call.content[0]",
                        kind="text",
                        metrics={"tokens": MetricValue.exact(2, unit="tokens")},
                    )
                ],
            )
        ],
        facts={
            "result": {
                "status": "ok",
                "is_error": False,
                "items": [{"label": "tools/call.content[0]", "kind": "text"}],
                "value": {"content": [{"type": "text", "text": "hello"}]},
            }
        },
    )

    output = render_report(report, "table")
    verbose_output = render_report(report, "table", verbose=True)
    document = json.loads(render_report(report, "json"))
    verbose_document = json.loads(render_report(report, "json", verbose=True))

    assert output.index("[returned]") < output.index("result: ok")
    assert "response:" not in output
    assert "hello" not in output
    assert "response:" in verbose_output
    assert "hello" in verbose_output
    assert "value" not in document["facts"]["result"]
    assert verbose_document["facts"]["result"]["value"]["content"][0]["text"] == "hello"
