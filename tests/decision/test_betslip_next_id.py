"""实票票号由服务端分配（2026-10-28 第 4 阶段）：`register_slip` 同 slip_id 覆盖，
页面不能自己编号。"""
from nutmeg.decision.betslip import BetSlip, next_slip_id, register_slip

_FACES = {str(i): "3" for i in range(1, 10)}


def _put(data_dir, slip_id: str, issue: str = "26151") -> None:
    register_slip(data_dir, BetSlip(slip_id=slip_id, channel="renjiu", placed_at="2026-10-28",
                                    legs=[], issue=issue, faces=dict(_FACES)))


def test_empty_registry_starts_at_t1(tmp_path):
    assert next_slip_id(tmp_path, "26151") == "26151-T1"


def test_max_t_plus_one_ignores_b1_and_other_suffixes(tmp_path):
    for sid in ("26151-T1", "26151-T3", "26151-B1", "26151-T2x", "26151-Tx"):
        _put(tmp_path, sid)
    assert next_slip_id(tmp_path, "26151") == "26151-T4"


def test_other_issues_do_not_count(tmp_path):
    _put(tmp_path, "26150-T7", issue="26150")
    _put(tmp_path, "26151-T1")
    assert next_slip_id(tmp_path, "26151") == "26151-T2"
    assert next_slip_id(tmp_path, "26152") == "26152-T1"
