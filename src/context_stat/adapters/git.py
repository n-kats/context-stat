from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from context_stat.domain.content import ContentBundle, ContentItem, ContentKind, TextPayload


class GitArgumentError(ValueError):
    pass


_BOOLEAN_OPTIONS = {
    "-a",
    "-B",
    "--cached",
    "--staged",
    "--no-index",
    "--no-ext-diff",
    "--ext-diff",
    "--no-textconv",
    "--textconv",
    "--binary",
    "--full-index",
    "--find-renames",
    "--find-copies",
    "--no-renames",
    "--relative",
    "--no-color",
    "--ignore-all-space",
    "--ignore-space-change",
    "--ignore-space-at-eol",
    "--ignore-blank-lines",
    "--no-patch",
    "--patch",
    "--patch-with-raw",
    "--patch-with-stat",
    "--merge-base",
    "--find-copies-harder",
    "--pickaxe-all",
    "--minimal",
    "--patience",
    "--histogram",
    "--indent-heuristic",
    "--no-indent-heuristic",
    "--ignore-cr-at-eol",
    "--ita-invisible-in-index",
    "--ita-visible-in-index",
    "--no-prefix",
    "--default-prefix",
    "--text",
    "--quiet",
    "--exit-code",
    "--check",
    "--summary",
    "--stat",
    "--numstat",
    "--dirstat-by-file",
    "--name-only",
    "--name-status",
    "-p",
    "-u",
    "-R",
    "-M",
    "-C",
    "-w",
    "-b",
    "-z",
}
_VALUE_OPTIONS = {
    "--unified",
    "-U",
    "--diff-filter",
    "--diff-algorithm",
    "--submodule",
    "--word-diff",
    "--color",
    "--src-prefix",
    "--dst-prefix",
    "--line-prefix",
    "--inter-hunk-context",
    "--ignore-submodules",
    "--abbrev",
    "--word-diff-regex",
    "--color-moved",
    "--color-moved-ws",
    "--ws-error-highlight",
    "--anchored",
    "--find-object",
    "--skip-to",
    "--rotate-to",
    "--dirstat",
    "-l",
    "-O",
    "-S",
    "-G",
    "-L",
}
_OPTIONAL_VALUE_OPTIONS = {
    "--abbrev": frozenset(),
    "--dirstat": frozenset(),
    "--ignore-submodules": frozenset({"none", "untracked", "dirty", "all"}),
    "--submodule": frozenset({"short", "log", "diff"}),
    "--word-diff": frozenset({"plain", "color", "porcelain", "none"}),
    "--color-moved": frozenset({"no", "plain", "blocks", "zebra", "dimmed-zebra"}),
}
_NON_PATCH_OPTIONS = frozenset(
    {
        "--no-patch",
        "--name-only",
        "--name-status",
        "--stat",
        "--numstat",
        "--dirstat",
        "--dirstat-by-file",
        "--summary",
        "--check",
        "--quiet",
    }
)
_ANSI_ESCAPE_RE = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
_DIFF_HEADER_RE = re.compile(rb"^(?:\x1b\[[0-?]*[ -/]*[@-~])*diff --git .*$", re.MULTILINE)


@dataclass(frozen=True)
class GitDiffSpec:
    options: tuple[str, ...]
    revisions: tuple[str, ...]
    pathspecs: tuple[str, ...]

    def argv(self, *extra_options: str) -> list[str]:
        return ["diff", *extra_options, *self.options, *self.revisions, "--", *self.pathspecs]


def _split_option(token: str) -> tuple[str, str | None]:
    if "=" in token and token.startswith("--"):
        name, value = token.split("=", 1)
        return name, value
    return token, None


def parse_git_diff_args(args: tuple[str, ...] | list[str]) -> GitDiffSpec:
    options: list[str] = []
    revisions: list[str] = []
    pathspecs: list[str] = []
    after_separator = False
    index = 0
    while index < len(args):
        token = args[index]
        if after_separator:
            pathspecs.append(token)
            index += 1
            continue
        if token == "--":
            after_separator = True
            index += 1
            continue
        if token.startswith("-"):
            name, inline_value = _split_option(token)
            if name == "--color" and inline_value is None:
                if index + 1 < len(args) and args[index + 1] in {"always", "never", "auto"}:
                    # Git declares this as an optional ``=<when>`` value;
                    # keeping the value as a separate argv entry makes it a
                    # revision on the Git versions used by the CLI.
                    options.append(f"--color={args[index + 1]}")
                    index += 2
                else:
                    options.append(token)
                    index += 1
                continue
            if name in _BOOLEAN_OPTIONS:
                options.append(token)
                index += 1
                continue
            if name in _OPTIONAL_VALUE_OPTIONS:
                if inline_value is not None:
                    options.append(token)
                    index += 1
                    continue
                values = _OPTIONAL_VALUE_OPTIONS[name]
                next_value = args[index + 1] if index + 1 < len(args) else None
                if next_value is not None and (
                    next_value in values or (name == "--abbrev" and next_value.isdigit())
                ):
                    options.extend((token, next_value))
                    index += 2
                else:
                    options.append(token)
                    index += 1
                continue
            if name in _VALUE_OPTIONS:
                if inline_value is not None:
                    options.append(token)
                    index += 1
                    continue
                if index + 1 >= len(args):
                    raise GitArgumentError(f"missing value for Git option: {token}")
                options.extend((token, args[index + 1]))
                index += 2
                continue
            if token.startswith("-U") and len(token) > 2:
                options.append(token)
                index += 1
                continue
            if token[:2] in {"-B", "-M", "-C"} and len(token) > 2:
                options.append(token)
                index += 1
                continue
            if token[:2] in {"-l", "-O", "-S", "-G", "-L"} and len(token) > 2:
                options.append(token)
                index += 1
                continue
            raise GitArgumentError(f"unsupported Git diff option: {token}")
        revisions.append(token)
        index += 1

    unsupported_output = [
        _split_option(option)[0]
        for option in options
        if _split_option(option)[0] in _NON_PATCH_OPTIONS
    ]
    if unsupported_output:
        names = ", ".join(dict.fromkeys(unsupported_output))
        raise GitArgumentError(f"Git option(s) {names} do not produce a patch")
    return GitDiffSpec(tuple(options), tuple(revisions), tuple(pathspecs))


def run_git_diff(spec: GitDiffSpec, cwd: Path | None = None) -> ContentBundle:
    command = ["git", *spec.argv()]
    completed = subprocess.run(command, cwd=cwd, capture_output=True, check=False)
    if completed.returncode not in {0, 1}:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or f"git diff failed with exit code {completed.returncode}")
    facts = _read_numstat(spec, cwd)
    patch = completed.stdout
    chunks = _split_patch_by_file(patch)
    numstat_files = facts.get("files", [])
    items: list[ContentItem] = []
    for index, chunk in enumerate(chunks):
        path = _path_for_chunk(chunk, numstat_files, index)
        items.append(
            ContentItem(
                item_id=f"git:diff:{index}",
                origin="git",
                label=path,
                kind=ContentKind.TEXT,
                payload=TextPayload(
                    raw=chunk,
                    text=chunk.decode("utf-8", errors="replace"),
                    encoding="utf-8",
                ),
                metadata={"argv": command, "path": path},
            )
        )
    if not items and patch:
        items.append(
            ContentItem(
                item_id="git:diff",
                origin="git",
                label="git diff",
                kind=ContentKind.TEXT,
                payload=TextPayload(
                    raw=patch,
                    text=patch.decode("utf-8", errors="replace"),
                    encoding="utf-8",
                ),
                metadata={"argv": command},
            )
        )
    return ContentBundle(tuple(items), facts=facts)


def _split_patch_by_file(patch: bytes) -> list[bytes]:
    headers = list(_DIFF_HEADER_RE.finditer(patch))
    return [
        patch[header.start() : headers[index + 1].start() if index + 1 < len(headers) else None]
        for index, header in enumerate(headers)
    ]


def _path_for_chunk(chunk: bytes, numstat_files: object, index: int) -> str:
    if isinstance(numstat_files, list) and index < len(numstat_files):
        entry = numstat_files[index]
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            return _decode_git_path(entry["path"])
    first_line = _ANSI_ESCAPE_RE.sub(b"", chunk.splitlines()[0]).decode("utf-8", errors="replace")
    body = first_line.removeprefix("diff --git ")
    if " b/" in body:
        return _decode_git_path(body.rsplit(" b/", 1)[1].strip('"'))
    return f"diff[{index}]"


def _decode_git_path(value: str) -> str:
    """Decode the C-style path quoting used by Git's text output."""

    if not (value.startswith('"') and value.endswith('"')):
        return value

    encoded = value[1:-1]
    decoded = bytearray()
    index = 0
    escapes = {
        "a": 7,
        "b": 8,
        "f": 12,
        "n": 10,
        "r": 13,
        "t": 9,
        "v": 11,
    }
    while index < len(encoded):
        character = encoded[index]
        if character != "\\" or index + 1 >= len(encoded):
            decoded.extend(character.encode("utf-8"))
            index += 1
            continue

        next_character = encoded[index + 1]
        if next_character in "01234567" and index + 3 < len(encoded):
            octal = encoded[index + 1 : index + 4]
            if all(digit in "01234567" for digit in octal):
                decoded.append(int(octal, 8))
                index += 4
                continue
        if next_character in escapes:
            decoded.append(escapes[next_character])
        else:
            decoded.extend(next_character.encode("utf-8"))
        index += 2
    return decoded.decode("utf-8", errors="replace")


def _read_numstat(spec: GitDiffSpec, cwd: Path | None) -> dict[str, object]:
    command = ["git", *spec.argv("--numstat")]
    completed = subprocess.run(command, cwd=cwd, capture_output=True, check=False)
    if completed.returncode not in {0, 1}:
        return {"numstat_available": False}
    files: list[dict[str, object]] = []
    additions = 0
    deletions = 0
    for line in completed.stdout.decode("utf-8", errors="replace").splitlines():
        match = re.match(r"^(\d+|-)\s+(\d+|-)\s+(.+)$", line)
        if not match:
            continue
        added_raw, deleted_raw, path = match.groups()
        added = int(added_raw) if added_raw != "-" else None
        deleted = int(deleted_raw) if deleted_raw != "-" else None
        if added is not None:
            additions += added
        if deleted is not None:
            deletions += deleted
        files.append(
            {
                "path": _decode_git_path(path),
                "additions": added,
                "deletions": deleted,
            }
        )
    return {
        "numstat_available": True,
        "changed_files": len(files),
        "additions": additions,
        "deletions": deletions,
        "files": files,
    }
