"""结账算数与重放。只算数：判决在 RsiActions.record_verdict（代码按冻结判据），上线在人。

- bootstrap_residual_pp：每行等权、bootstrap 95%CI；单场无权翻转判决（U6）。
- grade_f2_prospective：F2 的前瞻结账——读 F2 ledger 与当期 issue.json，任何一期的
  captured_at 晚于该期最早开球 → LeakError **拒收并点名期号**，不是静默丢弃（U8-④）。
- dream：在冻结语料上重放一族变体，出排序表并记 variants_tried（U8-⑥）。
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class LeakError(ValueError):
    """样本来自开球之后——拒收。"""


@dataclass(frozen=True, slots=True)
class ResidualCI:
    n: int
    value_pp: float
    ci_low_pp: float
    ci_high_pp: float


@dataclass(frozen=True, slots=True)
class GradeResult:
    stratum: str
    n_cum: int
    metric_value_pp: float
    ci_low_pp: float
    ci_high_pp: float
    cost_axis_pp: float | None
    as_of_policy: str
    inputs_hash: str
    computed_by: str


def inputs_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bootstrap_residual_pp(rows: Sequence[dict], *, face: str, seed: int = 7,
                          boots: int = 4000) -> ResidualCI:
    """(实开率 − 平均 fair) × 100，每行等权；CI 为 bootstrap 2.5/97.5 分位。"""
    n = len(rows)
    if n == 0:
        return ResidualCI(0, 0.0, 0.0, 0.0)
    resid = [(1.0 if r["actual"] == face else 0.0) - float(r["fair"][face]) for r in rows]
    point = statistics.fmean(resid) * 100
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(resid) for _ in resid) * 100 for _ in range(boots))
    return ResidualCI(n, point, means[int(0.025 * boots)], means[int(0.975 * boots) - 1])


def _earliest_kickoff(zucai_dir: Path, issue: str) -> datetime | None:
    """该期最早开球（naive 北京时间，与 ledger 的 captured_at 同口径比较）。"""
    p = Path(zucai_dir) / f"{issue}-issue.json"
    if not p.exists():
        return None
    kos = [datetime.fromisoformat(m["kickoff_bj"])
           for m in json.loads(p.read_text("utf-8"))["matches"] if m.get("kickoff_bj")]
    return min(kos) if kos else None


def grade_f2_prospective(*, ledger_path: Path, zucai_dir: Path, primary_bucket: str,
                         computed_by: str = "nutmeg.decision.rsi_grading.grade_f2_prospective",
                         ) -> GradeResult:
    raw = Path(ledger_path).read_bytes()
    ledger = json.loads(raw)
    rows: list[dict] = []
    for issue, entry in ledger.get("issues", {}).items():
        if not entry.get("prospective", True):
            continue
        ko = _earliest_kickoff(zucai_dir, issue)
        captured = datetime.fromisoformat(entry["captured_at"])
        if ko is not None and captured >= ko:
            raise LeakError(f"期 {issue} 的观察单采于 {captured.isoformat()}，"
                            f"不早于最早开球 {ko.isoformat()}——拒收（不是丢弃）")
        rows.extend(r for r in entry["rows"] if r.get("bucket") == primary_bucket)
    ci = bootstrap_residual_pp(rows, face="home")
    return GradeResult(stratum="zucai", n_cum=ci.n, metric_value_pp=ci.value_pp,
                       ci_low_pp=ci.ci_low_pp, ci_high_pp=ci.ci_high_pp, cost_axis_pp=None,
                       as_of_policy="earliest_kickoff", inputs_hash=inputs_hash(raw),
                       computed_by=computed_by)


Harness = Callable[[Sequence[dict], dict], ResidualCI]


def dream(corpus: Sequence[dict], harness: Harness, *, variants: Sequence[dict]) -> dict:
    """在冻结语料上重放一族变体。只排序、只记数；不产生任何判决。"""
    ranked = []
    for v in variants:
        ci = harness(corpus, v)
        ranked.append({"variant": v, "n": ci.n, "value_pp": ci.value_pp,
                       "ci_low_pp": ci.ci_low_pp, "ci_high_pp": ci.ci_high_pp})
    ranked.sort(key=lambda r: (-r["value_pp"], -r["n"]))
    return {"variants_tried": len(variants), "ranked": ranked,
            "note": "重放结果只产候选，进不了判决（verdict 只读 prospective 档）"}
