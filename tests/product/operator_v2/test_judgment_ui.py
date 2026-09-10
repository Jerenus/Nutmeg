from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nutmeg.interfaces.operator_ui import mount_operator_ui
from nutmeg.product.operator_contracts import (
    BaselineEnvelopeEditorView,
    BaselineEnvelopeOfferView,
    BaselineEnvelopeStructureView,
    BusinessEvidenceSummary,
    JudgeMatchesStep,
    JudgmentFaceView,
    JudgmentFactorView,
    JudgmentRuleView,
    MatchJudgmentEditorView,
    OperatorLane,
    OperatorTaskResponse,
    OperatorTaskState,
    OperatorTaskSummary,
    TaskProgressSummary,
)

NOW = datetime(2026, 9, 4, 9, tzinfo=UTC)
OPAQUE_ENVELOPE_TOKEN = "opaque.envelope-command-token"
OPAQUE_JUDGMENT_TOKEN = "opaque.judgment-command-token"
OPAQUE_PRESCRIPTION_TOKEN = "opaque.prescription-command-token"


def _step(mode: str) -> JudgeMatchesStep:
    return JudgeMatchesStep(
        task_id="jczq:2026-09-04",
        item_key="current-match",
        title="逐场登记判断",
        prompt="",
        options=[],
        mode=mode,
        comparison_only=True,
        completed_match_count=0 if mode == "match_judgment" else 1,
        required_match_count=1,
        envelope_command_token=OPAQUE_ENVELOPE_TOKEN,
        judgment_command_token=OPAQUE_JUDGMENT_TOKEN,
        prescription_command_token=OPAQUE_PRESCRIPTION_TOKEN,
        judgment_revision_tokens=["opaque.judgment-revision-token"],
        envelope=BaselineEnvelopeEditorView(
            lane=OperatorLane.JCZQ,
            ticket_kinds=["jczq_pass"],
            currency="CNY",
            capital_cap_minor=20000,
            maximum_ticket_count=2,
            maximum_exhaustive_candidate_count=100,
            offers=[
                BaselineEnvelopeOfferView(
                    official_match_no="001",
                    match_label="水晶宫 - 曼彻斯特城",
                    market_code="had",
                    market_label="胜平负",
                    face_bundles=[
                        {"bundle_code": "home", "face_codes": ["3"]},
                        {"bundle_code": "home_draw", "face_codes": ["3", "1"]},
                    ],
                    omission_available=False,
                )
            ],
            structures=[
                BaselineEnvelopeStructureView(
                    kind="jczq_pass",
                    structure_code="single-1",
                    structure_label="单关",
                    eligible_official_match_nos=["001"],
                    pass_size=1,
                    required_offer_count=1,
                    maximum_groups=1,
                )
            ],
        ),
        editor=MatchJudgmentEditorView(
            official_match_no="001",
            match_label="水晶宫 - 曼彻斯特城",
            competition_label="英格兰足总杯",
            kickoff_at=NOW,
            sale_deadline_at=NOW,
            market_code="had",
            market_label="胜平负",
            evidence=[
                BusinessEvidenceSummary(
                    label="E1 身份对齐",
                    value="已核对",
                    source_label="官方赛程",
                    freshness_label="09:00",
                )
            ],
            evidence_ref_tokens=["evidence:lineup:001"],
            faces=[
                JudgmentFaceView(
                    face_code="3",
                    face_label="主胜",
                    prior_probability_decimal="0.400000000000",
                    movement_pp_decimal="0.020000000000",
                    belief_probability_decimal="0.400000000000",
                ),
                JudgmentFaceView(
                    face_code="1",
                    face_label="平",
                    prior_probability_decimal="0.300000000000",
                    movement_pp_decimal="-0.010000000000",
                    belief_probability_decimal="0.300000000000",
                ),
                JudgmentFaceView(
                    face_code="0",
                    face_label="客胜",
                    prior_probability_decimal="0.300000000000",
                    movement_pp_decimal="-0.010000000000",
                    belief_probability_decimal="0.300000000000",
                ),
            ],
            factors=[
                JudgmentFactorView(
                    factor_id="factor-lineup-v1",
                    label="首发结构变化",
                    scope_key="match:001",
                    evidence_ref_tokens=["evidence:lineup:001"],
                )
            ],
            rules=[JudgmentRuleView(rule_id="k", label="k · 硬信息优先")],
            face_bundles=[
                {"bundle_code": "home", "face_codes": ["3"]},
                {"bundle_code": "home_draw", "face_codes": ["3", "1"]},
            ],
        ),
    )


class _Queries:
    def __init__(self, mode: str) -> None:
        selected = OperatorTaskSummary(
            task_id="jczq:2026-09-04",
            lane=OperatorLane.JCZQ,
            business_key="2026-09-04",
            title="竞彩 2026-09-04",
            state=OperatorTaskState.JUDGE_MATCHES,
            deadline_at=NOW,
            is_actionable=True,
            next_action_label="登记逐场判断",
            priority_rank=0,
        )
        self.response = OperatorTaskResponse(
            as_of=NOW,
            mutation_token="d" * 64,
            selected=selected,
            alternatives=[],
            progress=TaskProgressSummary(completed=0, total=1, label="逐场判断"),
            step=_step(mode),
        )

    def task(self, _task_id: str, *, as_of):
        return self.response

    def worklist(self, *, as_of):
        return SimpleNamespace(selected=self.response.selected, tasks=[], as_of=as_of)


def _client(mode: str, *, read_only: bool = False) -> TestClient:
    app = FastAPI()
    mount_operator_ui(
        app,
        SimpleNamespace(operator_queries=_Queries(mode)),
        lambda: NOW,
        read_only=read_only,
    )
    return TestClient(app)


def test_baseline_envelope_uses_named_controls_without_json_editor() -> None:
    html = _client("baseline_envelope").get("/tasks/jczq:2026-09-04").text

    assert "市场基线" in html and "仅用于比较" in html
    assert "资金上限" in html and "胜平负" in html and "单关" in html
    assert 'data-action="record-baseline-envelope"' in html
    assert 'name="capital_cap_minor"' in html
    assert 'name="allowed_face_bundle"' in html
    assert OPAQUE_ENVELOPE_TOKEN in html
    assert "textarea" not in html
    assert "payload_json" not in html


def test_match_judgment_renders_evidence_prior_movement_and_typed_fields() -> None:
    html = _client("match_judgment").get("/tasks/jczq:2026-09-04").text

    for visible in (
        "水晶宫 - 曼彻斯特城",
        "英格兰足总杯",
        "E1 身份对齐",
        "市场先验",
        "盘面变化",
        "你的概率",
        "首发结构变化",
        "k · 硬信息优先",
        "证伪条件",
        "判断理由",
    ):
        assert visible in html
    assert 'data-action="commit-match-judgment"' in html
    assert 'data-face-code="3"' in html
    assert 'name="factor_id"' in html
    assert 'name="rule_id"' in html
    assert 'name="face_bundle"' in html
    assert OPAQUE_JUDGMENT_TOKEN in html


def test_completed_judgments_offer_explicit_prescription_freeze() -> None:
    html = _client("prescription_ready").get("/tasks/jczq:2026-09-04").text

    assert "1 / 1" in html
    assert 'data-action="freeze-judgment-prescription"' in html
    assert OPAQUE_PRESCRIPTION_TOKEN in html


def test_judgment_surface_hides_raw_json_internal_ids_and_ai_authority() -> None:
    for mode in ("baseline_envelope", "match_judgment", "prescription_ready"):
        html = _client(mode).get("/tasks/jczq:2026-09-04").text
        assert "<pre" not in html
        assert "{" not in html
        assert not re.search(r"\b[0-9a-f]{64}\b", html)
        for forbidden in (
            "action_id",
            "bundle_id",
            "content_hash",
            "payload_json",
            'name="actor_id"',
            'name="actor_role"',
            "deterministic_system",
        ):
            assert forbidden not in html


def test_read_only_judgment_surface_contains_no_mutation_form() -> None:
    html = _client("match_judgment", read_only=True).get(
        "/tasks/jczq:2026-09-04"
    ).text

    assert "水晶宫 - 曼彻斯特城" in html
    assert "只读模式" in html
    assert "data-action=" not in html


def test_match_judgment_asks_for_the_anchor_and_excluded_face_precedents() -> None:
    html = _client("match_judgment").get("/tasks/jczq:2026-09-04").text

    for visible in ("锚方结构完整度", "被排面先例", "完整", "有洞", "载体已不在"):
        assert visible in html
    assert 'name="anchor_integrity"' in html
    assert 'value="pass"' in html
    assert 'value="fail"' in html
    assert 'value="symmetric_damage"' in html
    assert 'name="precedent_ref"' in html
    assert 'name="precedent_status"' in html
    assert 'data-precedent-face-code="3"' in html
    assert 'data-precedent-face-code="0"' in html
