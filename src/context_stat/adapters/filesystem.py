from __future__ import annotations

import io
import os
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError

from context_stat.domain.content import (
    ContentBundle,
    ContentItem,
    ContentKind,
    ImagePayload,
    TextPayload,
)
from context_stat.domain.parallel import ordered_map

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def _decode_text(data: bytes) -> TextPayload:
    try:
        return TextPayload(raw=data, text=data.decode("utf-8"), encoding="utf-8")
    except UnicodeDecodeError as exc:
        return TextPayload(
            raw=data,
            text=None,
            encoding=None,
            decode_error=f"UTF-8 decoding failed at byte {exc.start}",
        )


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def is_image_data(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)):
            return True
    except (DecompressionBombError, UnidentifiedImageError, OSError):
        return False


def is_binary_data(data: bytes) -> bool:
    """Return whether bytes should be excluded from text-file measurement."""
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def iter_files(paths: Iterable[str]) -> Iterator[Path]:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            yield from sorted(
                item
                for item in path.rglob("*")
                if item.is_file() and ".git" not in item.relative_to(path).parts
            )
        elif path.is_file():
            yield path
        else:
            raise FileNotFoundError(f"path does not exist: {path}")


def read_file_item(
    path: Path,
    include_images: bool,
    *,
    force_image: bool = False,
    data: bytes | None = None,
    image_detected: bool | None = None,
) -> ContentItem | None:
    if data is None:
        data = path.read_bytes()
    metadata = {"path": str(path), "size": len(data)}
    is_image = (
        image_detected
        if image_detected is not None
        else is_image_path(path) or (force_image and is_image_data(data))
    )
    if is_image:
        if not include_images and not force_image:
            return None
        return ContentItem(
            item_id=f"file:{path}",
            origin="file",
            label=str(path),
            kind=ContentKind.IMAGE,
            payload=ImagePayload(data=data, source=str(path)),
            metadata=metadata,
        )
    if is_binary_data(data):
        return None
    return ContentItem(
        item_id=f"file:{path}",
        origin="file",
        label=str(path),
        kind=ContentKind.TEXT,
        payload=_decode_text(data),
        metadata=metadata,
    )


def _git_root(path: Path) -> Path | None:
    target = path if path.is_dir() else path.parent
    try:
        completed = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip())


def _lexical_absolute(path: Path) -> Path:
    """Normalize ``..`` without resolving symlinks in the candidate path."""
    return Path(os.path.abspath(path))


def _ignored_paths(paths: list[Path], roots: list[tuple[Path, Path]]) -> set[Path]:
    ignored: set[Path] = set()
    for input_root, git_root in roots:
        candidates = []
        input_root_absolute = _lexical_absolute(input_root)
        try:
            root_relative = input_root.resolve().relative_to(git_root.resolve())
        except ValueError:
            continue
        for path in paths:
            try:
                # Gitignore matches the lexical path. Resolving symlinks here can
                # move virtualenv executables outside the repository and skip
                # the ignore check entirely.
                relative = _lexical_absolute(path).relative_to(input_root_absolute)
            except ValueError:
                continue
            candidates.append((path, (root_relative / relative).as_posix()))
        if not candidates:
            continue
        input_data = "\0".join(relative for _, relative in candidates) + "\0"
        try:
            completed = subprocess.run(
                ["git", "-C", str(git_root), "check-ignore", "--no-index", "-z", "--stdin"],
                input=input_data,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if completed.returncode not in {0, 1}:
            continue
        ignored_relative = set(filter(None, completed.stdout.split("\0")))
        ignored.update(path for path, relative in candidates if relative in ignored_relative)
    return ignored


def _selected_file_paths(
    path_values: tuple[str, ...], *, ignore_gitignore: bool
) -> tuple[list[Path], set[Path]]:
    direct_files = {Path(raw_path) for raw_path in path_values if Path(raw_path).is_file()}
    all_paths = list(iter_files(path_values))
    recursive_roots = [Path(raw_path) for raw_path in path_values if Path(raw_path).is_dir()]
    ignored = set()
    if not ignore_gitignore and recursive_roots:
        roots = [
            (input_root, git_root)
            for input_root in recursive_roots
            if (git_root := _git_root(input_root)) is not None
        ]
        ignored = _ignored_paths(
            [path for path in all_paths if path not in direct_files],
            roots,
        )
    return [path for path in all_paths if path not in ignored], ignored


def iter_selected_files(paths: Iterable[str], *, ignore_gitignore: bool = False) -> Iterator[Path]:
    selected, _ = _selected_file_paths(tuple(paths), ignore_gitignore=ignore_gitignore)
    yield from selected


def collect_files(
    paths: Iterable[str],
    include_images: bool,
    *,
    ignore_gitignore: bool = False,
    parallel: int = 1,
) -> ContentBundle:
    items = []
    binary_paths: list[Path] = []
    path_values = tuple(paths)
    direct_files = {Path(raw_path) for raw_path in path_values if Path(raw_path).is_file()}
    selected, ignored = _selected_file_paths(path_values, ignore_gitignore=ignore_gitignore)

    def collect_one(path: Path) -> tuple[Path, ContentItem | None, bool]:
        data = path.read_bytes()
        direct_file = path in direct_files
        image_file = is_image_path(path) or is_image_data(data)
        if image_file and (include_images or direct_file):
            item = read_file_item(
                path,
                include_images,
                force_image=direct_file or include_images,
                data=data,
                image_detected=True,
            )
            return path, item, False
        if image_file:
            return path, None, False
        if is_binary_data(data):
            return path, None, True
        item = read_file_item(
            path,
            include_images,
            force_image=path in direct_files,
            data=data,
            image_detected=False,
        )
        return path, item, False

    results = ordered_map(collect_one, selected, parallel)
    for path, item, is_binary in results:
        if is_binary:
            binary_paths.append(path)
        elif item is not None:
            items.append(item)
    return ContentBundle(
        tuple(items),
        facts={
            "file_count": len(items),
            "ignored_file_count": len(ignored),
            "binary_file_count": len(binary_paths),
            "binary_files": [str(path) for path in binary_paths],
            "input_paths": list(path_values),
        },
    )


def read_stdin_item() -> ContentItem:
    data = sys.stdin.buffer.read()
    return ContentItem(
        item_id="stdin",
        origin="stdin",
        label="-",
        kind=ContentKind.TEXT,
        payload=_decode_text(data),
    )
