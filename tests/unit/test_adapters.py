from __future__ import annotations

import base64
import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from PIL.Image import DecompressionBombError

from context_stat.adapters import filesystem as filesystem_adapter
from context_stat.adapters.filesystem import collect_files
from context_stat.adapters.git import GitArgumentError, parse_git_diff_args, run_git_diff
from context_stat.adapters.mcp import list_result_bundle, result_bundle
from context_stat.adapters.templating import render_command


def test_direct_image_is_included_but_recursive_image_is_opt_in(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    with image.open("wb") as output:
        Image.new("RGB", (2, 2), color="white").save(output, format="PNG")
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_image = nested / "nested.png"
    nested_image.write_bytes(b"not an image")
    nested_extensionless_image = nested / "nested-image"
    with nested_extensionless_image.open("wb") as output:
        Image.new("RGB", (2, 2), color="white").save(output, format="PNG")

    direct = collect_files([str(image)], include_images=False)
    recursive = collect_files([str(tmp_path)], include_images=False)
    recursive_with_images = collect_files([str(tmp_path)], include_images=True)

    assert len(direct.items) == 1
    assert direct.items[0].kind.value == "image"
    assert recursive.items == ()
    assert len(recursive_with_images.items) == 3
    assert all(item.kind.value == "image" for item in recursive_with_images.items)


def test_direct_extensionless_image_is_detected(tmp_path: Path) -> None:
    image = tmp_path / "image.data"
    with image.open("wb") as output:
        Image.new("RGB", (2, 2), color="white").save(output, format="PNG")

    direct = collect_files([str(image)], include_images=False)

    assert direct.items[0].kind.value == "image"


def test_binary_files_are_skipped_from_file_collection(tmp_path: Path) -> None:
    binary = tmp_path / "program.bin"
    binary.write_bytes(b"header\x00\xffpayload")

    bundle = collect_files([str(binary)], include_images=False)

    assert bundle.items == ()
    assert bundle.facts["binary_file_count"] == 1
    assert bundle.facts["binary_files"] == [str(binary)]


def test_directory_collection_respects_gitignore(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "included.txt").write_text("included", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")

    respected = collect_files([str(tmp_path)], include_images=False)
    all_files = collect_files([str(tmp_path)], include_images=False, ignore_gitignore=True)

    respected_labels = {item.label for item in respected.items}
    all_labels = {item.label for item in all_files.items}
    assert str(tmp_path / "ignored.txt") not in respected_labels
    assert str(tmp_path / "ignored.txt") in all_labels


def test_gitignore_matches_symlinked_files_without_resolving_target(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    virtualenv_bin = tmp_path / ".venv" / "bin"
    virtualenv_bin.mkdir(parents=True)
    target = tmp_path.parent / f"{tmp_path.name}-python"
    target.write_bytes(b"#!/bin/sh\n")
    link = virtualenv_bin / "python"
    link.symlink_to(target)

    bundle = collect_files([str(tmp_path)], include_images=False)

    assert str(link) not in bundle.facts["binary_files"]
    assert bundle.facts["ignored_file_count"] == 1


def test_gitignore_normalizes_dotdot_and_repository_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "nested").mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (repository / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repository / "included.txt").write_text("included", encoding="utf-8")
    (repository / "ignored.txt").write_text("ignored", encoding="utf-8")

    dotdot_bundle = collect_files(
        [str(repository / "nested" / "..")],
        include_images=False,
    )
    repository_link = tmp_path / "repository-link"
    repository_link.symlink_to(repository, target_is_directory=True)
    symlink_bundle = collect_files([str(repository_link)], include_images=False)

    for bundle, root in ((dotdot_bundle, repository), (symlink_bundle, repository_link)):
        labels = {item.label for item in bundle.items}
        assert str(root / "ignored.txt") not in labels
        assert bundle.facts["ignored_file_count"] == 1


def test_image_probe_handles_decompression_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_bomb(_source: object) -> None:
        raise DecompressionBombError("image is too large")

    monkeypatch.setattr(filesystem_adapter.Image, "open", raise_bomb)

    assert filesystem_adapter.is_image_data(b"not inspected") is False


def test_file_collection_continues_without_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    text_file = tmp_path / "plain.txt"
    text_file.write_text("hello", encoding="utf-8")

    def missing_git(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(filesystem_adapter.subprocess, "run", missing_git)

    bundle = collect_files([str(tmp_path)], include_images=False)

    assert [item.label for item in bundle.items] == [str(text_file)]
    assert bundle.facts["ignored_file_count"] == 0


def test_jinja_command_uses_argv_and_rejects_shell_operators(tmp_path: Path) -> None:
    path = tmp_path / "name with spaces.txt"

    assert render_command("cat {{ path|quote }}", path) == ["cat", str(path)]
    with pytest.raises(ValueError, match="shell operators"):
        render_command("cat {{ path|quote }} | wc -c", path)


def test_git_diff_arguments_are_parsed_and_separator_is_preserved() -> None:
    spec = parse_git_diff_args(
        [
            "--color",
            "always",
            "--merge-base",
            "-p",
            "-U3",
            "-M90%",
            "main",
            "--",
            "src/a file.py",
        ]
    )

    assert spec.revisions == ("main",)
    assert spec.pathspecs == ("src/a file.py",)
    assert spec.argv() == [
        "diff",
        "--color=always",
        "--merge-base",
        "-p",
        "-U3",
        "-M90%",
        "main",
        "--",
        "src/a file.py",
    ]

    with pytest.raises(GitArgumentError, match="unsupported"):
        parse_git_diff_args(["--made-up"])
    with pytest.raises(GitArgumentError, match="unsupported"):
        parse_git_diff_args(["--output", "result.patch"])

    multiple_revisions = parse_git_diff_args(["base", "left", "right", "--", "src"])
    assert multiple_revisions.revisions == ("base", "left", "right")

    optional_values = parse_git_diff_args(["--word-diff", "porcelain", "main", "--submodule=log"])
    assert optional_values.options == ("--word-diff", "porcelain", "--submodule=log")
    assert optional_values.revisions == ("main",)

    for option in (
        "--no-patch",
        "--name-only",
        "--name-status",
        "--stat",
        "--dirstat",
        "--dirstat-by-file",
    ):
        with pytest.raises(GitArgumentError, match="do not produce a patch"):
            parse_git_diff_args([option, "HEAD"])


def test_git_diff_returns_one_item_per_changed_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "context-stat test"],
        check=True,
    )
    (tmp_path / "a.txt").write_text("before a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("before b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "initial"],
        check=True,
    )
    (tmp_path / "a.txt").write_text("after a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("after b\n", encoding="utf-8")

    bundle = run_git_diff(parse_git_diff_args(["HEAD"]), cwd=tmp_path)

    assert [item.label for item in bundle.items] == ["a.txt", "b.txt"]
    assert all("diff --git" in item.payload.text for item in bundle.items)
    assert bundle.facts["changed_files"] == 2

    exit_code_bundle = run_git_diff(parse_git_diff_args(["--exit-code", "HEAD"]), cwd=tmp_path)
    assert [item.label for item in exit_code_bundle.items] == ["a.txt", "b.txt"]

    colored_bundle = run_git_diff(parse_git_diff_args(["--color", "always", "HEAD"]), cwd=tmp_path)
    assert [item.label for item in colored_bundle.items] == ["a.txt", "b.txt"]


def test_git_diff_decodes_non_ascii_paths(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "context-stat test"],
        check=True,
    )
    path = tmp_path / "日本語.txt"
    path.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "initial"], check=True)
    path.write_text("after\n", encoding="utf-8")

    bundle = run_git_diff(parse_git_diff_args(["HEAD"]), cwd=tmp_path)

    assert [item.label for item in bundle.items] == ["日本語.txt"]


def test_mcp_result_content_is_split_into_typed_items() -> None:
    listing = list_result_bundle({"tools": [{"name": "echo", "inputSchema": {}}]}, "tools")
    returned = result_bundle(
        {
            "content": [{"type": "text", "text": "hello"}],
            "structuredContent": {"ok": True},
        },
        "tools/call",
    )

    assert listing.items[0].kind.value == "structured"
    assert returned.items[0].kind.value == "text"
    assert returned.items[0].direction == "server_to_client"
    assert returned.items[1].kind.value == "structured"


def test_mcp_resource_text_without_explicit_type_is_text() -> None:
    returned = result_bundle(
        {"contents": [{"uri": "resource://one", "mimeType": "text/plain", "text": "body"}]},
        "resources/read",
    )

    assert returned.items[0].kind.value == "text"
    assert returned.items[0].payload.text == "body"


def test_mcp_image_content_is_split_into_an_image_item() -> None:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), color="white").save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")

    returned = result_bundle(
        {
            "content": [
                {
                    "type": "image",
                    "data": encoded,
                    "mimeType": "image/png",
                }
            ]
        },
        "tools/call",
    )

    assert returned.items[0].kind.value == "image"
    assert returned.items[0].payload.data == output.getvalue()


def test_mcp_embedded_resource_text_is_extracted() -> None:
    returned = result_bundle(
        {
            "content": [
                {
                    "type": "resource",
                    "resource": {
                        "uri": "resource://one",
                        "mimeType": "text/plain",
                        "text": "body",
                    },
                }
            ]
        },
        "tools/call",
    )

    assert returned.items[0].kind.value == "text"
    assert returned.items[0].payload.text == "body"
    assert returned.items[0].metadata == {
        "mcp_type": "resource",
        "resource_uri": "resource://one",
    }


def test_mcp_embedded_resource_image_is_extracted() -> None:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")

    returned = result_bundle(
        {
            "content": [
                {
                    "type": "resource",
                    "resource": {
                        "uri": "resource://image",
                        "mimeType": "image/png",
                        "blob": encoded,
                    },
                }
            ]
        },
        "tools/call",
    )

    assert returned.items[0].kind.value == "image"
    assert returned.items[0].payload.data == output.getvalue()
