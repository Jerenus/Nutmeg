"""判断唯一事实 P0（2026-10-01）：从内核投影一块板的 Read 列表，并与文件比对。

投影规则：`board_key` 下每个 forecast_series 取 revision_no 最高的一条，它的 `judgment_json`
就是那条 Read；竞彩按编号字典序、足彩按场号数值序排。比对以 match_id 对齐：read_id 不同
但 prior/belief/stance/judge/档 相同算「同判断新版本号」（定时重建每次换后缀），不算分歧；
这五个字段有一个不同才算分歧。一周（≥2026-10-08）分歧为零，P2 才把写路径搬进内核。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.zucai_identity import load_channel_map

REPORT = "judgment-projection.json"
# `reads.projected.json`（投影全文）2026-10-13 退役：P2 起 reads.json 本身就是内核投影落盘，
# 它与 reads.json 逐字相同、全仓无读者；比对结果只留 REPORT。
_KEYS = ("prior", "belief", "stance", "judge", "commitment_tier")


def project_board(kernel, board_key: str) -> list[dict]:
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    latest: dict[str, tuple[int, dict]] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for row in uow.decision.iter_board_revisions(board_key):
            if row.judgment is None:
                continue
            best = latest.get(row.forecast_series_id)
            if best is None or row.revision_no > best[0]:
                latest[row.forecast_series_id] = (row.revision_no, dict(row.judgment))
    reads = [judgment for _, judgment in latest.values()]
    if board_key.startswith("zucai:"):
        return sorted(reads, key=lambda r: int(str(r.get("code") or 0)))
    return sorted(reads, key=lambda r: str(r.get("code") or ""))


def compare(projected: list[dict], file_reads: list[dict], *,
            skip_match_ids: tuple[str, ...] | list[str] = ()) -> dict:
    skip = set(skip_match_ids)
    by_k = {r["match_id"]: r for r in projected
            if r.get("match_id") and r["match_id"] not in skip}
    by_f = {r["match_id"]: r for r in file_reads
            if r.get("match_id") and r["match_id"] not in skip}
    identical: list[str] = []
    same_judgment: list[dict] = []
    mismatch: list[dict] = []
    for mid in sorted(by_k.keys() & by_f.keys()):
        k, f = by_k[mid], by_f[mid]
        if k == f:
            identical.append(mid)
        elif all(k.get(key) == f.get(key) for key in _KEYS):
            same_judgment.append({"match_id": mid, "code": f.get("code") or k.get("code"),
                                  "kernel": k.get("read_id"), "file": f.get("read_id")})
        else:
            mismatch.append({
                "match_id": mid, "code": f.get("code") or k.get("code"),
                "kernel": {key: k.get(key) for key in _KEYS},
                "file": {key: f.get(key) for key in _KEYS},
            })
    return {
        "projected": len(projected), "file": len(by_f), "identical": len(identical),
        "same_judgment_new_version": same_judgment, "mismatch": mismatch,
        "only_in_kernel": sorted(by_k.keys() - by_f.keys()),
        "only_in_file": sorted(by_f.keys() - by_k.keys()),
        "skipped_mapped": sorted(skip),
    }


def summary_line(result: dict) -> str:
    return (f"投影 {result['projected']} 条｜文件 {result['file']} 条｜一致 {result['identical']}"
            f"｜同判断新版本 {len(result['same_judgment_new_version'])}"
            f"｜分歧 {len(result['mismatch'])}｜仅内核 {len(result['only_in_kernel'])}"
            f"｜仅文件 {len(result['only_in_file'])}")


def write_report(directory: Path, *, projected: list[dict], result: dict, board_key: str,
                 at: str, prefix: str = "") -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}{REPORT}"
    path.write_text(json.dumps({"board_key": board_key, "at": at, **result},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _mapped_match_ids(zucai_dir: Path, issue: str) -> list[str]:
    """已对到竞彩的足彩场次：同一场由竞彩那条 Read 进本体，足彩投影里不算缺失。

    channel-map 的键是**竞彩侧**的 match_id、值是足彩场号；足彩 Read 用的是 store-ids 里
    **足彩侧**的 match_id。2026-10-05 前这里只取键，跳过集与足彩 Read 永远对不上：已对到
    竞彩的场次被拿来和内核里早先的足彩版本比成「分歧」，P2 落盘时还用旧版本覆盖了文件。"""
    mapping = load_channel_map(zucai_dir, issue)
    if not mapping:
        return []
    store_path = zucai_dir / f"{issue}-store-ids.json"
    try:
        store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {}
    except (OSError, ValueError):
        return []
    zucai_side = {(store.get(str(no)) or {}).get("match_id") for no in mapping.values()}
    return sorted({*mapping, *(mid for mid in zucai_side if mid)})


def _kernel(data_dir: Path):
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel

    kernel = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve()))
    kernel.initialize()
    return kernel


def _code_of(read: dict) -> str:
    return str(read.get("code") or "")


def run_projection(data_dir: Path, *, day: str | None = None, issue: str | None = None,
                   kernel=None, at: str | None = None, write: bool = True,
                   materialize: bool = False) -> dict:
    """一块板的投影 + 比对（+ 落报告）。`day` 走竞彩板，`issue` 走足彩期，二选一。

    `materialize=True`（判断唯一事实 P2）：用投影**覆盖** Read 文件——内核是唯一可写的判断，
    文件只是它的镜像。投影为空（内核不可达/全部拒收）时不覆盖并标 `degraded`，不让一次
    内核故障抹掉当天的 Read。足彩已对到竞彩的场次（它们的内核真值在竞彩板）仍从文件
    原样带过去，P3 并轨时再定。"""
    data_dir = Path(data_dir)
    if bool(day) == bool(issue):
        raise ValueError("--day 与 --issue 二选一")
    if issue:
        board_key = f"zucai:{issue}"
        directory = data_dir / "zucai"
        reads_path = directory / f"{issue}-reads.json"
        prefix = f"{issue}-"
        skip = _mapped_match_ids(directory, issue)
    else:
        board_key = f"jczq:{day}"
        directory = data_dir / "jczq" / "daily" / str(day)
        reads_path = directory / "reads.json"
        prefix = ""
        skip = []
    active = kernel if kernel is not None else _kernel(data_dir)
    projected = project_board(active, board_key)
    try:
        file_reads = json.loads(reads_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        file_reads = []
    result = compare(projected, file_reads, skip_match_ids=skip)
    stamp = at or datetime.now().astimezone().isoformat(timespec="seconds")
    report = (write_report(directory, projected=projected, result=result, board_key=board_key,
                           at=stamp, prefix=prefix) if write else None)
    materialized = False
    degraded = False
    if materialize:
        if projected:
            # 已对到竞彩的场次：内核足彩板上可能还留着对上之前交的旧版，不能随投影落盘
            # （2026-10-05 修好跳过集后，26135 一度把 2–8 场写成新旧两条）
            carried = [r for r in file_reads if r.get("match_id") in set(skip)]
            final = [r for r in projected if r.get("match_id") not in set(skip)] + carried
            if issue:
                final.sort(key=lambda r: int(_code_of(r) or 0))
            reads_path.parent.mkdir(parents=True, exist_ok=True)
            reads_path.write_text(json.dumps(final, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
            materialized = True
        else:
            degraded = bool(file_reads)
    line = summary_line(result) + ("｜已落盘为投影" if materialized else "")
    if degraded:
        line += "｜⚠️投影为空，保留文件"
    return {"board_key": board_key, "projected": projected, "result": result,
            "report": report, "line": line, "materialized": materialized, "degraded": degraded}
