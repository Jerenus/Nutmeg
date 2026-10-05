#!/usr/bin/env python
"""样本账创世（2026-10-05，一次性；留作样本账来源的可复核证明）。

语料在 2026-09-23 → 10-01 之间没有提交过版本，但每次结账的 `inputs_hash`（入选行的
key/actual/fair/belief 摘要）都在内核 `rsi_grades` 里。用 2026-10-05 的旧版
`corpus_build.py`（bce4e9f）加「当时已结算到哪天 / 哪期」的截断重建当时的语料，
入选集的摘要与当时记录的 `inputs_hash` **逐位相同**才算复原成功，只有复原成功的快照才把
入选行按时间顺序冻结进样本账（source=genesis，proof=结账时刻:摘要前缀）。

复原不了的快照（09-22/23、09-30 20:31）不入账，在证据文档里点名。
之后的入账走 `nutmeg rsi grade` 的正常路径（rsi_samples.grade）。

用法：python experiments/rsi_samples_genesis.py --out experiments/rsi-samples.json
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nutmeg.decision import rsi_samples  # noqa: E402
from nutmeg.decision.rsi_grading import PROSPECTIVE_ADAPTERS  # noqa: E402

OLD_CORPUS_BUILD = "bce4e9f"
# (结账时刻, 竞彩赛果封存到哪天, 足彩官方赛果到哪期, 未封存的竞彩日)
# 截断由实测反推：26132 的官方赛果 09-29 10:17 时还没进 official-results，26134 直到
# 10-01 10:42 才进；09-26 板面 24/25 场有赛果，回填按「3 天后强封」到 09-29 才封存。
STATES = (
    ("2026-09-25T10:45", "2026-09-24", "26131", ()),
    ("2026-09-26T10:45", "2026-09-25", "26131", ()),
    ("2026-09-27T10:45", "2026-09-25", "26132", ()),
    ("2026-09-28T10:45", "2026-09-27", "26132", ("2026-09-26",)),
    ("2026-09-29T10:17", "2026-09-28", "26132", ()),
    ("2026-09-30T15:18", "2026-09-29", "26132", ()),
    ("2026-10-01T10:45", "2026-09-30", "26134", ()),
)
EXPERIMENTS = ("F5", "F9", "F10", "F11")


def _old_corpus_build(root: str):
    source = subprocess.run(
        ["git", "-C", root, "show", f"{OLD_CORPUS_BUILD}:experiments/corpus_build.py"],
        check=True, capture_output=True, text=True).stdout
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    handle.write(source)
    handle.close()
    spec = importlib.util.spec_from_file_location("corpus_build_old", handle.name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    module.Z = os.path.join(root, ".nutmeg-data", "zucai")
    module.J = os.path.join(root, ".nutmeg-data", "jczq")
    module.ONTOLOGY_DB = os.path.join(root, ".nutmeg-data", "ontology", "ontology.db")
    return module


def _rows_as_of(cb, jc_max: str, zc_max: str, unsealed: tuple[str, ...]) -> list[dict]:
    original = cb._load

    def load(path, default=None):
        value = original(path, default)
        if path.endswith("jc-results.json") and isinstance(value, dict):
            return {d: x for d, x in value.items() if d <= jc_max and d not in unsealed}
        if path.endswith("official-results.json") and isinstance(value, dict):
            return {i: x for i, x in value.items() if i <= zc_max}
        return value

    cb._load = load
    try:
        rows, _ = cb.dedupe(cb.zucai_rows(), cb.jczq_rows())
        rows, _ = cb.attach_kernel(rows, cb.kernel_rows())
    finally:
        cb._load = original
    return rows


def _recorded(db: str) -> dict[str, dict[str, str]]:
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out: dict[str, dict[str, str]] = {}
        for exp, graded_at, digest in connection.execute(
            "select exp_id, graded_at, inputs_hash from rsi_grades where mode='prospective'"
        ):
            out.setdefault(exp, {}).setdefault(digest, graded_at)
        return out
    finally:
        connection.close()


def _windows(db: str) -> dict[str, dict]:
    import json

    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {exp: json.loads(window) for exp, window in connection.execute(
            "select exp_id, window_json from rsi_experiments")}
    finally:
        connection.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT, help="读哪份 .nutmeg-data（只读）")
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "rsi-samples.json"))
    args = ap.parse_args()
    db = os.path.join(args.root, ".nutmeg-data", "ontology", "ontology.db")
    recorded, windows = _recorded(db), _windows(db)
    cb = _old_corpus_build(args.root)
    ledger = rsi_samples.empty()
    for at, jc_max, zc_max, unsealed in STATES:
        rows = _rows_as_of(cb, jc_max, zc_max, unsealed)
        for exp in EXPERIMENTS:
            result = PROSPECTIVE_ADAPTERS[exp](rows, window=windows[exp])
            graded_at = recorded.get(exp, {}).get(result.inputs_hash)
            if graded_at is None:
                print(f"{at} {exp}: n={result.n_cum} 摘要对不上当时的记录，不入账")
                continue
            by_key = {r["key"]: r for r in rows}
            admitted = sum(
                rsi_samples.admit(ledger, exp, by_key[key], at=graded_at, source="genesis",
                                  proof=f"{graded_at}:{result.inputs_hash[:16]}")
                for key in result.selected_keys)
            print(f"{at} {exp}: n={result.n_cum} 复原 ✓（{graded_at}）新入账 {admitted}")
    rsi_samples.save(args.out, ledger)
    for exp, info in rsi_samples.summary(ledger).items():
        print(f"{exp}: 创世成员 {info['members']}")


if __name__ == "__main__":
    main()
