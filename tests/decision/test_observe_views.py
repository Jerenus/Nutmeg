import json

from nutmeg.decision.observe_views import (
    balance_for_issue,
    candidate_dag,
    day_view,
    experiment_card,
)


def test_experiment_card_derives_progress_ci_bar_and_gap_heat():
    row = {
        "exp_id": "F2",
        "status": "observing",
        "n_cum": 10,
        "n_min": 140,
        "ci": [-21.3, 37.1],
        "distance_to_falsifier_pp": 35.1,
        "gaps": ["2026-09-14"],
        "verdict": None,
        "deployment": None,
        "tier": "observation",
        "layer": "judgment",
        "population": "zucai",
        "registered_at": "2026-09-14",
        "claim": "claim",
    }
    falsifier = {
        "threshold_pp": 2.0,
        "bound": "ci_upper",
        "direction": "lt_means_falsified",
    }

    card = experiment_card(row, falsifier)

    assert card["progress"] == 10 / 140
    assert card["threshold_pp"] == 2.0
    assert card["ci"] == [-21.3, 37.1]
    assert card["gap_count"] == 1
    assert card["color"] == "observing"


def test_candidate_dag_builds_nodes_and_edges_and_drops_orphans():
    events = [
        {
            "kind": "candidate",
            "seq": 1,
            "payload": {
                "version": "tiers@abc",
                "parent_version": None,
                "verdict": "considered",
                "notes": 0,
                "stake_yuan": 0,
                "p_all": None,
            },
        },
        {
            "kind": "candidate",
            "seq": 2,
            "payload": {
                "version": "frontier#0@400",
                "parent_version": "tiers@abc",
                "verdict": "considered",
                "notes": 200,
                "stake_yuan": 400,
                "p_all": 0.12,
            },
        },
        {
            "kind": "candidate",
            "seq": 3,
            "payload": {
                "version": "chosen#0@renjiu",
                "parent_version": "frontier#0@400",
                "verdict": "chosen",
                "notes": 200,
                "stake_yuan": 400,
                "p_all": 0.12,
            },
        },
        {
            "kind": "candidate",
            "seq": 4,
            "payload": {
                "version": "SFC-C",
                "parent_version": "SFC-B",
                "verdict": "rejected",
                "notes": 1,
                "stake_yuan": 2,
                "p_all": None,
            },
        },
        {"kind": "note", "seq": 5, "text": "x"},
    ]

    dag = candidate_dag(events)

    assert [node["id"] for node in dag["nodes"]] == [
        "tiers@abc",
        "frontier#0@400",
        "chosen#0@renjiu",
        "SFC-C",
    ]
    assert dag["edges"] == [
        {"source": "tiers@abc", "target": "frontier#0@400"},
        {"source": "frontier#0@400", "target": "chosen#0@renjiu"},
    ]
    assert dag["orphan_edges_dropped"] == 1
    chosen = next(node for node in dag["nodes"] if node["id"] == "chosen#0@renjiu")
    assert chosen["verdict"] == "chosen"


def test_day_view_degrades_gracefully_without_plan_or_tree():
    view = day_view(
        events=[
            {
                "kind": "slip",
                "payload": {
                    "slip_id": "26129-RJ9",
                    "notes": 384,
                    "stake_yuan": 768,
                },
            },
            {
                "kind": "judgment",
                "obj_id": "fr-1",
                "payload": {"match": "A vs B", "market": "had"},
            },
        ],
        plan=None,
    )

    assert view["plan"] is None
    assert view["tree"]["nodes"] == []
    assert view["slips"][0]["slip_id"] == "26129-RJ9"
    assert view["judgments"] == [
        {"obj_id": "fr-1", "match": "A vs B", "market": "had"}
    ]


def test_balance_for_issue_reads_the_visible_zero_move_ledger(tmp_path):
    payload = {
        "issue": "26129",
        "n_matches": 14,
        "n_moved": 0,
        "mean_abs_shift_pp": 0.0,
        "direction_right_n": None,
        "direction_wrong_n": None,
    }
    (tmp_path / "26129-balance.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    assert balance_for_issue(tmp_path, "26129") == payload
