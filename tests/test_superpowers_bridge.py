from pathlib import Path

from nutmeg.process.superpowers import inspect_superpowers_bridge


def test_superpowers_bridge_report_is_ready_for_workspace_install() -> None:
    report = inspect_superpowers_bridge(Path.cwd())

    assert report.extension_installed is True
    assert report.verdict == 'READY'
    assert any(
        skill.name == 'test-driven-development' and skill.status == 'READY'
        for skill in report.skills
    )
    assert any(
        hook.command == 'speckit.superb.verify' and hook.status == 'READY'
        for hook in report.hooks
    )
