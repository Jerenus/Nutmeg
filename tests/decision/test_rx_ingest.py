from nutmeg.decision.rx_ingest import map_rx_adjudications, map_rx_predictions

RX = {
    "issue": "26111",
    "predictions": [
        {"id": "P1", "claim": "悬置持平4场至少2平", "falsifier": "≤1场平→o条降级"},
        {"id": "P2", "claim": "皇马不至于输球", "falsifier": "皇社客胜→0/9追加"},
    ],
    "pending_adjudications": [
        {"id": "ADJ-2", "status": "我已裁", "q": "场9借场不挂旗", "reason": "单向削弱"},
        {
            "id": "ADJ-8",
            "status": "用户行权(大胆SFC≤600)",
            "q": "SFC486九胆",
            "evidence_rejected": "五条裸胆违审计",
        },
        {"id": "ADJ-1", "status": "需你裁", "q": "场3裸单 vs o条"},
    ],
}


def test_map_predictions_are_issue_scoped():
    reqs = map_rx_predictions(RX, "26111")
    assert len(reqs) == 2
    assert reqs[0]["subject_type"] == "issue" and reqs[0]["subject_id"] == "26111"
    assert reqs[0]["match_id"] is None
    assert reqs[0]["idempotency_key"] == "rx:26111:P1"
    assert reqs[0]["claim"] == "悬置持平4场至少2平"


def test_map_predictions_deduplicates_claims_and_preserves_alias_ids():
    rx = {
        "predictions": [
            {"id": "S1", "claim": "同一断言", "falsifier": "不成立"},
            {"id": "P5", "claim": "同一断言", "falsifier": "不成立"},
            {"id": "P6", "claim": "另一断言", "falsifier": "不成立"},
        ]
    }

    reqs = map_rx_predictions(rx, "26129")

    assert len(reqs) == 2
    assert reqs[0]["idempotency_key"] == "rx:26129:S1"
    assert reqs[0]["alias_ids"] == ["S1", "P5"]
    assert reqs[1]["alias_ids"] == ["P6"]


def test_map_adjudications_resolved_only():
    reqs, skipped = map_rx_adjudications(RX, "26111")
    assert [r["idempotency_key"] for r in reqs] == ["rx:26111:ADJ-2", "rx:26111:ADJ-8"]
    assert reqs[0]["decision"] == "approve"
    assert reqs[1]["decision"] == "override"
    assert reqs[1]["evidence_rejected"] == [{"type": "note", "id": "五条裸胆违审计"}]
    assert skipped == ["ADJ-1: 未决(需你裁)"]


# ── 批量判定映射（2026-09-11） ──

def test_map_rx_gradings_bridges_human_ids_to_idempotency_keys():
    """rx 用 P1..Pn，本体存 prediction-<hex>；唯一稳定的桥是注册时的幂等键。

    出生事故 26121：13 条预测判定前要先去 sqlite 里按 claim 文本对号，对了两轮。
    """
    from nutmeg.decision.rx_ingest import map_rx_gradings

    rx = {"predictions": [
        {"id": "P1", "claim": "场1 主胜", "falsifier": "不胜", "outcome": "hit"},
        {"id": "P2", "claim": "场2 平", "falsifier": "非平", "outcome": "MISS",
         "outcome_reason": "官方串场2=3"},
        {"id": "P3", "claim": "场3 客胜", "falsifier": "非客", "outcome": None},
    ]}
    gradings, skipped = map_rx_gradings(rx, "26122")
    assert [g["rx_id"] for g in gradings] == ["P1", "P2"]
    assert gradings[0]["idempotency_key"] == "rx:26122:P1"
    assert gradings[1]["outcome"] == "miss"                 # 大小写规约
    assert gradings[1]["reason"] == "官方串场2=3"           # 优先用显式理由
    assert skipped == ["P3: 未判定(None)"]


def test_map_rx_gradings_rejects_unknown_outcome_words():
    """只认 hit/miss/na——"✓"/"部分命中"这类自由文本必须落回未判定，不猜。"""
    from nutmeg.decision.rx_ingest import map_rx_gradings

    _, skipped = map_rx_gradings(
        {"predictions": [{"id": "P1", "claim": "c", "falsifier": "f", "outcome": "✓"}]},
        "26122")
    assert skipped and "P1" in skipped[0]
