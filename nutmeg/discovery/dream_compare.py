"""Dream 对照：实际出票 / 决策规则最优 / 世界各档最优 / 空仓（Jun 2026-09-28）。

设计：docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md §3.5。
对照料在录制时用冻结快照算好写进夜间报告（`offer_book`、`decision_rule_best`、
`band_best`），次日只拿赛果与实票记账。⛔只报告：不改票面、不改权重、不登记实验。
"""

from __future__ import annotations

import random
from statistics import mean

from nutmeg.decision.betslip import BetSlip, settle_slip
from nutmeg.decision.jczq_combos import enumerate_combos

FACE_SETS = ("3", "1", "0", "31", "30", "10")
_SELECTION_FACE = {"home": "3", "draw": "1", "away": "0", "3": "3", "1": "1", "0": "0"}
KINDS = ("actual", "decision_rule", "band", "empty")


def offer_book(snapshot) -> dict:
    """冻结快照 → {场次: {belief, prior, odds}}（面码 3/1/0，浮点）。"""
    priors = {audit.official_match_no: dict(audit.prior) for audit in snapshot.audit_offers}
    return {
        offer.official_match_no: {
            "belief": {face: float(value) for face, value in offer.probabilities},
            "prior": {
                face: float(value)
                for face, value in priors.get(offer.official_match_no, {}).items()
            },
            "odds": {face: float(value) for face, value in offer.booked_decimal_odds_by_face},
        }
        for offer in snapshot.candidate_input.offers
    }


def decision_rule_best(book: dict, *, max_legs: int = 4, max_notes: int = 4) -> dict | None:
    """与 `jczq-combos` 同一算术：胜平负 2–4 串、≤4 注，全中每元回报 >1 的组合里 P 最大者。"""
    legs = []
    for code, row in sorted(book.items()):
        belief, odds = row["belief"], row["odds"]
        options = []
        for faces in FACE_SETS:
            modal = max(faces, key=lambda face: belief[face])
            options.append(
                {
                    "market": "had",
                    "faces": faces,
                    "p": sum(belief[face] for face in faces),
                    "odds": [odds[face] for face in faces],
                    "modal_odds": odds[modal],
                }
            )
        legs.append({"code": code, "name": code, "options": options})
    if len(legs) < 2:
        return None
    for combo in enumerate_combos(legs, max_legs=max_legs, max_notes=max_notes, top=10**9):
        if combo["return_per_yuan"] > 1:
            return {
                "legs": [{"code": leg["code"], "faces": leg["faces"]} for leg in combo["legs"]],
                "p_belief": round(combo["p"], 6),
                "notes": combo["notes"],
                "modal_return_per_yuan": round(combo["return_per_yuan"], 4),
            }
    return None


def candidate_tickets(candidate) -> list[list[dict]]:
    return [
        [
            {"code": leg.official_match_no, "faces": "".join(leg.selection_codes)}
            for leg in ticket.legs
        ]
        for ticket in candidate.tickets
    ]


def score_tickets(tickets: list[list[dict]], book: dict, results: dict) -> dict:
    """一组串关票（每腿一个面集合，全中才中）→ 命中与每元回报；缺赛果且未定 → pending。"""
    notes = 0
    units = 0.0
    pending = False
    any_hit = False
    for ticket in tickets:
        ticket_notes = 1
        won = 1.0
        missed = False
        unknown = False
        for leg in ticket:
            ticket_notes *= len(leg["faces"])
            result = results.get(leg["code"])
            if not result:
                unknown = True
                continue
            if result.get("void"):
                continue
            outcome = str(result.get("outcome_90"))
            if outcome not in leg["faces"]:
                missed = True
            else:
                won *= float(book[leg["code"]]["odds"][outcome])
        notes += ticket_notes
        if missed:
            continue
        if unknown:
            pending = True
            continue
        any_hit = True
        units += won
    if pending:
        return {"status": "pending"}
    return {
        "status": "settled",
        "hit": any_hit,
        "return_per_yuan": round(units / notes, 4) if any_hit else 0.0,
    }


def _scored_row(kind: str, row_id: str | None, p_belief, score: dict) -> dict:
    row = {"kind": kind, "id": row_id, "p_belief": p_belief, **score}
    if score.get("status") == "settled":
        row["pnl_per_yuan"] = round(score["return_per_yuan"] - 1, 4)
    return row


def _slip_row(slip: BetSlip, book: dict, results: dict, frozen_ids: set[str]) -> dict:
    settlement = settle_slip(slip, results)
    in_world = all(leg.market == "had" and leg.key in book for leg in slip.legs) and tuple(
        slip.combo_sizes or ()
    ) in ((), (len(slip.legs),))
    p_belief = None
    if in_world:
        p_belief = 1.0
        for leg in slip.legs:
            faces = {_SELECTION_FACE.get(str(selection)) for selection in leg.selections}
            p_belief *= sum(book[leg.key]["belief"][face] for face in faces if face)
    row = {
        "kind": "actual",
        "id": slip.slip_id,
        "p_belief": p_belief,
        "in_world": in_world,
        "frozen_at_cutoff": slip.slip_id in frozen_ids,
        "stake_yuan": slip.stake_yuan,
    }
    if settlement.payout_yuan is None:
        return {**row, "status": "pending"}
    return {
        **row,
        "status": "settled",
        "hit": settlement.combos_won > 0,
        "pnl_yuan": settlement.pnl_yuan,
        "pnl_per_yuan": round(settlement.pnl_yuan / slip.stake_yuan, 4),
    }


def compare_day(report: dict, results: dict, slips: list[BetSlip]) -> dict:
    """一个录制日的四行记账。`slips` 只传该业务日已买（purchased）的竞彩票。"""
    book = report["offer_book"]
    frozen = {
        str(row.get("slip_id"))
        for row in (report.get("ticket_snapshot") or {}).get("betslips", [])
    }
    rows = [_slip_row(slip, book, results, frozen) for slip in slips]
    rule = report.get("decision_rule_best")
    if rule:
        rows.append(
            _scored_row(
                "decision_rule", None, rule["p_belief"],
                score_tickets([rule["legs"]], book, results),
            )
        )
    for band, best in sorted((report.get("band_best") or {}).items()):
        rows.append(
            _scored_row(
                "band", band, float(best["p_belief"]),
                score_tickets(best["tickets"], book, results),
            )
        )
    rows.append({"kind": "empty", "id": None, "status": "settled", "pnl_per_yuan": 0.0})
    status = "pending" if any(row["status"] == "pending" for row in rows) else "settled"
    return {
        "day": report["day"],
        "status": status,
        "world_id": report.get("world_id"),
        "manifest_hash": report.get("manifest_hash"),
        "rows": rows,
    }


def _actual_pnl_per_yuan(rows: list[dict]) -> float:
    actual = [r for r in rows if r["kind"] == "actual" and r["status"] == "settled"]
    stake = sum(r["stake_yuan"] for r in actual)
    return round(sum(r["pnl_yuan"] for r in actual) / stake, 4) if stake else 0.0


def _bootstrap_ci(values: list[float], *, seed: int = 20260928, draws: int = 2000) -> list[float]:
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return [round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)]


def summarize(days: list[dict], *, min_days_for_ci: int = 20) -> dict:
    """累计：各行平均 P、命中率、平均每元盈亏；实际−规则最优的日均差（n≥20 才给 CI）。"""
    kinds = {}
    for kind in KINDS:
        rows = [
            row
            for day in days
            for row in day["rows"]
            if row["kind"] == kind and row.get("status") == "settled"
        ]
        ps = [row["p_belief"] for row in rows if row.get("p_belief") is not None]
        hits = [1.0 if row.get("hit") else 0.0 for row in rows if "hit" in row]
        kinds[kind] = {
            "n": len(rows),
            "mean_p": round(mean(ps), 4) if ps else None,
            "hit_rate": round(mean(hits), 4) if hits else None,
            "mean_pnl_per_yuan": (
                round(mean(row["pnl_per_yuan"] for row in rows), 4) if rows else None
            ),
        }
    diffs = []
    for day in days:
        rule = [
            row for row in day["rows"]
            if row["kind"] == "decision_rule" and row.get("status") == "settled"
        ]
        if rule:
            diffs.append(_actual_pnl_per_yuan(day["rows"]) - rule[0]["pnl_per_yuan"])
    return {
        "n_days": len(days),
        "kinds": kinds,
        "actual_minus_rule": {
            "n": len(diffs),
            "mean": round(mean(diffs), 4) if diffs else None,
            "ci95": _bootstrap_ci(diffs) if len(diffs) >= min_days_for_ci else None,
        },
    }
