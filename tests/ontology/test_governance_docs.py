from pathlib import Path

DESIGN = "docs/superpowers/specs/2026-08-24-nutmeg-intelligence-os-design.md"
RETIRED_PLAN = ".specify/specs/046-jczq-mixed-parlay-report-v0/plan.md"


def test_agent_harnesses_point_to_the_current_intelligence_os_design() -> None:
    for path in (Path("AGENTS.md"), Path("CLAUDE.md")):
        text = path.read_text(encoding="utf-8")
        assert DESIGN in text
        assert RETIRED_PLAN not in text


def test_operations_doc_names_non_mutating_status_contract() -> None:
    text = Path("docs/ontology-kernel-operations.md").read_text(encoding="utf-8")
    assert "uv run nutmeg ontology init --format json" in text
    assert "uv run nutmeg ontology status --format json" in text
    assert "status never initializes or migrates the database" in text


def test_runbook_names_strict_operator_evidence_shadow_bridge() -> None:
    text = Path("docs/sop/RUNBOOK.md").read_text(encoding="utf-8")

    assert "workflow ingest-evidence --manifest" in text
    assert "operator-evidence-policy-v1" in text
    assert "v2" in text and "shadow" in text


def test_lower_sop_uses_constitutional_candidate_ordering() -> None:
    runbook = Path("docs/sop/RUNBOOK.md").read_text(encoding="utf-8")
    rulebook = Path("docs/sop/RULEBOOK.md").read_text(encoding="utf-8")

    required = (
        "帽内按 P(全对) 降序",
        "同 P 依次按票价升序、内容哈希升序",
        "回本线/官方中位倍数只作报告",
        "不排序、不阻断、不自动建议空仓",
    )
    for phrase in required:
        assert phrase in runbook
        assert phrase in rulebook
    assert "按回本线升序取档，不按 P 降序" not in runbook
    assert "帽内回本线最小" not in rulebook
