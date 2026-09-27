"""足彩侧的并集样本池：研究表态 → judgment-v1 → Read（Jun 2026-09-27）。

足彩 Read 原本只能由主循环手写 judgment-v1 生成，没人跑 B 泳道的期次整期不进 F9。
本模块只做**转录**，与竞彩泳道同一口径（研究 stance → tilt 算术 → belief）：

- 主循环写了 `{issue}-judgment-v1.json` 的场次：原样用主循环的（永远优先）；
- 有深研的场次：转录研究表态（足彩独有场次读 `{issue}-research-m{n}.json`，
  已对到竞彩的场次读竞彩的 `research-{code}.json`）；
- 两者都没有：市场锚定（belief = prior，confidence 1）。

⛔判断永不入脚本：这里不产生任何判断，只搬运 agent 表态与确定性算术。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from nutmeg.decision.overrides import effective_research
from nutmeg.decision.read_builder import build
from nutmeg.decision.stance import apply_tilt, validate_stance

JUDGE = "ai-pool"
_TRANSCRIBED = ("directional_flags", "nondirectional_flags", "anchor_integrity",
                "license_questions", "crash_markers", "tracking_tags", "team_tags")


def _load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _kickoff(value: str) -> datetime:
    text = value.replace(" ", "T")
    return datetime.fromisoformat(text if len(text) > 16 else f"{text}:00+08:00")


def _jczq_research_by_match_id(data_dir: Path, deadline_day: str) -> dict[str, Path]:
    """对到竞彩的场次：到截止日前后一天的竞彩腿表里按 match_id 找研究文件。"""
    out: dict[str, Path] = {}
    base = date.fromisoformat(deadline_day)
    for offset in (-1, 0, 1, 2):
        day_dir = Path(data_dir) / "jczq" / "daily" / (base + timedelta(days=offset)).isoformat()
        legs = (_load(day_dir / "jczq-legs-base.json", {}) or {}).get("legs") or {}
        for code, leg in legs.items():
            path = day_dir / f"research-{code}.json"
            if isinstance(leg, dict) and leg.get("match_id") and path.exists():
                out.setdefault(str(leg["match_id"]), path)
    return out


def _research_path(zucai_dir: Path, issue: str, no: str, mapped: dict[int, str],
                   jczq_research: dict[str, Path]) -> Path | None:
    own = zucai_dir / f"{issue}-research-m{no}.json"
    if own.exists():
        return own
    match_id = mapped.get(int(no))
    return jczq_research.get(match_id) if match_id else None


def _from_research(research: dict, prior: dict, kickoff: str) -> dict | None:
    norm, issues = validate_stance(
        research.get("stance"), confidence=research.get("confidence"),
        death_three_proofs=research.get("death_three_proofs") or {},
    )
    if any(issue.level == "ERROR" for issue in issues):
        return None
    tilt = apply_tilt(prior, norm.get("tilt"), kickoff=kickoff)
    moved = not tilt.zeroed and norm.get("tilt")
    entry = {key: research[key] for key in _TRANSCRIBED if key in research}
    entry.update({
        "action": norm["faces"],
        "prescription": norm["faces"],
        "confidence": int(research["confidence"]),
        "precedents": [p for p in research.get("precedents") or [] if isinstance(p, list)],
        "falsifier": norm["falsifier"],
        "stance": norm,
        "note": f"【并集池·研究转录】{str(research.get('summary') or '')[:300]}",
        "belief": tilt.belief if moved else dict(prior),
        "adjustment_evidence_tiers": list(tilt.tiers) if moved else [],
        "source": "research",
    })
    return entry


def auto_judgment(*, issue: str, data_dir: Path) -> dict:
    zucai_dir = Path(data_dir) / "zucai"
    issue_doc = _load(zucai_dir / f"{issue}-issue.json", {})
    store = _load(zucai_dir / f"{issue}-store-ids.json", {})
    manual = _load(zucai_dir / f"{issue}-judgment-v1.json", {}) or {}
    mapped: dict[int, str] = {}
    for name in (f"{issue}-channel-map.json", f"{issue}-channel-map.auto.json"):
        if (zucai_dir / name).exists():
            mapped = {int(no): mid for mid, no in _load(zucai_dir / name).items()}
            break
    deadline_day = str(issue_doc.get("sale_deadline") or "")[:10]
    jczq_research = _jczq_research_by_match_id(Path(data_dir), deadline_day) if deadline_day else {}
    kickoffs = {str(m["match_no"]): str(m.get("kickoff_bj") or "")
                for m in issue_doc.get("matches") or []}
    judgment: dict[str, dict] = {}
    for no, ids in store.items():
        if no in manual:
            judgment[no] = {**manual[no], "source": "main_loop"}
            continue
        prior = dict(ids["fair"])
        kickoff = _kickoff(kickoffs[no]).isoformat() if kickoffs.get(no) else None
        path = _research_path(zucai_dir, issue, no, mapped, jczq_research)
        entry = _from_research(effective_research(path), prior, kickoff) if path else None
        judgment[no] = entry or {
            "action": "310", "prescription": "310", "confidence": 1,
            "belief": prior, "adjustment_evidence_tiers": [],
            "note": "【并集池·市场锚定】无深研", "source": "market_anchor",
        }
    return judgment


def build_auto_reads(*, issue: str, data_dir: Path, made_at: str) -> list[dict]:
    """并集池足彩 Read：主循环 Read 永不覆盖；已开球场次保留旧 Read（前瞻性）。"""
    zucai_dir = Path(data_dir) / "zucai"
    store = _load(zucai_dir / f"{issue}-store-ids.json", {})
    issue_doc = _load(zucai_dir / f"{issue}-issue.json", {})
    kickoffs = {str(m["match_no"]): _kickoff(str(m["kickoff_bj"]))
                for m in issue_doc.get("matches") or [] if m.get("kickoff_bj")}
    reads_path = zucai_dir / f"{issue}-reads.json"
    existing = {read["match_id"]: read for read in _load(reads_path, []) or []}
    built_at = datetime.fromisoformat(made_at)
    judgment = auto_judgment(issue=issue, data_dir=data_dir)
    rebuild = {
        no: entry for no, entry in judgment.items()
        if not (
            store[no]["match_id"] in existing
            and (existing[store[no]["match_id"]].get("judge") != JUDGE
                 or kickoffs.get(no, built_at) <= built_at)
        )
    }
    revision = int("".join(ch for ch in made_at if ch.isdigit())[8:12] or 0)
    fresh = build(
        rebuild, issue=issue, store_ids=store,
        fair={no: store[no]["fair"] for no in rebuild}, made_at=made_at,
        judge=JUDGE, revision=revision,
    ).reads if rebuild else []
    by_match = dict(existing)
    for read in fresh:
        read["judgment_tier"] = judgment[
            next(no for no in rebuild if store[no]["match_id"] == read["match_id"])
        ]["source"]
        by_match[read["match_id"]] = read
    order = [store[no]["match_id"] for no in sorted(store, key=int)]
    reads = [by_match[mid] for mid in order if mid in by_match]
    reads_path.write_text(json.dumps(reads, ensure_ascii=False, indent=1), encoding="utf-8")
    return reads
