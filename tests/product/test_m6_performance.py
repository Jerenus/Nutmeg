import json
from datetime import timedelta

from nutmeg.ontology.repository.identity import (
    MatchRevisionRow,
    TeamAppearanceRow,
)
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.reliability.contracts import validate_performance_report
from tests.product.test_m6_api import _client, _session
from tests.reliability.test_release_policy import COMMIT, NOW


def _seed_ten_x_board(seeded_product) -> None:
    with OntologyUnitOfWork(seeded_product.kernel.engine) as uow:
        for index in range(2, 11):
            match_id = f"perf-match-{index}"
            uow.identity.insert_match(match_id)
            uow.identity.insert_match_revision(
                MatchRevisionRow(
                    match_revision_id=f"perf-match-revision-{index}",
                    match_id=match_id,
                    version=1,
                    competition_edition_id=None,
                    scheduled_at=(
                        NOW + timedelta(minutes=index)
                    ).isoformat(),
                    schedule_status="confirmed",
                    venue_id=None,
                    status="scheduled",
                    round_label=None,
                    recorded_at=(NOW - timedelta(hours=2)).isoformat(),
                    supersedes_revision_id=None,
                )
            )
            uow.identity.insert_team_appearance(
                TeamAppearanceRow(
                    f"perf-home-{index}", match_id, "team-home", "home"
                )
            )
            uow.identity.insert_team_appearance(
                TeamAppearanceRow(
                    f"perf-away-{index}", match_id, "team-away", "away"
                )
            )


def _action(index: int) -> dict[str, object]:
    return {
        "action_type": "record_adjudication",
        "idempotency_key": f"m6:performance:action:{index}",
        "payload": {
            "subject_type": "performance_probe",
            "subject_id": f"sample-{index}",
            "decision": "hold",
            "reason": "measure the guarded Action acknowledgement path",
            "evidence_rejected": [],
            "alternative": {},
        },
        "expected_versions": {},
    }


def test_fixed_performance_budgets_pass_at_ten_x_reference_volume(
    seeded_product,
) -> None:
    _seed_ten_x_board(seeded_product)
    assert seeded_product.kernel.status().match_count == 10

    warm = _client(seeded_product)
    warm.get("/api/v1/board?date=2026-08-24&as_of=2026-08-24T12:00:00Z")
    warm.get("/api/v1/matches/match-1?as_of=2026-08-24T12:00:00Z")
    warm.post("/api/v1/actions", headers=_session(warm), json=_action(-1))
    warm.get("/api/v1/events/stream?after=0&once=true")

    client = _client(seeded_product)
    headers = _session(client)
    for _index in range(20):
        assert client.get(
            "/api/v1/board?date=2026-08-24&as_of=2026-08-24T12:00:00Z"
        ).status_code == 200
        assert client.get(
            "/api/v1/matches/match-1?as_of=2026-08-24T12:00:00Z"
        ).status_code == 200

    cursor = client.get("/api/v1/events?after=0&limit=1000").json()[
        "next_cursor"
    ]
    for index in range(20):
        action = client.post(
            "/api/v1/actions", headers=headers, json=_action(index)
        )
        assert action.status_code == 200
        stream = client.get(
            f"/api/v1/events/stream?after={cursor}&once=true"
        )
        assert stream.status_code == 200
        cursor += 1
        assert f"id: {cursor}" in stream.text

    route_rows = {
        (row["method"], row["route_template"]): row
        for row in client.get(
            "/api/v1/reliability/metrics?as_of=2026-08-24T12:00:00Z"
        ).json()["routes"]
    }
    mapping = {
        "board_query_ms": ("GET", "/api/v1/board"),
        "match_query_ms": ("GET", "/api/v1/matches/{match_id}"),
        "action_ack_ms": ("POST", "/api/v1/actions"),
        "event_reconnect_ms": ("GET", "/api/v1/events/stream"),
    }
    report = {
        "schema_version": "performance-v1",
        "candidate_commit": COMMIT,
        "policy_version": "release-v1",
        "volume_multiplier": 10,
        "metrics": {
            metric: {
                "p95_ms": route_rows[route]["p95_ms"],
                "sample_count": route_rows[route]["request_count"],
            }
            for metric, route in mapping.items()
        },
    }
    assert all(row["sample_count"] == 20 for row in report["metrics"].values())
    assert validate_performance_report(report).passed is True
    print("M6_PERFORMANCE " + json.dumps(report, sort_keys=True))
