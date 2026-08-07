from __future__ import annotations

from context_stat.output import _ascii_table, _display_width


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
