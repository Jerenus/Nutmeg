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


def reusable_zucai_research(*, day: str, data_dir: Path, jczq_dir: Path) -> dict[str, Path]:
    """竞彩 match_id → 已落盘的足彩研究（经对号表认定为同一场比赛）。

    设计是「重叠场次走竞彩研究」，但竞彩板晚开售时足彩会先研究完这些场次
    （2026-09-28：08:03 足彩研究、11:01 开售、11:04 竞彩又把 6 场研究一遍）。
    有足彩研究的重叠场次，竞彩一侧复用它、不再调用模型。身份只认对号表，不猜。
    """
    from nutmeg.decision.zucai_prep import ensure_auto_channel_map

    zucai_dir = Path(data_dir) / "zucai"
    out: dict[str, Path] = {}
    for issue in _day_issues(zucai_dir, day):
        map_path = ensure_auto_channel_map(
            issue=issue, run_date=day, zucai_dir=zucai_dir, output_dir=Path(jczq_dir))
        if map_path is None:
            continue
        for match_id, no in json.loads(map_path.read_text(encoding="utf-8")).items():
            research = zucai_dir / f"{issue}-research-m{int(no)}.json"
            if research.exists():
                out[str(match_id)] = research
    return out


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


def _project(project, summary_row: dict, **board) -> None:
    """判断唯一事实 P0：刷新后把内核投影与文件比对一行写进摘要；比对是旁支，失败不挡刷新。"""
    if project is None:
        return
    try:
        out = project(materialize=True, **board)
        summary_row["projection"] = out["line"]
        summary_row["materialized"] = bool(out.get("materialized"))
    except Exception as exc:  # noqa: BLE001
        summary_row["projection_error"] = repr(exc)[:300]


def refresh_day(*, day: str, data_dir: Path, made_at: str,
                submit: Callable[[Path], tuple[int, str]],
                project: Callable[..., dict] | None = None) -> dict:
    """并集池刷新：竞彩入库+重建 Read、足彩表态转录 Read，再把未开球场次交本体。

    足彩里已对到竞彩的场次不交本体——同一场由竞彩那条 Read 进本体，不另建一条序列。
    `project(day=…)` / `project(issue=…)` 给出时，每块板刷新后把内核投影**落盘为 Read 文件**
    （判断唯一事实 P2：文件是镜像），并附一行内核 vs 文件比对。
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
        _project(project, summary["jczq"], day=day)
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
        _project(project, summary["zucai"][issue], issue=issue)
        try:
            # 足彩 legs-base 自动版（机器初稿依赖它；不覆盖主循环手工版），2026-10-02
            from nutmeg.decision.zucai_auto_judgment import ensure_auto_legs_base

            summary["zucai"][issue]["legs_base"] = ensure_auto_legs_base(
                issue=issue, data_dir=data_dir, made_at=made_at)["status"]
        except Exception as exc:  # noqa: BLE001 —— 旁支，失败不挡 Read 与本体提交
            summary["zucai"][issue]["legs_base"] = f"error: {exc!r}"[:160]
    try:
        # 信号面板随每次刷新重写：人工裁决看的永远是最新一版（Jun 2026-09-27）
        from nutmeg.decision.signals import write_signals

        summary["signals"] = str(write_signals(day=day, data_dir=data_dir))
    except Exception as exc:  # noqa: BLE001 —— 面板是旁支，失败不能挡住 Read 与本体提交
        summary["signals_error"] = repr(exc)
    return summary
