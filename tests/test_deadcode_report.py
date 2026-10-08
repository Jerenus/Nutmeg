import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deadcode_report.py"
SPEC = importlib.util.spec_from_file_location("deadcode_report", SCRIPT)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> Path:
    _write(root, "nutmeg/__init__.py")
    _write(root, "nutmeg/interfaces/__init__.py")
    _write(root, "nutmeg/interfaces/cli/__init__.py", (
        "import typer\napp = typer.Typer()\n"
        "@app.command('go')\ndef go():\n    from nutmeg.core import used\n    used()\n"))
    _write(root, "nutmeg/core.py", (
        "def used():\n    return 1\n\n"
        "def never_called():\n    return 2\n\n"
        "def only_tests():\n    return 3\n\n"
        "class Thing:\n    def __init__(self):\n        pass\n"
        "    def used_method(self):\n        return 4\n"))
    _write(root, "nutmeg/orphan.py", "def lonely():\n    return 5\n")
    _write(root, "nutmeg/web/__init__.py")           # empty package marker: not code
    _write(root, "scripts/job.py", "from nutmeg.core import Thing\nThing().used_method()\n")
    _write(root, "tests/test_core.py", "from nutmeg.core import only_tests\n")
    return root


def test_analyze_classifies_dead_modules_noref_and_testonly(tmp_path: Path) -> None:
    result = report.analyze(_repo(tmp_path))
    assert [m["module"] for m in result["unreachable_modules"]] == ["nutmeg.orphan"]
    assert [r["name"] for r in result["noref"]] == ["never_called"]
    assert [r["name"] for r in result["testonly"]] == ["only_tests"]


def test_main_writes_report_and_latest_with_trend(tmp_path: Path) -> None:
    repo, out = _repo(tmp_path / "repo"), tmp_path / "out"
    assert report.main(["--repo", str(repo), "--out", str(out), "--day", "2026-10-12"]) == 0
    assert report.main(["--repo", str(repo), "--out", str(out), "--day", "2026-10-19"]) == 0
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert latest["day"] == "2026-10-19" and latest["candidates"] == 3
    text = (out / "2026-10-19.md").read_text(encoding="utf-8")
    assert "上次 2026-10-12：3 个" in text and "`nutmeg/orphan.py`" in text
