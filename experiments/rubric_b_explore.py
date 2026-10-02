"""读者 B 历史重打分的探查表（2026-10-02）：逐项 n / 成立率 / 效应面命中 − 市场价（pp）。

⚠️非前瞻：历史侧车是赛后读的，只回答"问题表可读吗、方向大致对吗"，不进严格前瞻档，
不据此改任何上限。前瞻结账走 `factor_registry.py propose`（只收 provably_prospective 行）。

用法：uv run python experiments/rubric_b_explore.py [--corpus experiments/corpus-v2.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from experiments.rubric_rows import _rows_for
    from nutmeg.decision.rubric_items import DIRECTIONAL_ITEMS, ITEMS

    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(ROOT / "experiments" / "corpus-v2.json"))
    args = parser.parse_args()
    rows = json.loads(Path(args.corpus).read_text(encoding="utf-8"))["rows"]
    with_b = [r for r in rows if (r.get("labels") or {}).get("rubric_b")]
    print(f"语料 {len(rows)} 行，带读者 B 侧车 {len(with_b)} 行（非前瞻，只看可读性与方向）")
    print("| 项 | 效应 | n(答) | 成立 | 成立时命中−市场 pp | 不成立时 pp |")
    print("|---|---|---|---|---|---|")
    for item_id in DIRECTIONAL_ITEMS:
        built = _rows_for(item_id, reader="rubric_b")(with_b)
        on = [r["face_hit"] - r["fair"] for r in built if r["factor"] == 1]
        off = [r["face_hit"] - r["fair"] for r in built if r["factor"] == 0]
        on_pp = f"{statistics.fmean(on) * 100:+.1f}" if on else "—"
        off_pp = f"{statistics.fmean(off) * 100:+.1f}" if off else "—"
        print(f"| {item_id} | {ITEMS[item_id].effect} | {len(built)} | {len(on)} "
              f"| {on_pp} | {off_pp} |")
    abstain = {}
    for r in with_b:
        items = r["labels"]["rubric_b"].get("items") or {}
        for item_id in ITEMS:
            abstain.setdefault(item_id, 0)
            if item_id not in items:
                abstain[item_id] += 1
    print()
    print("弃权率（读者 B 在历史证据层上没答的比例）：")
    for item_id, n in abstain.items():
        print(f"  {item_id}: {n / len(with_b) * 100:.0f}%" if with_b else f"  {item_id}: —")


if __name__ == "__main__":
    main()
