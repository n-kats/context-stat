from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from context_stat.cli import _mcp_result_items, _mcp_result_value, main
from context_stat.domain.content import ContentItem, ContentKind, ImagePayload
from context_stat.domain.measurement import MeasuredItem


def test_stat_stdin_uses_default_text_tokenizer() -> None:
    result = CliRunner().invoke(
        main,
        ["stat", "-"],
        input="hello world\n",
    )

    assert result.exit_code == 0, result.output
    assert "| tokens" in result.output
    assert "3 tokens" not in result.output
    assert "|      3 |" in result.output


def test_anthropic_backend_requires_allow_online_without_sending_input() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--backend",
            "anthropic-api",
            "--text-tokenizer",
            "claude-sonnet-5",
            "stat",
            "-",
        ],
        input="secret prompt\n",
    )

    assert result.exit_code == 1
    assert "requires --allow-online" in result.output


def test_stat_json_is_machine_readable() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "stat",
            "-",
        ],
        input="hello",
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    metrics = document["groups"][0]["items"][0]["metrics"]
    assert metrics["tokens"]["value"] == 1
    assert "precision" not in metrics["tokens"]
    assert "bytes" not in metrics


def test_metrics_all_includes_basic_metrics() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--metrics",
            "all",
            "stat",
            "-",
        ],
        input="hello",
    )

    assert result.exit_code == 0, result.output
    assert "bytes" in result.output
    assert "characters" in result.output


def test_metrics_all_rejects_unknown_metric_names() -> None:
    result = CliRunner().invoke(
        main,
        ["--metrics", "all,typo", "stat", "-"],
        input="hello",
    )

    assert result.exit_code != 0
    assert "unknown metric 'typo'" in result.output


def test_unselected_token_metric_is_not_computed() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--metrics",
            "bytes",
            "stat",
            "-",
        ],
        input="hello",
    )

    assert result.exit_code == 0, result.output
    assert "bytes" in result.output
    assert "tokens" not in result.output
    assert "measurement-failed" not in result.output


def test_tree_format_is_available() -> None:
    # A non-path source still has a group node above its item.
    result = CliRunner().invoke(
        main,
        [
            "--format",
            "tree",
            "stat",
            "-",
        ],
        input="hello",
    )

    assert result.exit_code == 0, result.output
    assert "└── items [1 tokens]" in result.stdout
    assert "    └── - [1 tokens]" in result.stdout
    assert result.stderr == ""


def test_tree_format_uses_directory_nodes_for_totals(tmp_path: Path) -> None:
    root = tmp_path / "context"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "one.txt").write_text("one", encoding="utf-8")
    (nested / "two.txt").write_text("two three", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "tree",
            "stat",
            "--ignore-gitignore",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"└── {root} [" in result.stdout
    assert "one.txt [" in result.stdout
    assert "nested [" in result.stdout
    assert "two.txt [" in result.stdout
    assert "TOTAL" not in result.stdout


def test_directory_symlink_file_is_included_in_aggregate(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("linked content", encoding="utf-8")
    link = root / "linked.txt"
    link.symlink_to(external)

    result = CliRunner().invoke(
        main,
        ["--format", "json", "stat", "--ignore-gitignore", str(root)],
    )

    assert result.exit_code == 0, result.output
    group = json.loads(result.stdout)["groups"][0]
    item = next(item for item in group["items"] if item["label"] == str(link))
    root_node = next(node for node in group["nodes"] if node["path"] == str(root))
    assert root_node["metrics"]["tokens"]["value"] == item["metrics"]["tokens"]["value"]
    assert any(node["path"] == str(link) for node in group["nodes"])


def test_sort_orders_json_items_by_metric(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    short = root / "a.txt"
    long = root / "b.txt"
    short.write_text("a", encoding="utf-8")
    long.write_text("one two three", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "--metrics",
            "all",
            "--sort",
            "bytes",
            "--order",
            "desc",
            "stat",
            "--ignore-gitignore",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    labels = [item["label"] for item in json.loads(result.stdout)["groups"][0]["items"]]
    assert labels == [str(long), str(short)]


def test_tree_sorts_siblings_using_the_same_order(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    short = root / "a.txt"
    long = root / "b.txt"
    short.write_text("a", encoding="utf-8")
    long.write_text("one two three", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "tree",
            "--metrics",
            "all",
            "--sort",
            "bytes",
            "--order",
            "desc",
            "stat",
            "--ignore-gitignore",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.index("b.txt [") < result.stdout.index("a.txt [")


def test_table_uses_input_directory_as_aggregate_row() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("nested").mkdir()
        Path("nested/file.txt").write_text("hello", encoding="utf-8")

        result = runner.invoke(
            main,
            [
                "stat",
                ".",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "| . " in result.stdout
    assert "| dir " in result.stdout
    assert "TOTAL" not in result.stdout


def test_empty_directory_is_rendered_as_an_aggregate_node(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    table = CliRunner().invoke(
        main,
        ["stat", "--ignore-gitignore", str(empty)],
    )
    tree = CliRunner().invoke(
        main,
        ["--format", "tree", "stat", "--ignore-gitignore", str(empty)],
    )
    document = CliRunner().invoke(
        main,
        ["--format", "json", "stat", "--ignore-gitignore", str(empty)],
    )

    assert table.exit_code == 0, table.output
    assert f"| {empty} " in table.stdout
    assert "| dir " in table.stdout
    assert tree.exit_code == 0, tree.output
    assert f"└── {empty} [-]" in tree.stdout
    assert document.exit_code == 0, document.output
    nodes = json.loads(document.stdout)["groups"][0]["nodes"]
    assert nodes == [{"path": str(empty), "kind": "dir", "metrics": {}}]


def test_table_sorts_directory_rows_globally(tmp_path: Path) -> None:
    root = tmp_path / "context"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "direct.txt").write_text("a", encoding="utf-8")
    (nested / "file.txt").write_text("longer", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--metrics",
            "bytes",
            "--sort",
            "bytes",
            "--order",
            "asc",
            "stat",
            "--ignore-gitignore",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.count(f"| {root / 'direct.txt'}") == 1
    assert result.stdout.count(f"| {nested} ") == 1
    assert result.stdout.count(f"| {nested / 'file.txt'}") == 1
    assert result.stdout.count(f"| {root} ") == 1
    assert result.stdout.index(f"| {root / 'direct.txt'}") < result.stdout.index(f"| {nested} ")
    assert result.stdout.index(f"| {nested} ") < result.stdout.index(f"| {root} ")


def test_json_contains_directory_nodes_without_totals() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("nested").mkdir()
        Path("nested/file.txt").write_text("hello", encoding="utf-8")

        result = runner.invoke(
            main,
            [
                "--format",
                "json",
                "stat",
                ".",
            ],
        )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    group = document["groups"][0]
    assert "totals" not in group
    assert [node["path"] for node in group["nodes"]] == [".", "nested", "nested/file.txt"]
    assert [node["kind"] for node in group["nodes"]] == ["dir", "dir", "file"]


def test_json_sorts_directory_nodes_globally(tmp_path: Path) -> None:
    root = tmp_path / "context"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "direct.txt").write_text("a", encoding="utf-8")
    (nested / "file.txt").write_text("longer", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "--metrics",
            "bytes",
            "--sort",
            "bytes",
            "--order",
            "asc",
            "stat",
            "--ignore-gitignore",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    nodes = json.loads(result.stdout)["groups"][0]["nodes"]
    assert [node["path"] for node in nodes] == [
        str(root / "direct.txt"),
        str(nested),
        str(nested / "file.txt"),
        str(root),
    ]


def test_parallel_command_execution_preserves_items() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("b.txt").write_text("b", encoding="utf-8")
        Path("a.txt").write_text("a", encoding="utf-8")

        result = runner.invoke(
            main,
            [
                "--format",
                "json",
                "-p",
                "2",
                "stat",
                "--command",
                "cat {{ path|quote }}",
                ".",
            ],
        )

    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)["groups"][0]["items"]
    assert [item["label"] for item in items] == ["a.txt", "b.txt"]
    assert [item["metrics"]["tokens"]["value"] for item in items] == [1, 1]


def test_command_start_failures_are_reported_per_file(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "-p",
            "2",
            "stat",
            "--ignore-gitignore",
            "--command",
            "command-that-does-not-exist {{ path|quote }}",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert len(document["groups"][0]["items"]) == 2
    assert result.stderr.count("command-start-failed") == 2
    assert "command-failed" not in result.stderr
    assert "Traceback" not in result.stderr


def test_command_stat_uses_content_based_image_exclusion(tmp_path: Path) -> None:
    image = tmp_path / "image-data"
    image_data = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image_data, format="PNG")
    image.write_bytes(image_data.getvalue())
    text_file = tmp_path / "plain.txt"
    text_file.write_text("plain", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "stat",
            "--ignore-gitignore",
            "--command",
            "cat {{ path|quote }}",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)["groups"][0]["items"]
    assert [item["label"] for item in items] == [str(text_file)]


def test_command_output_truncation_is_reported_with_a_small_limit(tmp_path: Path) -> None:
    text_file = tmp_path / "plain.txt"
    text_file.write_text("plain", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "stat",
            "--ignore-gitignore",
            "--max-output-bytes",
            "1",
            "--command",
            "printf 123",
            str(text_file),
        ],
    )

    assert result.exit_code == 0, result.output
    item = json.loads(result.stdout)["groups"][0]["items"][0]
    assert item["metadata"]["stdout_truncated"] is True
    assert "command-output-truncated" in result.stderr


def test_stat_parallel_option_preserves_report_order(tmp_path: Path) -> None:
    root = tmp_path / "context"
    root.mkdir()
    (root / "b.txt").write_text("b", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "-p",
            "2",
            "stat",
            "--ignore-gitignore",
            str(root),
        ],
    )

    assert result.exit_code == 0, result.output
    labels = [item["label"] for item in json.loads(result.stdout)["groups"][0]["items"]]
    assert labels == [str(root / "a.txt"), str(root / "b.txt")]


def test_text_token_count_has_no_precision_diagnostic() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--format",
            "tree",
            "stat",
            "-",
        ],
        input="hello",
    )

    assert result.exit_code == 0, result.output
    assert "[1 tokens]" in result.stdout
    assert result.stderr == ""


def test_text_token_count_has_no_precision_label_in_table() -> None:
    result = CliRunner().invoke(
        main,
        [
            "--format",
            "table",
            "stat",
            "-",
        ],
        input="hello",
    )

    assert result.exit_code == 0, result.output
    assert "tokens" in result.stdout
    assert result.stderr == ""


def test_diagnostics_are_written_to_stderr_after_json(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image_data = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image_data, format="PNG")
    image.write_bytes(image_data.getvalue())

    result = CliRunner().invoke(
        main,
        [
            "--format",
            "json",
            "stat",
            str(image),
        ],
    )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["warnings"] == []
    metric = document["groups"][0]["items"][0]["metrics"]["image_tokens"]
    assert metric["status"] == "measured"
    assert metric["value"] == 1
    assert document["request"]["image_tokenizer"] == "gpt-5.6-style"
    assert result.stderr == ""


def test_stat_skips_binary_files_and_reports_the_path(tmp_path: Path) -> None:
    binary = tmp_path / "program.bin"
    binary.write_bytes(b"header\x00\xffpayload")

    result = CliRunner().invoke(
        main,
        [
            "stat",
            str(binary),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "binary-file-skipped" not in result.stdout
    assert "binary-file-skipped" in result.stderr
    assert str(binary) in result.stderr


def test_stat_skips_broken_image_tokens_with_item_path(tmp_path: Path) -> None:
    invalid_image = tmp_path / "broken.png"
    image_data = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image_data, format="PNG")
    invalid_image.write_bytes(image_data.getvalue()[:-8])

    result = CliRunner().invoke(
        main,
        [
            "stat",
            str(invalid_image),
        ],
    )

    assert result.exit_code == 0
    assert f"file:{invalid_image}" in result.output
    assert "measurement-skipped" in result.stderr
    assert "image could not be read" in result.stderr


def test_jinja_cli_measures_rendered_output(tmp_path: Path) -> None:
    template = tmp_path / "prompt.j2"
    template.write_text("Hello {{ name }}!", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "--metrics",
            "all",
            "jinja",
            "--params",
            '{"name":"Ada"}',
            str(template),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "characters" in result.output
    assert "10 characters" not in result.output


def test_git_cli_preserves_git_pathspec_separator() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "config", "user.name", "context-stat test"], check=True)
        Path("README.md").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], check=True)
        Path("README.md").write_text("after\n", encoding="utf-8")

        result = runner.invoke(
            main,
            [
                "--format",
                "json",
                "git",
                "diff",
                "--",
                "README.md",
            ],
        )

    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["groups"][0]["items"][0]["metadata"]["argv"] == [
        "git",
        "diff",
        "--",
        "README.md",
    ]


def test_git_diff_outputs_file_items_and_group_summary() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "config", "user.name", "context-stat test"], check=True)
        Path("a.txt").write_text("before a\n", encoding="utf-8")
        Path("b.txt").write_text("before b\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], check=True)
        Path("a.txt").write_text("after a\n", encoding="utf-8")
        Path("b.txt").write_text("after b\n", encoding="utf-8")

        json_result = runner.invoke(
            main,
            ["--format", "json", "--metrics", "all", "git", "diff", "HEAD"],
        )
        table_result = runner.invoke(
            main,
            ["--format", "table", "--metrics", "all", "git", "diff", "HEAD"],
        )

    assert json_result.exit_code == 0, json_result.output
    document = json.loads(json_result.stdout)
    group = document["groups"][0]
    assert [item["label"] for item in group["items"]] == ["a.txt", "b.txt"]
    assert group["summary"]["tokens"]["value"] == sum(
        item["metrics"]["tokens"]["value"] for item in group["items"]
    )
    assert table_result.exit_code == 0, table_result.output
    assert "| diff " in table_result.stdout


def test_mcp_request_uses_official_stdio_sdk(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "transport": "stdio",
                "command": uv,
                "args": ["run", "python", "tests/fixtures/mcp_stdio_server.py"],
                "cwd": str(Path.cwd()),
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "context_stat",
            "-v",
            "mcp",
            "request",
            "--config",
            str(config),
            "--method",
            "tools/call",
            "--name",
            "echo",
            "--params",
            '{"message":"hello"}',
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "result: ok" in result.stdout
    assert "hello" in result.stdout
    assert "[generated]" in result.stdout
    assert "[returned]" in result.stdout
    assert result.stdout.index("[generated]") < result.stdout.index("response:")


def test_mcp_request_reports_mcp_error_result(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "transport": "stdio",
                "command": uv,
                "args": ["run", "python", "tests/fixtures/mcp_stdio_server.py"],
                "cwd": str(Path.cwd()),
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "context_stat",
            "-v",
            "mcp",
            "request",
            "--config",
            str(config),
            "--method",
            "tools/call",
            "--name",
            "fail",
            "--params",
            "{}",
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "result: error" in result.stdout
    assert "response:" in result.stdout
    assert "server rejected the request" in result.stdout
    assert "error [mcp-request-error]" in result.stderr


def test_mcp_result_image_summary_includes_dimensions() -> None:
    image = io.BytesIO()
    Image.new("RGB", (48, 24), color="white").save(image, format="PNG")
    item = ContentItem(
        item_id="mcp:return:0",
        origin="mcp",
        label="tools/call.content[0]",
        kind=ContentKind.IMAGE,
        payload=ImagePayload(image.getvalue(), media_type="image/png"),
    )
    measured = MeasuredItem(
        item_id=item.item_id,
        origin="mcp",
        label=item.label,
        kind="image",
        metrics={},
    )

    summary = _mcp_result_items((item,), [measured])

    assert summary == [
        {
            "label": "tools/call.content[0]",
            "kind": "image",
            "media_type": "image/png",
            "dimensions": {"width": 48, "height": 24},
        }
    ]

    displayed = _mcp_result_value(
        {
            "content": [
                {
                    "type": "image",
                    "data": "base64-must-not-be-displayed",
                    "mimeType": "image/png",
                }
            ]
        },
        "tools/call",
        summary,
    )

    assert displayed["content"][0]["data"] == "<image/png 48x24>"


def test_mcp_list_uses_official_stdio_sdk(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    config = tmp_path / "config.toml"
    config.write_text(
        "[mcp_servers.test]\n"
        f"command = {json.dumps(uv)}\n"
        'args = ["run", "python", "tests/fixtures/mcp_stdio_server.py"]\n'
        f"cwd = {json.dumps(str(Path.cwd()))}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "context_stat",
            "--format",
            "json",
            "mcp",
            "list",
            "--kind",
            "tools",
            "--codex-config",
            str(config),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert [group["name"] for group in document["groups"]] == ["tools"]
    assert document["groups"][0]["facts"]["item_count"] == 2
    assert document["groups"][0]["facts"]["pages"] == 2
    assert document["groups"][0]["items"][0]["label"] == "echo"
    assert document["groups"][0]["items"][1]["label"] == "echo-second"
    assert document["groups"][0]["items"][0]["metadata"]["mcp_description"] == (
        "Return the supplied message."
    )
    assert document["request"]["source"] == "codex-config"
    assert document["request"]["server"] == "test"


def test_mcp_request_uses_streamable_http_without_allow_online(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    server = subprocess.Popen(
        [sys.executable, "tests/fixtures/mcp_stdio_server.py"],
        cwd=Path.cwd(),
        env={
            **os.environ,
            "MCP_TEST_PORT": str(port),
            "MCP_TEST_TRANSPORT": "streamable-http",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            stderr = server.stderr.read() if server.stderr is not None else ""
            raise AssertionError(f"MCP HTTP test server did not start: {stderr}")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "context_stat",
                "--format",
                "json",
                "-v",
                "mcp",
                "request",
                "--url",
                f"http://127.0.0.1:{port}/mcp",
                "--method",
                "tools/call",
                "--name",
                "echo",
                "--params",
                '{"message":"hello"}',
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout)
        assert [group["name"] for group in document["groups"]] == ["generated", "returned"]
        assert document["facts"]["result"]["value"]["content"][0]["text"] == "hello"
        assert document["request"]["source"] == "url"
        assert document["request"]["config"] is None
        assert f"http://127.0.0.1:{port}/mcp" not in result.stdout
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def test_mcp_config_and_url_are_mutually_exclusive(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps({"transport": "streamable-http", "url": "http://example.test/mcp"}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        main,
        [
            "mcp",
            "list",
            "--config",
            str(config),
            "--url",
            "http://example.test/mcp",
        ],
    )

    assert result.exit_code != 0
    assert "--config, --codex-config, and --url cannot be used together" in result.output
