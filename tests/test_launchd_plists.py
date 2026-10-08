import plistlib
from pathlib import Path

PLISTS = Path("ops/launchd")
EXPECTED = {
    # 15:45 第二趟：美洲晚场 09:45 常未封存（2026-09-30 执行链追补）
    "com.nutmeg.day.settle": ("09:45,15:45", "day run --job results", "day run --job settle"),
    # 2026-10-08：末两步（intake + jczq-build-reads）合成 research refresh，intake 不再一轮跑 3 次
    "com.nutmeg.jczq.research": ("10:00", "research run --day", "research refresh --day"),
    "com.nutmeg.day.brief": (
        "12:00,14:20,18:35", "day run --job brief", "--with-logic", "day publish",
    ),
    "com.nutmeg.day.broadcast": ("every 600s", "day run --job broadcast"),
    "com.nutmeg.rsi.loop": ("10:45", "rsi loop"),
}


def _schedule(doc: dict) -> str:
    if "StartInterval" in doc:
        return f"every {doc['StartInterval']}s"
    cal = doc["StartCalendarInterval"]
    cal = cal if isinstance(cal, list) else [cal]
    return ",".join(f"{c['Hour']:02d}:{c.get('Minute', 0):02d}" for c in cal)


def test_every_plist_is_wellformed_and_self_consistent():
    for path in sorted(PLISTS.glob("com.nutmeg.*.plist")):
        doc = plistlib.loads(path.read_bytes())
        assert doc["Label"] == path.stem, path
        assert doc["ProgramArguments"], path
        assert "StartCalendarInterval" in doc or "StartInterval" in doc, path


def test_daily_surface_plists_call_expected_commands():
    for label, (schedule, *fragments) in EXPECTED.items():
        doc = plistlib.loads((PLISTS / f"{label}.plist").read_bytes())
        assert _schedule(doc) == schedule, label
        program = " ".join(doc["ProgramArguments"])
        for fragment in fragments:
            assert fragment in program, (label, fragment)
