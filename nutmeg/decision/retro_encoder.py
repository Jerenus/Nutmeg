"""复盘编码器（Jun 2026-09-30）：把一天 / 一期的**事实**写进记分牌，判断栏留给人。

事实 = 每张实票的断腿、注金、派奖、净值；板面的市场 / 研究原判 / 主循环终判 Brier；
足彩的开奖串与处方命中数。写入 `scoreboard.json` 的 `tickets/<key>` 与 `balance_ledger/<key>`，
**只覆盖事实字段**，人写的 `key` / `board` / `note` 原样保留；同日重跑幂等。
出生事故：09-28 / 09-29 两天的这些数字都是主循环手算再手写进 JSON 的——记分牌是单一事实源，
事实部分不该靠人搬。
⛔不产生判断：链条、裁决、画像一律不碰。
"""

from __future__ import annotations

import json
import statistics
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, load_slips, settle_slip
from nutmeg.decision.day_paths import RESULTS_90, day_dir

FACE_OF = {"3": "home", "1": "draw", "0": "away"}
CODE_OF = {"home": "3", "draw": "1", "away": "0"}
HUMAN_FIELDS = ("key", "board", "note", "judgment", "rx")


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def results_for_board(data_dir: Path, date: str) -> dict | None:
    """板面日 D 的 90' 赛果住在 daily/<D+1>/results-90.json；退回 jc-results.json[D]。"""
    next_day = (_date.fromisoformat(date) + timedelta(days=1)).isoformat()
    doc = _read_json(day_dir(data_dir, next_day) / RESULTS_90)
    if doc:
        return doc
    jc = (_read_json(Path(data_dir) / "jczq" / "jc-results.json", {}) or {}).get(date)
    if not jc:
        return None
    out = {}
    for code, row in jc.items():
        h, a = row.get("ft_home"), row.get("ft_away")
        if h is None or a is None:
            continue
        out[code] = {"outcome_90": "3" if h > a else "1" if h == a else "0",
                     "goals_h": h, "goals_a": a}
    return out or None


def _brier(p: dict, outcome: str) -> float:
    return sum((float(p.get(f, 0.0)) - (1.0 if f == outcome else 0.0)) ** 2
               for f in ("home", "draw", "away"))


def board_brier(data_dir: Path, date: str, results: dict) -> dict:
    """reads.json（prior/终判）+ overrides.jsonl（研究原判）× 赛果 → 三行 Brier。"""
    jczq_day = Path(data_dir) / "jczq" / "daily" / date
    reads = _read_json(jczq_day / "reads.json", []) or []
    research: dict[str, dict] = {}
    for line in (jczq_day / "overrides.jsonl").read_text(encoding="utf-8").splitlines() \
            if (jczq_day / "overrides.jsonl").exists() else []:
        if line.strip():
            row = json.loads(line)
            research[row["research"].replace("research-", "").replace(".json", "")] = \
                row.get("research_belief") or {}
    per_match = []
    for read in reads:
        code = str(read.get("note") or "")[1:].split("|")[0]
        result = results.get(code)
        if not result or not read.get("prior") or not read.get("belief"):
            continue
        outcome = FACE_OF.get(str(result.get("outcome_90")))
        if outcome is None:
            continue
        prior, final = read["prior"], read["belief"]
        orig = research.get(code) or final
        per_match.append({
            "code": code, "outcome": CODE_OF[outcome], "tier": read.get("judgment_tier"),
            "market": round(_brier(prior, outcome), 4),
            "research": round(_brier(orig, outcome), 4),
            "final": round(_brier(final, outcome), 4),
            "moved": any(abs(float(prior[f]) - float(final[f])) > 1e-9
                         for f in ("home", "draw", "away")),
        })
    deep = [m for m in per_match if m["tier"] == "deep_research"]

    def mean(items, key):
        return round(statistics.fmean(m[key] for m in items), 4) if items else None

    return {
        "n_matches": len(per_match), "n_deep": len(deep),
        "n_moved_final": sum(1 for m in per_match if m["moved"]),
        "market_brier": mean(per_match, "market"), "research_brier": mean(per_match, "research"),
        "final_brier": mean(per_match, "final"),
        "deep_market_brier": mean(deep, "market"), "deep_research_brier": mean(deep, "research"),
        "deep_final_brier": mean(deep, "final"),
        "per_match": per_match,
    }


def settle_day_slips(slips: list[BetSlip], results: dict,
                     prize_per_note: float | None = None) -> list[dict]:
    rows = []
    for slip in slips:
        s = settle_slip(slip, results, prize_per_note=prize_per_note)
        dead = [line.split(" ")[1] for line in s.detail if line.startswith("✗")]
        pending = [line.split(" ")[1] for line in s.detail if line.startswith("?")]
        rows.append({
            "id": slip.slip_id, "stake": slip.stake_yuan, "payout": s.payout_yuan,
            "result": f"{s.won_legs}/{len(slip.legs)} 腿"
                      + (f"，断 {'、'.join(dead)}" if dead else "")
                      + (f"，未结 {'、'.join(pending)}" if pending else "")
                      + (f"，中 {s.combos_won}/{s.combos_total} 注" if s.payout_yuan is not None
                         else ""),
            "dead_legs": dead, "pending_legs": pending,
        })
    return rows


def _merge(section: dict, key: str, facts: dict) -> dict:
    existing = section.get(key) or {}
    kept = {k: v for k, v in existing.items() if k in HUMAN_FIELDS}
    section[key] = {**existing, **facts, **kept}
    return section[key]


def encode_jczq_day(data_dir: Path, date: str, *, scoreboard_path: Path | None = None,
                    now: str | None = None) -> dict | None:
    """板面日 date 的实票与判断记分 → scoreboard；无赛果 → None（不伪造）。"""
    data_dir = Path(data_dir)
    results = results_for_board(data_dir, date)
    if not results:
        return None
    path = scoreboard_path or data_dir / "scoreboard.json"
    sb = _read_json(path, {}) or {}
    slips = [s for s in load_slips(data_dir, channel="jczq")
             if s.purchased and str(s.placed_at)[:10] == date]
    rows = settle_day_slips(slips, results)
    settled = [r for r in rows if r["payout"] is not None]
    facts = {
        "draw": " ".join(str(results[c]["outcome_90"]) for c in sorted(results)),
        "slips": rows, "stake": sum(r["stake"] for r in rows),
        "payout": round(sum(r["payout"] for r in settled), 2),
        "net": round(sum(r["payout"] for r in settled) - sum(r["stake"] for r in settled), 2),
        "encoded_at": now or "",
    }
    _merge(sb.setdefault("tickets", {}), f"jczq-{date}", facts)
    brier = board_brier(data_dir, date, results)
    _merge(sb.setdefault("balance_ledger", {}), f"jczq-{date}",
           {k: v for k, v in brier.items() if k != "per_match"} | {"encoded_at": now or ""})
    sb["updated_at"] = now or sb.get("updated_at")
    path.write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"date": date, "slips": len(rows), "stake": facts["stake"], "net": facts["net"],
            "n_matches": brier["n_matches"], "market_brier": brier["market_brier"],
            "final_brier": brier["final_brier"]}


def encode_zucai_issue(data_dir: Path, issue: str, *, prize_per_note: float | None = None,
                       scoreboard_path: Path | None = None, now: str | None = None) -> dict | None:
    """期 issue 的开奖串、处方命中、实票结果 → scoreboard；无官方开奖串 → None。"""
    data_dir = Path(data_dir)
    draw = (_read_json(data_dir / "zucai" / "official-results.json", {}) or {}).get(str(issue))
    if not draw:
        return None
    outcomes = str(draw).split()
    results = {str(i + 1): {"outcome_90": o, "goals_h": None, "goals_a": None}
               for i, o in enumerate(outcomes)}
    judgment = _read_json(data_dir / "zucai" / f"{issue}-judgment-v1.json", {}) or {}
    hits = [str(judgment[no]["action"]) for no in sorted(judgment, key=int)
            if isinstance(judgment.get(no), dict) and judgment[no].get("action")
            and outcomes[int(no) - 1] in str(judgment[no]["action"])]
    prescribed = [no for no in judgment if isinstance(judgment.get(no), dict)
                  and judgment[no].get("action")]
    slips = [s for s in load_slips(data_dir, issue=str(issue)) if s.purchased]
    rows = settle_day_slips(slips, results, prize_per_note=prize_per_note)
    settled = [r for r in rows if r["payout"] is not None]
    path = scoreboard_path or data_dir / "scoreboard.json"
    sb = _read_json(path, {}) or {}
    facts = {
        "draw": str(draw),
        "prescription": f"{len(hits)}/{len(prescribed)}" if prescribed else None,
        "slips": rows, "stake": sum(r["stake"] for r in rows),
        "payout": round(sum(r["payout"] for r in settled), 2) if settled else None,
        "net": (round(sum(r["payout"] for r in settled) - sum(r["stake"] for r in settled), 2)
                if settled else None),
        "prize_per_note": prize_per_note, "encoded_at": now or "",
    }
    _merge(sb.setdefault("tickets", {}), str(issue), facts)
    sb["updated_at"] = now or sb.get("updated_at")
    path.write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"issue": str(issue), "slips": len(rows), "prescription": facts["prescription"],
            "net": facts["net"]}
