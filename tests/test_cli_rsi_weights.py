from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()
REGISTRY = Path(__file__).resolve().parents[1] / "experiments" / "factors.json"


def _corpus(tmp_path: Path, n: int = 120) -> Path:
    rows = []
    for i in range(n):
        passed = i % 2 == 0
        rows.append(
            {
                "date": f"2026-09-{(i % 28) + 1:02d}",
                "actual": "3" if (i * 7919) % 100 < 50 else "0",
                "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
                "labels": {"anchor_integrity": "pass" if passed else "fail"},
                "provably_prospective": True,
            }
        )
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return path


def test_weights_propose_outputs_decision_and_never_writes_registry(tmp_path):
    before = REGISTRY.read_bytes()
    result = runner.invoke(
        app,
        [
            "rsi", "weights", "propose", "--factor", "anchor_integrity",
            "--corpus", str(_corpus(tmp_path)), "--n-perm", "20",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["factor_id"] == "anchor_integrity"
    assert payload["decision"] in {"propose_zero", "propose_change", "hold"}
    assert payload["writes_weights"] is False
    assert payload["current_weight_pp"] == 0.0
    assert REGISTRY.read_bytes() == before


def test_weights_propose_requires_a_factor_and_rejects_unknown_ids(tmp_path):
    missing = runner.invoke(app, ["rsi", "weights", "propose", "--corpus", str(_corpus(tmp_path))])
    assert missing.exit_code == 1
    assert "--factor" in missing.output
    unknown = runner.invoke(
        app,
        ["rsi", "weights", "propose", "--factor", "nope", "--corpus", str(_corpus(tmp_path))],
    )
    assert unknown.exit_code == 1
    assert "未登记" in unknown.output
