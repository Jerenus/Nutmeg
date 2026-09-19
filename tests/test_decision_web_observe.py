from fastapi.testclient import TestClient

from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import append_candidate
from nutmeg.interfaces.decision_web import create_decision_app


def _app(tmp_path, *, kernel_state=None, repo=None):
    return TestClient(
        create_decision_app(
            store=DecisionStore(tmp_path / "decision"),
            output_dir=tmp_path,
            kernel_state=kernel_state,
            observe_repo=repo,
        )
    )


class _Repo:
    def experiments(self, *, as_of):
        return [
            {
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
                "falsifier": {
                    "threshold_pp": 2.0,
                    "bound": "ci_upper",
                    "direction": "lt_means_falsified",
                },
            }
        ]

    def experiment_timeline(self, exp_id, *, as_of):
        return [
            {"kind": "registered", "at": "2026-09-18T20:00:00+08:00"},
            {
                "kind": "grade",
                "at": "2026-09-19T01:00:00+08:00",
                "ci_low_pp": -21.3,
                "ci_high_pp": 37.1,
                "n_cum": 10,
            },
        ]

    def duties_due(self, day, *, now):
        return [
            {
                "duty_id": "F2:f2-observation",
                "due_at": f"{day}T00:30:00+08:00",
                "issue": "26130",
            }
        ]

    def latest_capital_plan(self, issue):
        return None


def test_api_observe_returns_cards_duties_and_null_wind_when_absent(tmp_path):
    client = _app(tmp_path, repo=_Repo())

    response = client.get("/api/observe")

    assert response.status_code == 200
    body = response.json()
    assert body["experiments"][0]["exp_id"] == "F2"
    assert body["experiments"][0]["gap_count"] == 1
    assert body["wind"] is None
    assert body["duties_today"][0]["duty_id"].startswith("F2")


def test_api_observe_exp_and_day(tmp_path):
    client = _app(tmp_path, repo=_Repo())
    assert client.get("/api/observe/exp/F2").json()[1]["kind"] == "grade"
    append_candidate(
        tmp_path,
        "2026-09-19",
        obj_id="ticket:26129",
        version="SFC-B",
        faces={},
        notes=128,
        stake_yuan=256,
        p_all=0.0038,
        verdict="rejected",
    )
    append_candidate(
        tmp_path,
        "2026-09-19",
        obj_id="ticket:26129",
        version="SFC-C",
        parent_version="SFC-B",
        faces={},
        notes=128,
        stake_yuan=256,
        p_all=None,
        verdict="chosen",
    )

    day = client.get("/api/observe/day/2026-09-19").json()

    assert day["plan"] is None
    assert day["tree"]["edges"] == [{"source": "SFC-B", "target": "SFC-C"}]


def test_observe_api_is_read_only_and_survives_repo_errors(tmp_path):
    class Broken(_Repo):
        def experiments(self, *, as_of):
            raise RuntimeError("kernel down")

    client = _app(tmp_path, repo=Broken())

    response = client.get("/api/observe")

    assert response.status_code == 200
    assert response.json()["experiments"] == []
    assert "kernel down" in response.json()["errors"][0]
    assert client.post("/api/observe").status_code == 405
