from nutmeg.decision.research_ledger import ResearchRunLedger


def _run(run_id: str, code: str, status: str) -> dict:
    return {
        "run_id": run_id,
        "idempotency_key": f"key:{run_id}",
        "day": "2026-09-19",
        "budget": 1,
        "concurrency": 1,
        "started_at": f"2026-09-19T10:0{run_id[-1]}:00+08:00",
        "finished_at": f"2026-09-19T10:0{run_id[-1]}:01+08:00",
        "matches": [{"code": code, "status": status}],
    }


def test_two_runs_append_and_daily_projection_keeps_both(tmp_path):
    ledger = ResearchRunLedger(tmp_path / "daily" / "2026-09-19")

    ledger.append(_run("run-1", "周六001", "done"))
    ledger.append(_run("run-2", "周六029", "done"))

    assert [row["run_id"] for row in ledger.runs()] == ["run-1", "run-2"]
    projection = ledger.daily_projection()
    assert projection["run_count"] == 2
    assert {row["code"] for row in projection["matches"]} == {"周六001", "周六029"}
    assert {row["run_id"] for row in projection["matches"]} == {"run-1", "run-2"}


def test_same_idempotency_key_does_not_append_twice(tmp_path):
    ledger = ResearchRunLedger(tmp_path / "daily" / "2026-09-19")
    run = _run("run-1", "周六001", "done")

    first = ledger.append(run)
    replay = ledger.append(run)

    assert replay == first
    assert len(ledger.runs()) == 1
