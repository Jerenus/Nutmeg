"""当日样本池：传统足彩（优先）∪ 竞彩。

Jun 2026-09-27：每天把当天截止的足彩期次与竞彩板面的**并集**作为分析样本池。
竞彩一侧沿用 `jczq-legs-base.json`；本模块只补足彩一侧——当天截止的期次里
**不在竞彩板上**的场次（已由对号表对到竞彩的场次走竞彩研究，不重复研究）。
"""
from __future__ import annotations

import json
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
