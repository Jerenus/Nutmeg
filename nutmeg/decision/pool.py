"""当日样本池：传统足彩（优先）∪ 竞彩。

Jun 2026-09-27：每天把当天截止的足彩期次与竞彩板面的**并集**作为分析样本池。
竞彩一侧沿用 `jczq-legs-base.json`；本模块只补足彩一侧——当天截止的期次里
**不在竞彩板上**的场次（已由对号表对到竞彩的场次走竞彩研究，不重复研究）。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path


def _channel_mapped_match_nos(zucai_dir: Path, issue: str) -> set[int]:
    for name in (f"{issue}-channel-map.json", f"{issue}-channel-map.auto.json"):
        path = zucai_dir / name
        if path.exists():
            return {int(no) for no in json.loads(path.read_text(encoding="utf-8")).values()}
    return set()


def _iso_bj(value: str) -> str:
    return f"{value.replace(' ', 'T')}:00+08:00" if len(value) == 16 else value


def zucai_pool_entries(*, day: str, data_dir: Path) -> list[dict]:
    """当天截止期次中不在竞彩板上的场次，每条带研究落点与深研 brief 所需的 leg。"""
    zucai_dir = Path(data_dir) / "zucai"
    entries: list[dict] = []
    for issue_path in sorted(zucai_dir.glob("*-issue.json")):
        doc = json.loads(issue_path.read_text(encoding="utf-8"))
        issue = str(doc.get("issue_id") or issue_path.name.split("-")[0])
        if str(doc.get("sale_deadline") or "")[:10] != day:
            continue
        store_path = zucai_dir / f"{issue}-store-ids.json"
        if not store_path.exists():
            continue
        store = json.loads(store_path.read_text(encoding="utf-8"))
        mapped = _channel_mapped_match_nos(zucai_dir, issue)
        for match in doc.get("matches") or []:
            no = int(match["match_no"])
            ids = store.get(str(no))
            if no in mapped or not ids or not ids.get("match_id") or not ids.get("fair"):
                continue
            entries.append({
                "key": f"足彩{issue}-{no:02d}",
                "issue": issue,
                "match_no": no,
                "leg": {
                    "match_id": ids["match_id"],
                    "name": f"{match.get('home_team')}-{match.get('away_team')}",
                    "competition": match.get("competition"),
                    "kickoff_bj": _iso_bj(str(match.get("kickoff_bj"))),
                    "fair": ids["fair"],
                    "hhad_line": None,
                },
                "output": zucai_dir / f"{issue}-research-m{no}.json",
                "rejected": zucai_dir / f"{issue}-research-m{no}.rejected.json",
            })
    return entries


def _day_issues(zucai_dir: Path, day: str) -> list[str]:
    out = []
    for issue_path in sorted(zucai_dir.glob("*-issue.json")):
        doc = json.loads(issue_path.read_text(encoding="utf-8"))
        issue = str(doc.get("issue_id") or issue_path.name.split("-")[0])
        if str(doc.get("sale_deadline") or "")[:10] == day and (
            zucai_dir / f"{issue}-store-ids.json"
        ).exists():
            out.append(issue)
    return out


def refresh_day(*, day: str, data_dir: Path, made_at: str,
                submit: Callable[[Path], tuple[int, str]]) -> dict:
    """并集池刷新：竞彩入库+重建 Read、足彩表态转录 Read，再把未开球场次交本体。

    足彩里已对到竞彩的场次不交本体——同一场由竞彩那条 Read 进本体，不另建一条序列。
    """
    from nutmeg.decision.jczq_reads import build_jczq_reads, intake_board
    from nutmeg.decision.kernel_submit import submit_unstarted
    from nutmeg.decision.zucai_auto_judgment import build_auto_reads

    data_dir = Path(data_dir)
    summary: dict = {"jczq": None, "zucai": {}}
    jczq_dir = data_dir / "jczq"
    day_dir = jczq_dir / "daily" / day
    legs_path = day_dir / "jczq-legs-base.json"
    if legs_path.exists():
        intake_board(day=day, jczq_dir=jczq_dir, write=True)
        reads = build_jczq_reads(day=day, jczq_dir=jczq_dir, made_at=made_at)
        legs = json.loads(legs_path.read_text(encoding="utf-8")).get("legs") or {}
        kickoffs = {leg["match_id"]: leg["kickoff_bj"] for leg in legs.values()}
        sent = submit_unstarted(reads, kickoffs=kickoffs,
                                state_path=day_dir / "kernel-submitted.json",
                                now=made_at, submit=submit)
        summary["jczq"] = {"reads": len(reads), "submitted": len(sent)}
    zucai_dir = data_dir / "zucai"
    for issue in _day_issues(zucai_dir, day):
        reads = build_auto_reads(issue=issue, data_dir=data_dir, made_at=made_at)
        store = json.loads((zucai_dir / f"{issue}-store-ids.json").read_text(encoding="utf-8"))
        issue_doc = json.loads((zucai_dir / f"{issue}-issue.json").read_text(encoding="utf-8"))
        mapped = _channel_mapped_match_nos(zucai_dir, issue)
        kickoffs = {
            store[str(m["match_no"])]["match_id"]: _iso_bj(str(m["kickoff_bj"]))
            for m in issue_doc.get("matches") or []
            if int(m["match_no"]) not in mapped
            and store.get(str(m["match_no"]), {}).get("match_id")
        }
        sent = submit_unstarted(reads, kickoffs=kickoffs,
                                state_path=zucai_dir / f"{issue}-kernel-submitted.json",
                                now=made_at, submit=submit)
        summary["zucai"][issue] = {"reads": len(reads), "submitted": len(sent)}
    return summary
