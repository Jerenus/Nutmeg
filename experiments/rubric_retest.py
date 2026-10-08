#!/usr/bin/env python
"""rubric 问题表的重测一致性（2026-10-06；K1 的训练养料，永不进判决）。

K1 量的是读者 A（分析员）与读者 B 的合并 kappa，10-02 之前的研究没有 A 的答案，K1 没有历史。
这里让读者 B 把已有侧车的研究**再读一遍**（B′，同一模型、同一提示、同一证据层），用 K1 的
同一个适配器（`grade_k1_prospective`，弃权项照语料口径剔除）算 B 对 B′ 的合并 kappa：
同一个读者读同一份证据都答不一致的项，问题本身写得含糊——A 对 B 也不会好（必要条件，不是充分条件）。

B′ 只写进 `analytics/rubric/retest.jsonl`（断点续跑），不碰侧车。

用法：python experiments/rubric_retest.py [--limit N] [--workers 4] [--report-only]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

from corpus_build import _rubric_answers  # noqa: E402

from nutmeg.decision.bj_time import BJ  # noqa: E402
from nutmeg.decision.rsi_grading import grade_k1_prospective  # noqa: E402
from nutmeg.decision.rubric_items import ITEMS  # noqa: E402
from nutmeg.decision.rubric_reader import (  # noqa: E402
    is_research_file,
    read_rubric,
    research_kickoff,
    sidecar_path,
)


def _targets(data_dir: Path) -> list[Path]:
    paths = sorted((data_dir / "jczq" / "daily").glob("*/research-*.json"))
    paths += sorted((data_dir / "zucai").glob("*-research-m*.json"))
    return [p for p in paths if is_research_file(p) and sidecar_path(p).exists()]


def _done(log: Path) -> dict[str, dict]:
    if not log.exists():
        return {}
    out = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["research"]] = row
    return out


def _read_one(path: Path, data_dir: Path) -> dict:
    research = json.loads(path.read_text(encoding="utf-8"))
    b2 = read_rubric(research, kickoff=research_kickoff(path, research))
    return {"research": str(path.relative_to(data_dir)), "b2": b2,
            "at": datetime.now(BJ).isoformat(timespec="seconds")}


def run(data_dir: Path, log: Path, *, limit: int | None, workers: int) -> None:
    done = _done(log)
    todo = [p for p in _targets(data_dir) if str(p.relative_to(data_dir)) not in done]
    if limit is not None:
        todo = todo[:limit]
    log.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool, log.open("a", encoding="utf-8") as f:
        futures = {pool.submit(_read_one, p, data_dir): p for p in todo}
        for fut in as_completed(futures):
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001 —— 单份失败只记一笔，不整批退出
                failed += 1
                print(f"失败 {futures[fut].name}: {exc}", file=sys.stderr)
                continue
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
    print(f"本轮 {len(todo)} 份，失败 {failed}；累计 {len(_done(log))} 份")


def report(data_dir: Path, log: Path) -> dict:
    rows, per_item = [], {i: [0, 0] for i in ITEMS}
    for rel, row in _done(log).items():
        side = json.loads(sidecar_path(data_dir / rel).read_text(encoding="utf-8"))
        b, b2 = _rubric_answers(side.get("b")), _rubric_answers(row["b2"])
        if b is None or b2 is None:
            continue
        for item_id, rb in b.items():
            if item_id in b2 and item_id in per_item:
                per_item[item_id][0] += 1
                per_item[item_id][1] += str(rb["answer"]) == str(b2[item_id]["answer"])
        # 日期只为过适配器的窗口判断（重测不按日期选样）
        rows.append({"key": rel, "date": "2026-10-06", "labels": {
            "rubric_version": (side.get("b") or {}).get("version"), "rubric": b,
            "rubric_b": {"items": b2}}})
    g = grade_k1_prospective(rows, window={"date_from": ""})
    return {"files": len(rows), "item_pairs": g.n_cum, "kappa_pp": round(g.metric_value_pp, 1),
            "ci": [round(g.ci_low_pp, 1), round(g.ci_high_pp, 1)],
            "per_item": {i: {"n": n, "agree": round(a / n, 3) if n else None}
                         for i, (n, a) in per_item.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, ".nutmeg-data"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    log = data_dir / "analytics" / "rubric" / "retest.jsonl"
    if not args.report_only:
        run(data_dir, log, limit=args.limit, workers=args.workers)
    print(json.dumps(report(data_dir, log), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
