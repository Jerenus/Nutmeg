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


def test_map_adjudications_resolved_only():
    reqs, skipped = map_rx_adjudications(RX, "26111")
    assert [r["idempotency_key"] for r in reqs] == ["rx:26111:ADJ-2", "rx:26111:ADJ-8"]
    assert reqs[0]["decision"] == "approve"
    assert reqs[1]["decision"] == "override"
    assert reqs[1]["evidence_rejected"] == [{"type": "note", "id": "五条裸胆违审计"}]
    assert skipped == ["ADJ-1: 未决(需你裁)"]
