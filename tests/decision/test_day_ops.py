import plistlib
from datetime import date, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_ops import launchd_rows

BJ = timezone(timedelta(hours=8))
LAUNCHCTL = (
    "-\t0\tcom.nutmeg.rsi.loop\n"
    "-\t2\tcom.nutmeg.jczq.results-backfill\n"
    "123\t0\tcom.apple.foo\n"
)


def _plist(path: Path, label: str, hour: int, minute: int, program: str) -> None:
    path.write_bytes(plistlib.dumps({
        "Label": label,
        "ProgramArguments": ["/bin/zsh", "-lc", program],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
    }))


def test_launchd_rows_pair_each_label_with_time_evidence(tmp_path: Path):
    plists, logs = tmp_path / "plists", tmp_path / "logs"
    plists.mkdir()
    logs.mkdir()
    _plist(plists / "com.nutmeg.rsi.loop.plist", "com.nutmeg.rsi.loop", 10, 45,
           "uv run nutmeg rsi loop")
    _plist(plists / "com.nutmeg.jczq.results-backfill.plist", "com.nutmeg.jczq.results-backfill",
           9, 30, "uv run python scripts/jczq_result_backfill.py")
    _plist(plists / "com.nutmeg.decision.close.plist", "com.nutmeg.decision.close", 19, 0, "x")
    out = logs / "rsi.loop.out.log"
    out.write_text("RSI 闭环 2026-09-23：9 步，失败 0\n", encoding="utf-8")
    err = logs / "jczq.results-backfill.out.log"
    err.write_text("⚠️RESULTS_STALE lag=3d\n", encoding="utf-8")
    rows = launchd_rows(plists_dir=plists, logs_dir=logs, launchctl_text=LAUNCHCTL,
                        today=date(2026, 9, 23))
    by = {r["label"]: r for r in rows}
    rsi = by["com.nutmeg.rsi.loop"]
    assert rsi["schedule"] == "10:45" and rsi["loaded"] is True
    assert rsi["last_exit"] == "0" and rsi["log_at"] is not None
    backfill = by["com.nutmeg.jczq.results-backfill"]
    assert backfill["last_exit"] == "2"
    assert backfill["alarm"] is True
    close = by["com.nutmeg.decision.close"]
    assert close["loaded"] is False and close["log_at"] is None
    assert [r["label"] for r in rows] == sorted(by)  # stable order by label



def test_monthly_job_is_not_stale_three_weeks_after_its_run(tmp_path: Path):
    import os
    from datetime import datetime

    plists, logs = tmp_path / "plists", tmp_path / "logs"
    plists.mkdir()
    logs.mkdir()
    (plists / "com.nutmeg.account.month.plist").write_bytes(plistlib.dumps({
        "Label": "com.nutmeg.account.month", "ProgramArguments": ["/bin/zsh", "-lc", "x"],
        "StartCalendarInterval": {"Day": 1, "Hour": 16, "Minute": 10}}))
    out = logs / "account.month.out.log"
    out.write_text("NUTMEG_OK account month 2026-10-01\n", encoding="utf-8")
    stamp = datetime(2026, 10, 1, 16, 11).timestamp()
    os.utime(out, (stamp, stamp))
    launchctl = "-\t0\tcom.nutmeg.account.month\n"
    [row] = launchd_rows(plists_dir=plists, logs_dir=logs, launchctl_text=launchctl,
                         today=date(2026, 10, 22))
    assert row["schedule"] == "每月 1 日 16:10" and row["alarm"] is False
    [late] = launchd_rows(plists_dir=plists, logs_dir=logs, launchctl_text=launchctl,
                          today=date(2026, 11, 5))
    assert late["alarm"] is True                        # 11-01 没跑 → 11-05 报警
