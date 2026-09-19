"""RSI 实验对象的纯函数层：枚举、冻结哈希、falsifier 判定、状态投影。零 IO。

宪法落点：
- frozen_hash 覆盖登记原件的**全部**判据字段（含 mechanism，用户裁定 U5）；
- Falsifier.evaluate 只读 CI 边界、n<n_min 返回 None（不判）——中途看得见数字看不见判决；
- 判读层（layer=judgment）不可重放，因此最高只能是 observation，永不 deploy（U8-⑤）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from nutmeg.ontology.actions.models import canonical_json


class Tier(StrEnum):
    CANDIDATE = "candidate"
    OBSERVATION = "observation"
    DEPLOY_ELIGIBLE = "deploy_eligible"


class Layer(StrEnum):
    JUDGMENT = "judgment"
    STRUCTURAL = "structural"


class Population(StrEnum):
    ZUCAI = "zucai"
    JCZQ = "jczq"
    BOTH = "both"


class JudgmentTier(StrEnum):
    PRICE_ONLY = "price_only"
    LIGHT_READ = "light_read"
    DEEP_RESEARCH = "deep_research"


class GradeMode(StrEnum):
    REPLAY = "replay"
    PROSPECTIVE = "prospective"


class Verdict(StrEnum):
    FALSIFIED = "falsified"
    SURVIVED = "survived"
    INCONCLUSIVE = "inconclusive"


class DeploymentDecision(StrEnum):
    DEPLOY = "deploy"
    HOLD = "hold"
    RETIRE = "retire"
    EXTEND = "extend"


FROZEN_FIELDS: tuple[str, ...] = (
    "claim",
    "mechanism",
    "tier",
    "layer",
    "population",
    "min_tier",
    "window",
    "falsifier",
    "stop_rule",
    "quota_slot",
    "buckets",
)


def frozen_hash(doc: dict) -> str:
    """登记原件的冻结指纹。只看 FROZEN_FIELDS，与字段顺序无关。"""
    material = {k: doc.get(k) for k in FROZEN_FIELDS}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def window_contains(window: dict, *, issue: str | None, day: str) -> bool:
    """Return whether a duty target belongs to the experiment's frozen window."""
    if issue is not None and ("issue_from" in window or "issue_to" in window):
        if window.get("issue_from") and issue < str(window["issue_from"]):
            return False
        if window.get("issue_to") and issue > str(window["issue_to"]):
            return False
    if window.get("date_from") and day < str(window["date_from"]):
        return False
    if window.get("date_to") and day > str(window["date_to"]):
        return False
    return True


def validate_tier_for_layer(tier: Tier, layer: Layer) -> None:
    if layer is Layer.JUDGMENT and tier is Tier.DEPLOY_ELIGIBLE:
        raise ValueError("judgment 层实验不可重放，最高只能是 observation，不得 deploy_eligible")


@dataclass(frozen=True, slots=True)
class Falsifier:
    metric: str
    stratum: str
    n_min: int
    bound: str  # "ci_upper" | "ci_lower"
    threshold_pp: float
    direction: str  # "lt_means_falsified" | "gt_means_falsified"

    @classmethod
    def from_dict(cls, d: dict) -> Falsifier:
        if d["bound"] not in ("ci_upper", "ci_lower"):
            raise ValueError(f"bound 必须是 ci_upper/ci_lower，得到 {d['bound']!r}")
        if d["direction"] not in ("lt_means_falsified", "gt_means_falsified"):
            raise ValueError(f"direction 非法: {d['direction']!r}")
        return cls(
            metric=str(d["metric"]),
            stratum=str(d["stratum"]),
            n_min=int(d["n_min"]),
            bound=str(d["bound"]),
            threshold_pp=float(d["threshold_pp"]),
            direction=str(d["direction"]),
        )

    def evaluate(self, *, n_cum: int, ci_low: float, ci_high: float) -> Verdict | None:
        """n<n_min → None（不判）。判据只读 CI 边界，从不读点估计。"""
        if n_cum < self.n_min:
            return None
        t = self.threshold_pp
        if self.direction == "lt_means_falsified":
            # 「上界 < t」证伪；「下界 ≥ t」成立；否则跨线
            if ci_high < t:
                return Verdict.FALSIFIED
            if ci_low >= t:
                return Verdict.SURVIVED
            return Verdict.INCONCLUSIVE
        if ci_low > t:
            return Verdict.FALSIFIED
        if ci_high <= t:
            return Verdict.SURVIVED
        return Verdict.INCONCLUSIVE

    def distance_pp(self, *, ci_low: float, ci_high: float) -> float:
        """距触发 falsifier 还差多少 pp（正数=还没到）。"""
        if self.direction == "lt_means_falsified":
            return ci_high - self.threshold_pp
        return self.threshold_pp - ci_low


def project_status(
    *,
    n_observations: int,
    latest_prospective_n: int,
    n_min: int,
    latest_verdict: str | None,
    latest_deployment: str | None,
) -> str:
    """状态是投影：registered → observing → graded → <verdict> → <deployment>。"""
    if latest_deployment == "deploy":
        return "deployed"
    if latest_deployment == "hold":
        return "held"
    if latest_deployment == "retire":
        return "retired"
    if latest_deployment == "extend":
        return "extended"
    if latest_verdict:
        return latest_verdict
    if latest_prospective_n >= n_min and n_min > 0:
        return "graded"
    if n_observations > 0:
        return "observing"
    return "registered"
