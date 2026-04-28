from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'acceptance.sh'


def test_acceptance_script_dry_run_prints_no_network_plan() -> None:
    result = subprocess.run(
        ['bash', str(SCRIPT), '--dry-run'],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert 'mode=dry-run' in result.stdout
    assert 'uv run nutmeg doctor --format json' in result.stdout
    assert 'uv run nutmeg agent-status --format json' in result.stdout
    assert 'uv run nutmeg fixtures --league epl --demo' in result.stdout
    assert 'fixtures-sync' not in result.stdout


def test_acceptance_script_live_requires_api_football_key() -> None:
    env = os.environ.copy()
    env.pop('NUTMEG_API_FOOTBALL_KEY', None)
    result = subprocess.run(
        ['bash', str(SCRIPT), '--live'],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode == 2
    assert 'NUTMEG_API_FOOTBALL_KEY is required for --live acceptance' in result.stderr


def test_acceptance_script_help_and_makefile_target_are_discoverable() -> None:
    help_result = subprocess.run(
        ['bash', str(SCRIPT), '--help'],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    makefile = (ROOT / 'Makefile').read_text()

    assert help_result.returncode == 0
    assert '--dry-run' in help_result.stdout
    assert '--live' in help_result.stdout
    assert 'acceptance:' in makefile
    assert 'scripts/acceptance.sh' in makefile
