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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nutmeg.decision.faces import CODE_OF
from nutmeg.decision.scoring import brier


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
    # 入选行的语料键（2026-10-05）：样本账（rsi_samples）据此登记首次入选、冻结样本。
    selected_keys: tuple[str, ...] = ()


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


# ── 前瞻结账适配器（2026-09-22 接入 F5 / F9；F3 与 F4 2026-10-04 退役，适配器随之删除）─────
# 都只读语料 v2 的行，按登记原件的 window 过滤，永不回补窗前样本（T12）。
# F5：date_from 起两泳道，gap12∈[10,20)pp 的模态面残差（stratum=pooled；另按泳道各出一档）。
# F9：date_from 起 belief≠prior 的行，市场 Brier − 判读 Brier（pp，正=判读更好）。



def _modal(fair: dict) -> str:
    return max(fair, key=fair.get)


def _rows_hash(rows: Sequence[dict]) -> str:
    raw = json.dumps(
        [(r.get("key"), r.get("actual"), r.get("fair"), r.get("belief")) for r in rows],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return inputs_hash(raw)


def _keys(rows: Sequence[dict]) -> tuple[str, ...]:
    return tuple(str(r.get("key")) for r in rows)


def _in_date_window(row: dict, window: dict) -> bool:
    day = str(row.get("date") or "")
    return bool(day) and day >= str(window.get("date_from", ""))


def _residual_grade(rows: Sequence[dict], *, stratum: str, computed_by: str,
                    as_of_policy: str) -> GradeResult:
    modal_rows = [
        {"actual": r["actual"], "fair": {"m": r["fair"][_modal(r["fair"])]}, "m": _modal(r["fair"])}
        for r in rows
    ]
    resid_rows = [
        {"actual": "m" if r["actual"] == CODE_OF[r["m"]] else "x", "fair": {"m": r["fair"]["m"]}}
        for r in modal_rows
    ]
    ci = bootstrap_residual_pp(resid_rows, face="m")
    return GradeResult(stratum=stratum, n_cum=ci.n, metric_value_pp=ci.value_pp,
                       ci_low_pp=ci.ci_low_pp, ci_high_pp=ci.ci_high_pp, cost_axis_pp=None,
                       as_of_policy=as_of_policy, inputs_hash=_rows_hash(rows),
                       computed_by=computed_by, selected_keys=_keys(rows))


def _priced(rows: Sequence[dict]) -> list[dict]:
    return [r for r in rows
            if len(r.get("fair") or {}) == 3 and r.get("actual") in CODE_OF.values()]


def grade_f5_prospective(rows: Sequence[dict], *, window: dict,
                         stratum: str = "pooled") -> GradeResult:
    """F5a 价格带：窗内、gap12∈[10,20)pp → 模态面残差。stratum=pooled|zucai|jczq。"""
    selected = []
    for r in _priced(rows):
        if not _in_date_window(r, window):
            continue
        if stratum != "pooled" and r.get("src") != stratum:
            continue
        ordered = sorted(r["fair"].values(), reverse=True)
        gap = ordered[0] - ordered[1]
        if 0.10 <= gap < 0.20:
            selected.append(r)
    return _residual_grade(selected, stratum=stratum,
                           computed_by="nutmeg.decision.rsi_grading.grade_f5_prospective",
                           as_of_policy="registry_window_date")


def grade_f9_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                         boots: int = 4000) -> GradeResult:
    """F9 判读增量：窗内 belief≠prior 的行，(市场 Brier − 判读 Brier)×100，正=判读更好。"""
    selected = [
        r for r in _priced(rows)
        if _in_date_window(r, window)
        and r.get("belief_moved")
        and len(r.get("belief") or {}) == 3
    ]
    deltas = [(brier(r["fair"], r["actual"]) - brier(r["belief"], r["actual"])) * 100
              for r in selected]
    n = len(deltas)
    if n == 0:
        return GradeResult(stratum="pooled", n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0,
                           ci_high_pp=0.0, cost_axis_pp=None, as_of_policy="registry_window_date",
                           inputs_hash=_rows_hash(selected),
                           computed_by="nutmeg.decision.rsi_grading.grade_f9_prospective",
                           selected_keys=())
    rng = random.Random(seed)
    point = statistics.fmean(deltas)
    means = sorted(statistics.fmean(rng.choice(deltas) for _ in deltas) for _ in range(boots))
    lo, hi = means[int(0.025 * boots)], means[int(0.975 * boots) - 1]
    return GradeResult(stratum="pooled", n_cum=n, metric_value_pp=point,
                       ci_low_pp=lo, ci_high_pp=hi,
                       cost_axis_pp=None, as_of_policy="registry_window_date",
                       inputs_hash=_rows_hash(selected),
                       computed_by="nutmeg.decision.rsi_grading.grade_f9_prospective",
                       selected_keys=_keys(selected))


def grade_f10_prospective(rows: Sequence[dict], *, window: dict) -> GradeResult:
    """F10 热门低估（2026-09-27 登记）：窗内两渠道、模态面市场概率 ∈[60,80)% → 模态面残差。
    事前依据：语料 v2 历史 n=378 实开 74.9% vs 市场 68.1%（单次扫描，需前瞻复现）。"""
    selected = [
        r for r in _priced(rows)
        if _in_date_window(r, window) and 0.60 <= r["fair"][_modal(r["fair"])] < 0.80
    ]
    return _residual_grade(selected, stratum="pooled",
                           computed_by="nutmeg.decision.rsi_grading.grade_f10_prospective",
                           as_of_policy="registry_window_date")


def grade_f11_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                          boots: int = 4000) -> GradeResult:
    """F11 研究的保险点名能否识别热门翻车（2026-09-27 登记）。

    窗内、模态面 ≥55% 且带研究表态的行；翻车残差 = 1{模态面没开} − (1 − 模态 fair)。
    指标 = 研究要保险（double/full）组残差均值 − 研究单选组残差均值（pp）；正=点名有识别力。
    """
    groups: dict[str, list[float]] = {"insure": [], "single": []}
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window):
            continue
        modal = _modal(r["fair"])
        if r["fair"][modal] < 0.55:
            continue
        structure = str((r.get("labels") or {}).get("stance_structure") or "")
        if structure not in ("single", "double", "full"):
            continue
        crashed = 1.0 if r["actual"] != CODE_OF[modal] else 0.0
        groups["single" if structure == "single" else "insure"].append(
            crashed - (1.0 - r["fair"][modal]))
        selected.append(r)
    n = len(selected)
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=_rows_hash(selected), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_f11_prospective")
    if not groups["insure"] or not groups["single"]:
        return GradeResult(n_cum=n, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    point = (statistics.fmean(groups["insure"]) - statistics.fmean(groups["single"])) * 100
    rng = random.Random(seed)
    diffs = sorted(
        (statistics.fmean(rng.choice(groups["insure"]) for _ in groups["insure"])
         - statistics.fmean(rng.choice(groups["single"]) for _ in groups["single"])) * 100
        for _ in range(boots)
    )
    return GradeResult(n_cum=n, metric_value_pp=point, ci_low_pp=diffs[int(0.025 * boots)],
                       ci_high_pp=diffs[int(0.975 * boots) - 1], **kwargs)


COLLAPSE_FLAGS = frozenset({"dressing_room_turmoil", "coach_debut"})


def _anchor_residual_grade(rows: Sequence[dict], *, computed_by: str) -> GradeResult:
    resid_rows = [
        {"actual": "m" if r["actual"] == CODE_OF[r["_anchor"]] else "x",
         "fair": {"m": r["fair"][r["_anchor"]]}}
        for r in rows
    ]
    ci = bootstrap_residual_pp(resid_rows, face="m")
    return GradeResult(stratum="pooled", n_cum=ci.n, metric_value_pp=ci.value_pp,
                       ci_low_pp=ci.ci_low_pp, ci_high_pp=ci.ci_high_pp, cost_axis_pp=None,
                       as_of_policy="registry_window_date", inputs_hash=_rows_hash(rows),
                       computed_by=computed_by, selected_keys=_keys(rows))


def grade_f13_prospective(rows: Sequence[dict], *, window: dict) -> GradeResult:
    """F13 崩塌叙事完整的锚方（2026-09-30 登记）。

    窗内、锚方完整度 FAIL、带崩塌叙事（更衣室/换帅无方向旗或 crash_markers）、且 belief 把锚方
    拨低 ≥1.5pp 的行；指标 = 锚方实开 − 市场锚方概率（pp）。画像③：越完整越不崩 ⇒ 期望 ≥0。
    """
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window):
            continue
        labels = r.get("labels") or {}
        anchor = labels.get("anchor_side")
        if anchor not in CODE_OF or labels.get("anchor_integrity") != "fail":
            continue
        flags = set(labels.get("nondirectional_flags") or [])
        if not (flags & COLLAPSE_FLAGS) and not labels.get("crash_markers"):
            continue
        belief = r.get("belief") or {}
        if anchor not in belief or float(belief[anchor]) > float(r["fair"][anchor]) - 0.015:
            continue
        selected.append({**r, "_anchor": anchor})
    return _anchor_residual_grade(
        selected, computed_by="nutmeg.decision.rsi_grading.grade_f13_prospective")


PROSPECTIVE_ADAPTERS = {"F5": grade_f5_prospective,
                        "F9": grade_f9_prospective, "F10": grade_f10_prospective,
                        "F11": grade_f11_prospective}
def _stance_faces(labels: dict) -> set[str]:
    structure = str(labels.get("stance_structure") or "")
    face, cover = str(labels.get("stance_face") or ""), str(labels.get("stance_cover") or "")
    if structure == "single" and face in CODE_OF.values():
        return {face}
    if structure == "double" and face in CODE_OF.values() and cover in CODE_OF.values():
        return {face, cover}
    return set()


def grade_f14_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                          boots: int = 4000) -> GradeResult:
    """F14 结构命中率（2026-09-30 登记）：深研表态面集合（single/double）
    命中 − 该集合的市场覆盖率 Σfair（pp）。09-28/29 表态面 16/16 对而拨动净负——
    结构判断是不是真的比价格准，要前瞻数。"""
    resid: list[float] = []
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window):
            continue
        faces = _stance_faces(r.get("labels") or {})
        if not faces:
            continue
        coverage = sum(float(r["fair"][k]) for k, code in CODE_OF.items() if code in faces)
        resid.append((1.0 if r["actual"] in faces else 0.0) - coverage)
        selected.append(r)
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=_rows_hash(selected), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_f14_prospective")
    if not resid:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(resid) for _ in resid) * 100 for _ in range(boots))
    return GradeResult(n_cum=len(resid), metric_value_pp=statistics.fmean(resid) * 100,
                       ci_low_pp=means[int(0.025 * boots)],
                       ci_high_pp=means[int(0.975 * boots) - 1], **kwargs)


PROSPECTIVE_ADAPTERS.update({"F13": grade_f13_prospective, "F14": grade_f14_prospective})

def grade_f16_prospective(rows: Sequence[dict], *, window: dict) -> GradeResult:
    """F16 赛程负荷（2026-10-09 登记稿 experiments/registry/_draft_F16.json）。

    窗内、挂着开球前冻结的损耗台账（`team_load.captured_at < kickoff`）、两队 14 天场数差 ≥2
    → 更密一方取胜的残差 1{更密一方胜} − fair[更密一方]。主张为负（负荷被低估）。"""
    from nutmeg.decision.bj_time import parse_bj

    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window):
            continue
        load = r.get("team_load") or {}
        captured, kickoff = parse_bj(load.get("captured_at")), parse_bj(load.get("kickoff"))
        diff = load.get("load_diff_14")
        if captured is None or kickoff is None or captured >= kickoff or diff is None:
            continue
        if abs(int(diff)) < 2:
            continue
        selected.append({**r, "_anchor": "home" if diff > 0 else "away"})
    return _anchor_residual_grade(
        selected, computed_by="nutmeg.decision.rsi_grading.grade_f16_prospective")


PROSPECTIVE_ADAPTERS["F16"] = grade_f16_prospective      # 2026-10-09 登记


def _closing_fav(row: dict) -> tuple[str, float] | None:
    sharp = (row.get("closing") or {}).get("sharp_fair") or {}
    if len(sharp) != 3:
        return None
    face = max(sharp, key=sharp.get)
    return face, float(sharp[face])


def grade_f15_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                          boots: int = 4000, threshold: float = 0.70) -> GradeResult:
    """F15 大热校准（2026-10-01 登记）：终盘最大面 ≥0.70 的竞彩场，命中 − 终盘 p（pp）。

    价格边验证 118 天 +15pp（事后分桶）；这里只数窗内前瞻样本。"""
    resid: list[float] = []
    selected: list[dict] = []
    for r in rows:
        if r.get("src") != "jczq" or not _in_date_window(r, window):
            continue
        if r.get("actual") not in CODE_OF.values():
            continue
        fav = _closing_fav(r)
        if fav is None or fav[1] < threshold:
            continue
        resid.append((1.0 if r["actual"] == CODE_OF[fav[0]] else 0.0) - fav[1])
        selected.append(r)
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=_rows_hash(selected), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_f15_prospective")
    if not resid:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(resid) for _ in resid) * 100 for _ in range(boots))
    return GradeResult(n_cum=len(resid), metric_value_pp=statistics.fmean(resid) * 100,
                       ci_low_pp=means[int(0.025 * boots)],
                       ci_high_pp=means[int(0.975 * boots) - 1], **kwargs)


def grade_g1_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                         boots: int = 4000, data_dir=None, policy: str = "jczq_fav_pairs",
                         ledger: Sequence[dict] | None = None) -> GradeResult:
    """G1 结构规则（2026-10-01 登记）：gym 回放 `jczq_fav_pairs` 的窗内平注 ROI（pp）。

    `rows`（语料）在此不用——结构实验的样本是板面日，账由 nutmeg.gym 精确结算；
    n_cum＝有票的板面日数，CI 按日 bootstrap。测试可直接喂 `ledger`。"""
    if ledger is None:
        from nutmeg.gym.board import list_days
        from nutmeg.gym.run import run_gym

        if data_dir is None:
            from nutmeg.config.settings import get_settings

            data_dir = get_settings().data_dir
        days = [d for d in list_days(data_dir) if d >= str(window.get("date_from", ""))]
        result = run_gym(data_dir=data_dir, policies=[policy], days=days, issues=[],
                         run_id=f"grade-{policy}")
        ledger = result.ledger
    settled = [r for r in ledger if r.get("policy") == policy and r.get("net") is not None]
    by_day: dict[str, list[float]] = {}
    for r in settled:
        by_day.setdefault(r["key"], [0.0, 0.0])
        by_day[r["key"]][0] += float(r["net"])
        by_day[r["key"]][1] += float(r["stake"])
    days_ = sorted(by_day)
    digest = hashlib.sha256(json.dumps([[d, *by_day[d]] for d in days_]).encode()).hexdigest()
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=digest,
                  computed_by="nutmeg.decision.rsi_grading.grade_g1_prospective")
    if not days_:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)

    def roi(sample: list[str]) -> float:
        stake = sum(by_day[d][1] for d in sample)
        return (sum(by_day[d][0] for d in sample) / stake * 100) if stake else 0.0

    rng = random.Random(seed)
    boot = sorted(roi([rng.choice(days_) for _ in days_]) for _ in range(boots))
    return GradeResult(n_cum=len(days_), metric_value_pp=roi(days_),
                       ci_low_pp=boot[int(0.025 * boots)], ci_high_pp=boot[int(0.975 * boots) - 1],
                       **kwargs)


PROSPECTIVE_ADAPTERS.update({"F15": grade_f15_prospective, "G1": grade_g1_prospective})


def _rubric_pairs(labels: dict) -> list[tuple[str, str]]:
    """两读都作答（未弃权）的项 → [(A 答案, B 答案)]；只认在用版本（治理）。"""
    from nutmeg.decision.rubric_items import SUPPORTED_VERSIONS

    if labels.get("rubric_version") not in SUPPORTED_VERSIONS:
        return []
    a = labels.get("rubric") or {}
    b = ((labels.get("rubric_b") or {}).get("items")) or {}
    pairs = []
    for item_id, ra in a.items():
        rb = b.get(item_id)
        if not isinstance(ra, dict) or not isinstance(rb, dict):
            continue
        if ra.get("answer") is None or rb.get("answer") is None:
            continue
        pairs.append((str(ra["answer"]), str(rb["answer"])))
    return pairs


def _kappa_pp(pairs: Sequence[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    agree = sum(1 for x, y in pairs if x == y) / len(pairs)
    labels = {x for pair in pairs for x in pair}
    expected = sum((sum(1 for x, _ in pairs if x == lab) / len(pairs))
                   * (sum(1 for _, y in pairs if y == lab) / len(pairs)) for lab in labels)
    return (1.0 if expected >= 1 else (agree - expected) / (1 - expected)) * 100


def grade_k1_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                         boots: int = 4000) -> GradeResult:
    """K1 两读一致性（2026-10-02 登记）：读者 A（分析员）与读者 B（系统一读者）在两读都作答的
    rubric 项上的合并 Cohen's kappa × 100；按场 bootstrap。n = 项次。"""
    per_row: list[list[tuple[str, str]]] = []
    selected: list[dict] = []
    for r in rows:
        if not _in_date_window(r, window):
            continue
        pairs = _rubric_pairs(r.get("labels") or {})
        if not pairs:
            continue
        per_row.append(pairs)
        selected.append(r)
    raw = json.dumps([(r.get("key"), (r.get("labels") or {}).get("rubric"),
                       (r.get("labels") or {}).get("rubric_b")) for r in selected],
                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=inputs_hash(raw), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_k1_prospective")
    n_items = sum(len(p) for p in per_row)
    if not per_row:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    value = _kappa_pp([pair for pairs in per_row for pair in pairs])
    rng = random.Random(seed)
    boot = sorted(_kappa_pp([pair for pairs in (rng.choice(per_row) for _ in per_row)
                             for pair in pairs]) for _ in range(boots))
    return GradeResult(n_cum=n_items, metric_value_pp=value,
                       ci_low_pp=boot[int(0.025 * boots)], ci_high_pp=boot[int(0.975 * boots) - 1],
                       **kwargs)


PROSPECTIVE_ADAPTERS.update({"K1": grade_k1_prospective})
