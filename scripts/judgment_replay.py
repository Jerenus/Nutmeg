#!/usr/bin/env python
"""判断唯一事实 P0 批量比对（2026-10-01）：把历史 reads.json 重交进生产库的**副本**，
按 board_key 投影回来，与文件逐场比对。假期没有活板，用 23 个竞彩日 + 37 期足彩的历史
替代"活板一周零分歧"门。

    uv run python scripts/judgment_replay.py [--data-dir .nutmeg-data] [--out <dir>]

只写：副本库（临时目录）、输出目录的 report.md / summary.json。生产库与生产文件只读。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_ZUCAI_ID = re.compile(r"-zucai-(\d+)-(\d+)-had")
_NOTE_CODE = re.compile(r"^\[([^|\]]+)\|")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def copy_kernel(data_dir: Path, tmp: Path):
    """生产库 → 副本（sqlite backup API，含 WAL 里未 checkpoint 的页）。"""
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel

    src = sqlite3.connect(f"file:{data_dir / 'ontology' / 'ontology.db'}?mode=ro", uri=True)
    (tmp / "ontology").mkdir(parents=True, exist_ok=True)
    dst = sqlite3.connect(tmp / "ontology" / "ontology.db")
    src.backup(dst)
    src.close()
    dst.close()
    kernel = build_ontology_kernel(AppSettings(data_dir=tmp))
    kernel.initialize()
    return kernel


def jczq_kind(read: dict, overrides: dict, code: str | None) -> str:
    judge = str(read.get("judge") or "")
    if judge.startswith("market"):
        return "market"
    if code and f"research-{code}.json" in overrides:
        return "override"
    return "research" if judge else "manual"


def prepare_jczq(day_dir: Path, day: str, out: Path) -> tuple[Path, int]:
    from nutmeg.decision.overrides import load_overrides

    reads = _read(day_dir / "reads.json", []) or []
    overrides = {r["research"]: r for r in load_overrides(day_dir)}
    shaped = []
    for read in reads:
        read = dict(read)
        m = _NOTE_CODE.match(str(read.get("note") or ""))
        code = m.group(1) if m else None
        read.setdefault("code", code)
        read.setdefault("board_key", f"jczq:{day}")
        read.setdefault("kind", jczq_kind(read, overrides, code))
        shaped.append(read)
    target = out / "jczq" / day
    target.mkdir(parents=True, exist_ok=True)
    (target / "reads.json").write_text(json.dumps(shaped, ensure_ascii=False), encoding="utf-8")
    snap = day_dir / "sporttery_markets.json"
    if snap.exists():
        shutil.copy(snap, target / "sporttery_markets.json")
    return target / "reads.json", len(shaped)


def zucai_kind(read: dict) -> str:
    source = str(read.get("judgment_tier") or "")
    if source in ("main_loop", "manual"):
        return "manual"
    if source in ("market_anchor", "market"):
        return "market"
    if source == "research":
        return "research"
    judge = str(read.get("judge") or "")
    return "manual" if judge.startswith("claude") else "research"


def prepare_zucai(zdir: Path, issue: str, out: Path) -> tuple[Path, int]:
    reads = _read(zdir / f"{issue}-reads.json", []) or []
    shaped = []
    for read in reads:
        read = dict(read)
        m = _ZUCAI_ID.search(str(read.get("read_id") or ""))
        read.setdefault("code", str(int(m.group(2))) if m else None)
        read.setdefault("board_key", f"zucai:{issue}")
        read.setdefault("kind", zucai_kind(read))
        shaped.append(read)
    target = out / "zucai" / issue
    target.mkdir(parents=True, exist_ok=True)
    (target / "reads.json").write_text(json.dumps(shaped, ensure_ascii=False), encoding="utf-8")
    return target / "reads.json", len(shaped)


_INGEST = re.compile(r"摄取 (\d+)/(\d+)")


def submit(kernel, reads_file: Path) -> dict:
    from nutmeg.decision.ontology_adapter import run_decision_read_v2

    try:
        msg = run_decision_read_v2(reads_file, reads_file.parent, kernel=kernel,
                                   idempotency_prefix="replay")
    except Exception as exc:  # noqa: BLE001 —— 一块板炸了不该挡住其它板
        return {"ok": 0, "total": 0, "error": repr(exc)[:200]}
    m = _INGEST.search(msg)
    rejected = msg.split("拒绝: ", 1)[1] if "拒绝: " in msg else ""
    return {"ok": int(m.group(1)) if m else 0, "total": int(m.group(2)) if m else 0,
            "rejected": [r.strip() for r in rejected.split(";") if r.strip()]}


def reclassify(result: dict) -> dict:
    """重放注入了 kind/board_key/code 三个键：read_id 相同且五个判断键相同 → 算一致。"""
    same = result["same_judgment_new_version"]
    identical_extra = [row for row in same if row["kernel"] == row["file"]]
    return {**result, "identical": result["identical"] + len(identical_extra),
            "same_judgment_new_version": [row for row in same if row["kernel"] != row["file"]]}


def _row(board: str, n: int, sub: dict, res: dict) -> dict:
    return {"board": board, "reads": n, **sub, "identical": res["identical"],
            "same_judgment": len(res["same_judgment_new_version"]), "mismatch": res["mismatch"],
            "only_in_file": res["only_in_file"], "only_in_kernel": res["only_in_kernel"],
            "skipped_mapped": len(res.get("skipped_mapped") or [])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / ".nutmeg-data")
    ap.add_argument("--out", type=Path,
                    default=ROOT / ".nutmeg-data" / "analytics" / "judgment-replay"
                    / datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    data_dir: Path = args.data_dir.resolve()
    tmp = Path(tempfile.mkdtemp(prefix="judgment-replay-"))
    kernel = copy_kernel(data_dir, tmp)
    from nutmeg.decision.judgment_projection import run_projection

    boards: list[dict] = []
    for day_dir in sorted((data_dir / "jczq" / "daily").iterdir()):
        if not (day_dir / "reads.json").exists():
            continue
        day = day_dir.name
        reads_file, n = prepare_jczq(day_dir, day, tmp / "replay")
        sub = submit(kernel, reads_file)
        proj = run_projection(data_dir, day=day, kernel=kernel, write=False)
        res = reclassify(proj["result"])
        boards.append(_row(f"jczq:{day}", n, sub, res))
    zdir = data_dir / "zucai"
    for path in sorted(zdir.glob("*-reads.json")):
        issue = path.name.split("-")[0]
        if not (zdir / f"{issue}-issue.json").exists():
            continue
        reads_file, n = prepare_zucai(zdir, issue, tmp / "replay")
        sub = submit(kernel, reads_file)
        proj = run_projection(data_dir, issue=issue, kernel=kernel, write=False)
        res = reclassify(proj["result"])
        boards.append(_row(f"zucai:{issue}", n, sub, res))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(boards, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    lines = ["| 板 | Read | 交库 ok/总 | 一致 | 同判断新版本 | 分歧 | 仅文件 | 仅内核 | 拒绝原因 |",
             "|---|---|---|---|---|---|---|---|---|"]
    tot = {"reads": 0, "ok": 0, "total": 0, "identical": 0, "same": 0, "mismatch": 0,
           "only_file": 0, "only_kernel": 0}
    reasons: dict[str, int] = {}
    for b in boards:
        for r in b.get("rejected") or []:
            why = r.split(":", 1)[1] if ":" in r else r
            why = re.sub(r"\d+", "#", why)[:40]
            reasons[why] = reasons.get(why, 0) + 1
        for key, value in (("reads", b["reads"]), ("ok", b["ok"]), ("total", b["total"]),
                           ("identical", b["identical"]), ("same", b["same_judgment"]),
                           ("mismatch", len(b["mismatch"])), ("only_file", len(b["only_in_file"])),
                           ("only_kernel", len(b["only_in_kernel"]))):
            tot[key] += value
        why = "; ".join(sorted({(r.split(":", 1)[1] if ":" in r else r)[:28]
                                for r in (b.get("rejected") or [])})) or b.get("error", "")
        lines.append(f"| {b['board']} | {b['reads']} | {b['ok']}/{b['total']} | {b['identical']} "
                     f"| {b['same_judgment']} | {len(b['mismatch'])} | {len(b['only_in_file'])} "
                     f"| {len(b['only_in_kernel'])} | {why} |")
    lines.append("")
    lines.append(f"**合计**：Read {tot['reads']}，交库 {tot['ok']}/{tot['total']}，"
                 f"一致 {tot['identical']}，同判断新版本 {tot['same']}，"
                 f"**分歧 {tot['mismatch']}**，仅文件 {tot['only_file']}，"
                 f"仅内核 {tot['only_kernel']}")
    ranked = sorted(reasons.items(), key=lambda kv: -kv[1])
    lines.append("拒绝原因分布：" + ", ".join(f"{k}×{v}" for k, v in ranked))
    text = "\n".join(lines) + "\n"
    (args.out / "report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"副本库 {tmp}（可删）；输出 {args.out}")


if __name__ == "__main__":
    main()
