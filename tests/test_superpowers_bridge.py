from pathlib import Path

from nutmeg.process.superpowers import inspect_superpowers_bridge


def test_superpowers_bridge_report_is_ready_for_workspace_install() -> None:
    report = inspect_superpowers_bridge(Path.cwd())

    assert report.verdict == 'READY'
    assert any(
        skill.name == 'test-driven-development' and skill.status == 'READY'
        for skill in report.skills
    )


def test_superpowers_bridge_blocks_when_required_skill_missing(tmp_path: Path) -> None:
    report = inspect_superpowers_bridge(tmp_path, home_root=tmp_path / "home")

    assert report.verdict == 'BLOCKED'
    assert all(skill.status == 'MISSING' for skill in report.skills)
