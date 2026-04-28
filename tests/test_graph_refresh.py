from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_graph_refresh_generates_report_and_json_assets(tmp_path) -> None:
    output_dir = tmp_path / 'graphify-out'

    result = subprocess.run(
        [
            'python3',
            'scripts/refresh_graph.py',
            '--project-root',
            str(ROOT),
            '--output-dir',
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    report = output_dir / 'GRAPH_REPORT.md'
    graph_json = output_dir / 'graph.json'
    assert report.exists()
    assert graph_json.exists()
    text = report.read_text()
    assert '# Nutmeg Code Graph Report' in text
    assert '## Package Communities' in text
    assert '## High-Degree Modules' in text
    assert '## Dependency Edges' in text


def test_graph_refresh_records_known_internal_dependencies(tmp_path) -> None:
    output_dir = tmp_path / 'graphify-out'
    subprocess.run(
        [
            'python3',
            'scripts/refresh_graph.py',
            '--project-root',
            str(ROOT),
            '--output-dir',
            str(output_dir),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads((output_dir / 'graph.json').read_text())
    edges = {(edge['source'], edge['target']) for edge in payload['edges']}

    assert ('nutmeg.interfaces.cli', 'nutmeg.services.analysis') in edges
    assert ('nutmeg.services.snapshot', 'nutmeg.domain.snapshot') in edges
    assert payload['module_count'] >= 40


def test_graph_refresh_is_discoverable_from_makefile_and_docs() -> None:
    makefile = (ROOT / 'Makefile').read_text()
    overview = (ROOT / 'docs' / 'architecture' / 'overview.md').read_text()

    assert 'graph:' in makefile
    assert 'scripts/refresh_graph.py' in makefile
    assert 'GRAPH_REPORT.md' in overview
