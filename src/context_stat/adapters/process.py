from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import BinaryIO

from context_stat.adapters.templating import render_command


@dataclass(frozen=True)
class CommandExecution:
    argv: tuple[str, ...]
    stdout: bytes
    stderr: bytes
    returncode: int | None
    duration_seconds: float
    timed_out: bool = False
    start_error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False


@dataclass
class _StreamCapture:
    data: bytearray
    truncated: bool = False


def _read_limited(stream: BinaryIO, capture: _StreamCapture, limit: int) -> None:
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = limit - len(capture.data)
            if remaining > 0:
                capture.data.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                capture.truncated = True
    except (OSError, ValueError):
        return


def _bounded_stderr(data: bytes, notices: list[bytes], limit: int) -> bytes:
    notice = b"".join(notices)
    if len(notice) >= limit:
        return notice[-limit:]
    return data[: limit - len(notice)] + notice


def run_for_path(
    template: str,
    path: Path,
    *,
    timeout_seconds: float = 30.0,
    max_output_bytes: int = 10_000_000,
) -> CommandExecution:
    argv = render_command(template, path)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        return CommandExecution(
            argv=tuple(argv),
            stdout=b"",
            stderr=b"",
            returncode=None,
            duration_seconds=time.monotonic() - started,
            start_error=f"could not start command: {exc}",
        )
    stdout_capture = _StreamCapture(bytearray())
    stderr_capture = _StreamCapture(bytearray())
    readers = [
        Thread(
            target=_read_limited,
            args=(process.stdout, stdout_capture, max_output_bytes),
            daemon=True,
        ),
        Thread(
            target=_read_limited,
            args=(process.stderr, stderr_capture, max_output_bytes),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
    finally:
        for reader in readers:
            reader.join(timeout=2)
        for stream, reader in zip((process.stdout, process.stderr), readers, strict=True):
            if reader.is_alive():
                stream.close()
                reader.join(timeout=1)
    duration = time.monotonic() - started
    notices = []
    if stdout_capture.truncated:
        notices.append(f"\nstdout exceeded {max_output_bytes} bytes and was truncated\n".encode())
    if stderr_capture.truncated:
        notices.append(f"\nstderr exceeded {max_output_bytes} bytes and was truncated\n".encode())
    return CommandExecution(
        argv=tuple(argv),
        stdout=bytes(stdout_capture.data),
        stderr=_bounded_stderr(bytes(stderr_capture.data), notices, max_output_bytes),
        returncode=process.returncode,
        duration_seconds=duration,
        timed_out=timed_out,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
    )
