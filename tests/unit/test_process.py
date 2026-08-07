from __future__ import annotations

import shlex
import sys
from pathlib import Path

from context_stat.adapters.process import run_for_path


def command_for(script: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


def test_command_output_is_bounded_while_process_is_running() -> None:
    execution = run_for_path(
        command_for("import sys; sys.stdout.write('o' * 1000000); sys.stderr.write('e' * 1000000)"),
        Path("example.txt"),
        max_output_bytes=128,
    )

    assert execution.returncode == 0
    assert len(execution.stdout) <= 128
    assert len(execution.stderr) <= 128
    assert b"stdout exceeded 128 bytes" in execution.stderr
    assert b"stderr exceeded 128 bytes" in execution.stderr


def test_command_timeout_terminates_a_running_process() -> None:
    execution = run_for_path(
        command_for("import time; time.sleep(30)"),
        Path("example.txt"),
        timeout_seconds=0.1,
        max_output_bytes=128,
    )

    assert execution.timed_out is True
    assert execution.returncode is not None


def test_truncation_state_is_available_with_a_small_output_limit() -> None:
    execution = run_for_path(
        command_for("import sys; sys.stdout.write('out'); sys.stderr.write('err')"),
        Path("example.txt"),
        max_output_bytes=1,
    )

    assert execution.stdout_truncated is True
    assert execution.stderr_truncated is True
