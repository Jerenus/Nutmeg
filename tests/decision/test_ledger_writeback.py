import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.ledger_writeback import expand_notes, summary_line, writeback_jczq_slip
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from tests.decision.test_close_settle_adapter import DATE, _kernel_with_read

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 19, 16, 0, tzinfo=BJ)


def _board(data_dir: Path, match_id: str) -> None:
    day = data_dir / "jczq" / "daily" / DATE
    day.mkdir(parents=True, exist_ok=True)
    (day / "jczq-legs-base.json").write_text(
        json.dumps({"day": DATE, "legs": {"周日001": {"match_id": match_id, "faces": "31"}}}),
        encoding="utf-8")


def _slip(selections, odds, combo=(1,), slip_id="J1", multiplier=10):
    return BetSlip(slip_id=slip_id, channel="jczq", placed_at=DATE, multiplier=multiplier,
                   combo_sizes=combo,
                   legs=[SlipLeg(key="周日001", market="had", selections=selections, odds=odds)])


def test_expand_notes_enumerates_a_multi_selection_parlay_and_refuses_mixed_combos():
    slip = _slip(("home", "draw"), (2.1, 3.3))
    notes = expand_notes(slip)
    assert [(n[0][1], n[0][2]) for n in notes] == [("home", 2.1), ("draw", 3.3)]
    mixed = BetSlip(slip_id="M", channel="jczq", placed_at=DATE, combo_sizes=(2, 3), legs=[
        SlipLeg(key=k, market="had", selections=("home",), odds=(2.0,)) for k in ("a", "b", "c")])
    assert expand_notes(mixed) == []


def test_registered_slip_books_one_kernel_ticket_per_note(tmp_path: Path):
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    data_dir = output_dir.parent
    _board(data_dir, match_id)
    result = writeback_jczq_slip(_slip(("home", "draw"), (2.1, 3.3)), data_dir=data_dir,
                                 kernel=kernel, requested_at=NOW)
    assert result["status"] == "booked" and result["booked"] == 2 and result["notes"] == 2
    assert result["stake_booked"] == 40.0          # 2 注 × ¥2 × 10 倍
    assert kernel.status().ticket_count == 2
    with OntologyUnitOfWork(kernel.engine) as uow:
        rows = uow.finance.all_tickets() if hasattr(uow.finance, "all_tickets") else None
    assert rows is None or len(rows) == 2
    assert "入账 2/2 注（¥40）" in summary_line(result)
    # 幂等：同一票再登记一次不会重复入账
    again = writeback_jczq_slip(_slip(("home", "draw"), (2.1, 3.3)), data_dir=data_dir,
                                kernel=kernel, requested_at=NOW)
    assert kernel.status().ticket_count == 2 and again["booked"] == 2


def test_notes_without_identity_or_read_or_price_are_skipped_not_invented(tmp_path: Path):
    kernel, match_id, output_dir = _kernel_with_read(tmp_path)
    data_dir = output_dir.parent
    unknown = writeback_jczq_slip(_slip(("home",), (2.1,)), data_dir=data_dir, kernel=kernel,
                                  requested_at=NOW)
    assert unknown["status"] == "skipped" and unknown["skipped"] == {"no_match_identity": 1}
    _board(data_dir, match_id)
    no_price = writeback_jczq_slip(_slip(("home",), (1.0,)), data_dir=data_dir, kernel=kernel,
                                   requested_at=NOW)
    assert no_price["skipped"] == {"no_price": 1}
    hhad = BetSlip(slip_id="H", channel="jczq", placed_at=DATE, combo_sizes=(1,), legs=[
        SlipLeg(key="周日001", market="hhad", line=-1.0, selections=("home",), odds=(2.4,))])
    no_read = writeback_jczq_slip(hhad, data_dir=data_dir, kernel=kernel, requested_at=NOW)
    assert no_read["skipped"] == {"no_committed_read": 1}     # 只提交过 had 的 Read
    assert kernel.status().ticket_count == 0
    zucai = BetSlip(slip_id="Z", channel="renjiu", placed_at=DATE, issue="26134", legs=[])
    out = writeback_jczq_slip(zucai, data_dir=data_dir, kernel=kernel)
    assert out["status"] == "not_applicable"
