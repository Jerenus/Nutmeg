"""jczq-today --refresh-check 与 jczq-report CLI。"""
from __future__ import annotations

from nutmeg.interfaces.cli.jczq import _board_changed


def test_board_changed_detects_new_match() -> None:
    # 真实快照结构：matchInfoList（按日分组）→ subMatchList → matchNumStr
    # （对齐 bold_matches_from_sporttery 的解析口径）。
    old = {"matchInfoList": [{"subMatchList": [{"matchNumStr": "周四001"}]}]}
    new = {
        "matchInfoList": [
            {
                "subMatchList": [
                    {"matchNumStr": "周四001"},
                    {"matchNumStr": "周四002"},
                ]
            }
        ]
    }
    assert _board_changed(old, new) is True
    assert _board_changed(old, old) is False


def test_board_changed_none_snapshot_means_changed() -> None:
    assert _board_changed(None, {"matchInfoList": []}) is True
