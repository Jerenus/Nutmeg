import datetime as dt
import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[2] / "experiments" / "attempts.py"
_SPEC = importlib.util.spec_from_file_location("attempts", _PATH)
assert _SPEC and _SPEC.loader
attempts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(attempts)


def test_log_attempt_creates_header_and_appends_one_flat_line(tmp_path):
    path = tmp_path / "attempts.log"
    stamp = dt.datetime(2026, 9, 22, 13, 5)
    first = attempts.log_attempt(
        "hyp 方向旗→非模态",
        {"n": 76},
        "R=-2.8pp\nCI[-13.7,+8.4]",
        "证伪 | 欠功效",
        path=path,
        ts=stamp,
    )
    second = attempts.log_attempt("x", None, "", "hold", path=path, ts=stamp)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(attempts.HEADER)
    assert first == (
        "2026-09-22T13:05 | hyp 方向旗→非模态 | {'n': 76} | "
        "R=-2.8pp CI[-13.7,+8.4] | 证伪 / 欠功效\n"
    )
    assert second == "2026-09-22T13:05 | x |  |  | hold\n"
    assert text.count("\n") == 4  # two header lines + two entries


def test_log_attempt_appends_without_rewriting_existing_entries(tmp_path):
    path = tmp_path / "attempts.log"
    path.write_text("# custom header\nold line | kept\n", encoding="utf-8")
    attempts.log_attempt("e", "p", "r", "c", path=path, ts=dt.datetime(2026, 9, 22, 0, 0))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# custom header", "old line | kept"]
    assert lines[2].endswith("| e | p | r | c")
