from pathlib import Path

PLAN = "docs/superpowers/plans/2026-07-21-ontology-kernel-v2-package-1.md"
RETIRED_PLAN = ".specify/specs/046-jczq-mixed-parlay-report-v0/plan.md"


def test_agent_harnesses_point_to_the_current_package_plan() -> None:
    for path in (Path("AGENTS.md"), Path("CLAUDE.md")):
        text = path.read_text(encoding="utf-8")
        assert PLAN in text
        assert RETIRED_PLAN not in text


def test_operations_doc_names_non_mutating_status_contract() -> None:
    text = Path("docs/ontology-kernel-operations.md").read_text(encoding="utf-8")
    assert "uv run nutmeg ontology init --format json" in text
    assert "uv run nutmeg ontology status --format json" in text
    assert "status never initializes or migrates the database" in text
