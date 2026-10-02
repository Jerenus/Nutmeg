"""历史重打分（2026-10-02 判断 rubric r1）：让读者 B 读已有的研究文件，写侧车。

范围：竞彩 `jczq/daily/*/research-<code>.json` + 足彩 `zucai/<issue>-research-m<N>.json`
（跳过 *.rejected*；已有侧车跳过，`--force` 重跑）。n 的真实量级 ≈ 260 份（09-19 起），
不是语料行数 1,578。跑完后 `experiments/corpus_build.py` 把 `rubric_b` 并入语料，
`factor_registry.py propose --all --log` 出逐项 n 与提案。

读者 B 读的是研究原件里分析员写下的证据层，侧车 `prospective` 按读取时刻 < 开球判定：
历史重打分一律是**非前瞻**（赛后读），只用于逐项一致性与问题表可读性，不进严格前瞻档。

用法：
    uv run python scripts/rubric_rescore.py --limit 20            # 先试 20 份
    uv run python scripts/rubric_rescore.py --lane zucai --free   # 足彩全部 + 无表对照
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def all_research_files(data_dir: Path, lane: str) -> list[Path]:
    from nutmeg.decision.rubric_reader import is_research_file

    out: list[Path] = []
    if lane in ("jczq", "all"):
        out += sorted(p for p in (data_dir / "jczq" / "daily").glob("*/research-*.json")
                      if is_research_file(p))
    if lane in ("zucai", "all"):
        out += sorted(p for p in (data_dir / "zucai").glob("*-research-m*.json")
                      if is_research_file(p))
    return out


def main() -> int:
    from nutmeg.decision.rubric_reader import read_many

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=".nutmeg-data")
    parser.add_argument("--lane", choices=("jczq", "zucai", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--free", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--log", default=None, help="追加写 JSON 行日志（断点续跑看这个）")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    paths = all_research_files(data_dir, args.lane)
    out = read_many(paths, free=args.free, force=args.force, limit=args.limit,
                    workers=args.workers)
    summary = {"lane": args.lane, "total": len(paths), "done": len(out["done"]),
               "skipped": len(out["skipped"]), "failed": out["failed"][:20]}
    print(json.dumps(summary, ensure_ascii=False))
    if args.log:
        with open(args.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0 if out["done"] or out["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
