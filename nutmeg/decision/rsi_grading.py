"""结账算数与重放。只算数：判决在 RsiActions.record_verdict（代码按冻结判据），上线在人。

- bootstrap_residual_pp：每行等权、bootstrap 95%CI；单场无权翻转判决（U6）。
- 自助法一律先排序再抽（`_boot_mean_ci` / `_boot_diff_ci`，2026-10-19）：样本账重载会改行序，
  此前同一批样本每天一个 CI（F14 10-14/10-15 同 n=120 两个下界），判决可以只由行序翻转。
- 依赖判断的实验只收 `provably_prospective is True` 的行（`_proven`，2026-10-19）。
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from nutmeg.decision.faces import CODE_OF
from nutmeg.decision.scoring import brier


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


def _boot_mean_ci(values: Sequence[float], *, seed: int = 7,
                  boots: int = 4000) -> tuple[float, float, float]:
    """(均值, 2.5 分位, 97.5 分位)，单位同 values。先排序：结果只取决于样本集合，不取决于行序。"""
    xs = sorted(values)
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(xs) for _ in xs) for _ in range(boots))
    return statistics.fmean(xs), means[int(0.025 * boots)], means[int(0.975 * boots) - 1]


def _boot_diff_ci(a: Sequence[float], b: Sequence[float], *, seed: int = 7,
                  boots: int = 4000) -> tuple[float, float, float]:
    """两组均值差 (a − b) 的点估计与 bootstrap 95%CI（两组各自重抽；先排序）。"""
    xa, xb = sorted(a), sorted(b)
    rng = random.Random(seed)
    diffs = sorted(statistics.fmean(rng.choice(xa) for _ in xa)
                   - statistics.fmean(rng.choice(xb) for _ in xb) for _ in range(boots))
    return (statistics.fmean(xa) - statistics.fmean(xb), diffs[int(0.025 * boots)],
            diffs[int(0.975 * boots) - 1])


def _cluster_boot_ci(groups: dict[str, Sequence[float]], *, seed: int = 7,
                     boots: int = 4000) -> tuple[float, float, float]:
    """按簇（日 / 期）整簇重抽的均值 CI（2026-10-19 起新登记实验的默认）：同一天的研究共享
    写法与赛况，逐行 iid 会把 CI 估窄（F14 的 209 个成员只来自 14 天）。"""
    clusters = [sorted(groups[k]) for k in sorted(groups)]
    flat = [v for c in clusters for v in c]
    rng = random.Random(seed)
    means = []
    for _ in range(boots):
        picked = [v for c in (rng.choice(clusters) for _ in clusters) for v in c]
        means.append(statistics.fmean(picked))
    means.sort()
    return statistics.fmean(flat), means[int(0.025 * boots)], means[int(0.975 * boots) - 1]


def bootstrap_residual_pp(rows: Sequence[dict], *, face: str, seed: int = 7,
                          boots: int = 4000) -> ResidualCI:
    """(实开率 − 平均 fair) × 100，每行等权；CI 为 bootstrap 2.5/97.5 分位。"""
    n = len(rows)
    if n == 0:
        return ResidualCI(0, 0.0, 0.0, 0.0)
    resid = [(1.0 if r["actual"] == face else 0.0) - float(r["fair"][face]) for r in rows]
    point, lo, hi = _boot_mean_ci(resid, seed=seed, boots=boots)
    return ResidualCI(n, point * 100, lo * 100, hi * 100)


# ── 前瞻结账适配器（2026-09-22 接入 F5 / F9；F3 与 F4 2026-10-04 退役，适配器随之删除）─────
# 都只读语料 v2 的行，按登记原件的 window 过滤，永不回补窗前样本（T12）。
# F5：date_from 起两泳道，gap12∈[10,20)pp 的模态面残差（stratum=pooled；另按泳道各出一档）。
# F9：date_from 起 belief≠prior 的行，市场 Brier − 判读 Brier（pp，正=判读更好）。



def _modal(fair: dict) -> str:
    return max(fair, key=fair.get)


def _rows_hash(rows: Sequence[dict]) -> str:
    raw = json.dumps(
        sorted([str(r.get("key")), r.get("actual"), r.get("fair"), r.get("belief")]
               for r in rows),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return inputs_hash(raw)


def _proven(row: dict) -> bool:
    """判断早于开球的唯一证明（研究 captured_at / legs judged_at / 内核 made_at < 开球）。
    依赖判断（belief、表态、研究标签）的实验只收它；纯市场残差实验（F10/F15/F16/F17）不需要。
    这些适配器带 `proven_only`（默认 True）——只有 training_pool 读历史分层时关掉。"""
    return row.get("provably_prospective") is True


PROOF_GATED = frozenset({"F9", "F11", "F13", "F14", "F18"})


def _keys(rows: Sequence[dict]) -> tuple[str, ...]:
    return tuple(str(r.get("key")) for r in rows)


def _in_date_window(row: dict, window: dict) -> bool:
    day = str(row.get("date") or "")
    if not day or day < str(window.get("date_from", "")):
        return False
    return not window.get("date_to") or day <= str(window["date_to"])


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
                         boots: int = 4000, proven_only: bool = True) -> GradeResult:
    """F9 判读增量：窗内 belief≠prior 的行，(市场 Brier − 判读 Brier)×100，正=判读更好。"""
    selected = [
        r for r in _priced(rows)
        if _in_date_window(r, window)
        and (_proven(r) or not proven_only)
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
    point, lo, hi = _boot_mean_ci(deltas, seed=seed, boots=boots)
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
                          boots: int = 4000, proven_only: bool = True) -> GradeResult:
    """F11 研究的保险点名能否识别热门翻车（2026-09-27 登记）。

    窗内、模态面 ≥55% 且带研究表态的行；翻车残差 = 1{模态面没开} − (1 − 模态 fair)。
    指标 = 研究要保险（double/full）组残差均值 − 研究单选组残差均值（pp）；正=点名有识别力。
    """
    groups: dict[str, list[float]] = {"insure": [], "single": []}
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window) or (proven_only and not _proven(r)):
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
    point, lo, hi = _boot_diff_ci(groups["insure"], groups["single"], seed=seed, boots=boots)
    return GradeResult(n_cum=n, metric_value_pp=point * 100, ci_low_pp=lo * 100,
                       ci_high_pp=hi * 100, **kwargs)


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


def grade_f13_prospective(rows: Sequence[dict], *, window: dict,
                          proven_only: bool = True) -> GradeResult:
    """F13 崩塌叙事完整的锚方（2026-09-30 登记）。

    窗内、锚方完整度 FAIL、带崩塌叙事（更衣室/换帅无方向旗或 crash_markers）、且 belief 把锚方
    拨低 ≥1.5pp 的行；指标 = 锚方实开 − 市场锚方概率（pp）。画像③：越完整越不崩 ⇒ 期望 ≥0。
    """
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window) or (proven_only and not _proven(r)):
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
                          boots: int = 4000, proven_only: bool = True) -> GradeResult:
    """F14 结构命中率（2026-09-30 登记）：深研表态面集合（single/double）
    命中 − 该集合的市场覆盖率 Σfair（pp）。09-28/29 表态面 16/16 对而拨动净负——
    结构判断是不是真的比价格准，要前瞻数。"""
    resid: list[float] = []
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window) or (proven_only and not _proven(r)):
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
    point, lo, hi = _boot_mean_ci(resid, seed=seed, boots=boots)
    return GradeResult(n_cum=len(resid), metric_value_pp=point * 100, ci_low_pp=lo * 100,
                       ci_high_pp=hi * 100, **kwargs)


PROSPECTIVE_ADAPTERS.update({"F13": grade_f13_prospective, "F14": grade_f14_prospective})


def _top_k_faces(fair: dict, k: int) -> set[str]:
    """市场同尺寸 top-k（并列按面名定序，结果只取决于价格）。"""
    order = sorted(fair, key=lambda face: (-float(fair[face]), face))
    return {CODE_OF[face] for face in order[:k]}


def grade_f14b_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                           boots: int = 4000, proven_only: bool = True) -> GradeResult:
    """F14b 表态 vs 市场同尺寸 top-k（2026-10-19 登记，接替 v2 证伪的 F14）。

    F14 的 survived 量到的是市场头部被低估（F10）：209 个成员里 151 个表态集合就是市场 top-k，
    机械 top-k 自己就有 +5.2pp。这里只看表态偏离市场排序的场，逐场配对
    （表态命中 − 表态覆盖）−（top-k 命中 − top-k 覆盖），按日聚类 bootstrap（pp）。"""
    by_day: dict[str, list[float]] = {}
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window) or (proven_only and not _proven(r)):
            continue
        faces = _stance_faces(r.get("labels") or {})
        if not faces:
            continue
        top = _top_k_faces(r["fair"], len(faces))
        if faces == top:
            continue                     # 与市场同序：配对差恒为 0，不带判断信息

        def residual(face_set: set[str], row: dict = r) -> float:
            cover = sum(float(row["fair"][k]) for k, code in CODE_OF.items() if code in face_set)
            return (1.0 if row["actual"] in face_set else 0.0) - cover

        by_day.setdefault(str(r.get("date")), []).append(residual(faces) - residual(top))
        selected.append(r)
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=_rows_hash(selected), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_f14b_prospective")
    if not selected:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    point, lo, hi = _cluster_boot_ci(by_day, seed=seed, boots=boots)
    return GradeResult(n_cum=len(selected), metric_value_pp=point * 100, ci_low_pp=lo * 100,
                       ci_high_pp=hi * 100, **kwargs)


PROSPECTIVE_ADAPTERS["F14b"] = grade_f14b_prospective     # 2026-10-19 登记
PROOF_GATED = PROOF_GATED | {"F14b"}


def grade_n0_prospective(rows: Sequence[dict], *, window: dict, n_perm: int = 200,
                         seed: int = 20260920, boots: int = 60) -> GradeResult:
    """N0 噪音地板（2026-10-25 登记）：主指标 F14b 的观测残差 vs 固定 seed 标签置换零分布。

    只打乱 F14b 入选行的 `actual`（价格、表态、分日聚类都不动），每次用 F14b 适配器重算点估计；
    metric = 观测 − 地板 p97.5（pp），>0 才算可区分；ci = [观测 − p97.5, 观测 − p2.5]。
    n_cum 与 selected_keys 沿用 F14b（同窗同 n_min），不另立样本账。"""
    import random

    base = grade_f14b_prospective(rows, window=window, boots=boots)
    keys = set(base.selected_keys)
    selected = [dict(r) for r in rows if r.get("key") in keys]
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy=base.as_of_policy,
                  inputs_hash=base.inputs_hash, selected_keys=base.selected_keys,
                  computed_by="nutmeg.decision.rsi_grading.grade_n0_prospective")
    if len(selected) < 2:
        return GradeResult(n_cum=len(selected), metric_value_pp=0.0, ci_low_pp=0.0,
                           ci_high_pp=0.0, **kwargs)
    rng = random.Random(seed)
    actuals = [r["actual"] for r in selected]
    floor: list[float] = []
    for _ in range(n_perm):
        rng.shuffle(actuals)
        for r, a in zip(selected, actuals, strict=True):
            r["actual"] = a
        floor.append(grade_f14b_prospective(selected, window=window, boots=boots).metric_value_pp)
    floor.sort()
    p2 = floor[int(0.025 * (len(floor) - 1))]
    p97 = floor[int(0.975 * (len(floor) - 1))]
    obs = base.metric_value_pp
    return GradeResult(n_cum=base.n_cum, metric_value_pp=obs - p97, ci_low_pp=obs - p97,
                       ci_high_pp=obs - p2, **kwargs)


PROSPECTIVE_ADAPTERS["N0"] = grade_n0_prospective         # 2026-10-25 登记（不进样本账）

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


HYPE_VOLUME_USD = 50_000.0


def grade_f17_prospective(rows: Sequence[dict], *, window: dict) -> GradeResult:
    """F17 名气热卖（2026-10-09 登记 experiments/registry/F17.json）。

    窗内、挂着开球前的 Polymarket 快照（`polymarket.fetched_at < kickoff`）、赛前成交 ≥$50k、
    市场模态面 ≥60% → 模态面残差。主张为负（名气热门被高估）；事前粗测偏向否定（+3.5pp）。"""
    from nutmeg.decision.bj_time import parse_bj

    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window):
            continue
        pm = r.get("polymarket") or {}
        fetched, kickoff = parse_bj(pm.get("fetched_at")), parse_bj(pm.get("kickoff"))
        if fetched is None or kickoff is None or fetched >= kickoff:
            continue
        if float(pm.get("volume") or 0.0) < HYPE_VOLUME_USD:
            continue
        modal = _modal(r["fair"])
        if modal == "draw" or float(r["fair"][modal]) < 0.60:
            continue
        selected.append({**r, "_anchor": modal})
    return _anchor_residual_grade(
        selected, computed_by="nutmeg.decision.rsi_grading.grade_f17_prospective")


PROSPECTIVE_ADAPTERS["F17"] = grade_f17_prospective      # 2026-10-09 登记


LICENCE_FAV_MIN = 0.57
_OPPOSITE = {"home": "away", "away": "home"}


def licence_of(labels: dict, anchor: str) -> bool | None:
    """F18 单关许可证（2026-10-14，26140 §10b）：数据可得的三条——锚方中轴齐（`q1_spine`）∧
    洞在弱方（`hole_location_side` 是锚方对面）∧ 洞的单位明确（不是 both/none）。
    三个字段缺任一 → None（既不算有证也不算无证，不计入两组）。"""
    lq = labels.get("license_questions") or {}
    side, unit = labels.get("hole_location_side"), labels.get("hole_location_unit")
    if "q1_spine" not in lq or side is None or unit is None:
        return None
    return bool(lq["q1_spine"]) and side == _OPPOSITE[anchor] and unit not in ("both", "none")


def grade_f18_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                          boots: int = 4000, proven_only: bool = True) -> GradeResult:
    """F18 单关许可证（2026-10-14 登记 experiments/registry/F18.json）。

    窗内、模态面 ≥57% 的非平热门、研究标签齐（anchor_side 与模态同侧或缺省）→ 按许可证分两组，
    指标＝有证组模态残差 − 无证组模态残差（pp）。主张为正（许可证能把热门分开）；
    26133–26140 n=42 粗看 洞在弱方 9/11 vs 锚方 15/21，CI 互含，只写「不矛盾」。
    n_cum 记有证组；selected_keys 两组都记（样本账两组都冻结）。"""
    licensed: list[dict] = []
    unlicensed: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window) or (proven_only and not _proven(r)):
            continue
        labels = r.get("labels") or {}
        if not labels:
            continue
        modal = _modal(r["fair"])
        if modal == "draw" or float(r["fair"][modal]) < LICENCE_FAV_MIN:
            continue
        anchor = labels.get("anchor_side")
        if anchor in _OPPOSITE and anchor != modal:
            continue                                  # 研究锚方与市场热门不是一边，不是本题
        lic = licence_of(labels, modal)
        if lic is None:
            continue
        (licensed if lic else unlicensed).append({**r, "_anchor": modal})

    def resid(group: Sequence[dict]) -> list[float]:
        return [(1.0 if r["actual"] == CODE_OF[r["_anchor"]] else 0.0)
                - float(r["fair"][r["_anchor"]]) for r in group]

    a, b = resid(licensed), resid(unlicensed)
    both = [*licensed, *unlicensed]
    if not a or not b:
        return GradeResult(stratum="pooled", n_cum=len(a), metric_value_pp=0.0, ci_low_pp=0.0,
                           ci_high_pp=0.0, cost_axis_pp=None, as_of_policy="registry_window_date",
                           inputs_hash=_rows_hash(both),
                           computed_by="nutmeg.decision.rsi_grading.grade_f18_prospective",
                           selected_keys=_keys(both))
    point, lo, hi = _boot_diff_ci(a, b, seed=seed, boots=boots)
    return GradeResult(stratum="pooled", n_cum=len(a), metric_value_pp=point * 100,
                       ci_low_pp=lo * 100, ci_high_pp=hi * 100,
                       cost_axis_pp=statistics.fmean(b) * 100,     # 无证组残差，读数时作对照
                       as_of_policy="registry_window_date", inputs_hash=_rows_hash(both),
                       computed_by="nutmeg.decision.rsi_grading.grade_f18_prospective",
                       selected_keys=_keys(both))


PROSPECTIVE_ADAPTERS["F18"] = grade_f18_prospective      # 2026-10-14 登记


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
    point, lo, hi = _boot_mean_ci(resid, seed=seed, boots=boots)
    return GradeResult(n_cum=len(resid), metric_value_pp=point * 100, ci_low_pp=lo * 100,
                       ci_high_pp=hi * 100, **kwargs)


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


def _rubric_triples(labels: dict) -> list[tuple[str, str, str]]:
    """两读都作答（未弃权）的项 → [(项, A 答案, B 答案)]；只认在用版本（治理）。"""
    from nutmeg.decision.rubric_items import SUPPORTED_VERSIONS

    if labels.get("rubric_version") not in SUPPORTED_VERSIONS:
        return []
    a = labels.get("rubric") or {}
    b = ((labels.get("rubric_b") or {}).get("items")) or {}
    out = []
    for item_id, ra in sorted(a.items()):
        rb = b.get(item_id)
        if not isinstance(ra, dict) or not isinstance(rb, dict):
            continue
        if ra.get("answer") is None or rb.get("answer") is None:
            continue
        out.append((str(item_id), str(ra["answer"]), str(rb["answer"])))
    return out


def _rubric_pairs(labels: dict) -> list[tuple[str, str]]:
    return [(a, b) for _item, a, b in _rubric_triples(labels)]


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
    for r in sorted(rows, key=lambda row: str(row.get("key"))):
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


K2_MIN_PAIRS_PER_ITEM = 20


def _weighted_item_kappa(per_row: Sequence[Sequence[tuple[str, str, str]]]) -> tuple[float, int]:
    """逐项 κ 按项次加权的均值（×100）与计入的项次；不足 K2_MIN_PAIRS_PER_ITEM 的项不计。"""
    by_item: dict[str, list[tuple[str, str]]] = {}
    for triples in per_row:
        for item, a, b in triples:
            by_item.setdefault(item, []).append((a, b))
    kept = {item: pairs for item, pairs in by_item.items() if len(pairs) >= K2_MIN_PAIRS_PER_ITEM}
    total = sum(len(pairs) for pairs in kept.values())
    if not total:
        return 0.0, 0
    return sum(_kappa_pp(pairs) * len(pairs) for pairs in kept.values()) / total, total


def grade_k2_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                         boots: int = 1000, proven_only: bool = True) -> GradeResult:
    """K2 逐项可读性（2026-10-19 登记，接替 K1）：K1 的合并 κ 跨词表异质的 15 项一起算，
    期望一致率被压低、κ 被抬高（合并 0.78 vs 逐项加权约 0.43）。这里逐项算 κ、按项次加权；
    只收开球前的研究与开球前读的侧车。按场 bootstrap。n = 计入的项次。"""
    per_row: list[list[tuple[str, str, str]]] = []
    selected: list[dict] = []
    for r in sorted(rows, key=lambda row: str(row.get("key"))):
        if not _in_date_window(r, window):
            continue
        labels = r.get("labels") or {}
        sidecar_ok = (labels.get("rubric_b") or {}).get("prospective") is True
        if proven_only and not (_proven(r) and sidecar_ok):
            continue
        triples = _rubric_triples(labels)
        if not triples:
            continue
        per_row.append(triples)
        selected.append(r)
    raw = json.dumps([(r.get("key"), (r.get("labels") or {}).get("rubric"),
                       (r.get("labels") or {}).get("rubric_b")) for r in selected],
                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    kwargs = dict(stratum="pooled", cost_axis_pp=None, as_of_policy="registry_window_date",
                  inputs_hash=inputs_hash(raw), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_k2_prospective")
    value, n_pairs = _weighted_item_kappa(per_row)
    if not n_pairs:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    rng = random.Random(seed)
    boot = sorted(_weighted_item_kappa([rng.choice(per_row) for _ in per_row])[0]
                  for _ in range(boots))
    return GradeResult(n_cum=n_pairs, metric_value_pp=value,
                       ci_low_pp=boot[int(0.025 * boots)], ci_high_pp=boot[int(0.975 * boots) - 1],
                       **kwargs)


PROSPECTIVE_ADAPTERS["K2"] = grade_k2_prospective         # 2026-10-19 登记


F19_DRIFT_PRICED_PP = 1.0
_FACE_OF = {code: face for face, code in CODE_OF.items()}


def f19_class(row: dict) -> tuple[str, str] | None:
    """F19 机械判据（2026-10-16 登记原文，2026-10-20 对象化）→ (价内/未价, 翻车面)。

    只收研究标「真实」且写了弱方的场；弱方＝`underdog_side`，热门＝对面。
    翻车面＝研究表态里不是热门胜的那一面（face 先、cover 次）；没有＝「—」，不计。
    位移＝国际盘弱方面＋平 开盘→停售（`intl_drift_pp`）；没有国际盘＝「?」，不计。
    未价＝研究答 priced_in=false ∧ 洞在热门 ∧ 位移 ≤ 0；其余（含位移 ≥ +1pp）价内。
    判据①「路径依据全部早于开盘」不是数据字段、无法机械判；它只会把场判成价内，
    与「未价」三条同时成立的场按未价记（研究自己答了未价）。"""
    labels = row.get("labels") or {}
    weak = labels.get("underdog_side")
    drift = row.get("intl_drift_pp")
    if labels.get("underdog_strength") != "real" or weak not in _OPPOSITE or not drift:
        return None
    fav = _OPPOSITE[weak]
    upset = [c for c in (labels.get("stance_face"), labels.get("stance_cover"))
             if c in _FACE_OF and c != CODE_OF[fav]]
    if not upset:
        return None
    moved = float(drift[weak]) + float(drift["draw"])
    unpriced = (labels.get("hole_location_priced_in") is False
                and labels.get("hole_location_side") == fav and moved <= 0)
    return ("未价" if unpriced else "价内"), upset[0]


def grade_f19_prospective(rows: Sequence[dict], *, window: dict, seed: int = 7,
                          boots: int = 4000, proven_only: bool = True) -> GradeResult:
    """F19「真实＝已定价」（2026-10-16 登记 experiments/registry/F19.json）。

    指标＝「真实·价内」组翻车面『命中 − 市场 P』残差均值（pp），市场 P＝停售前最后一版
    zgzcw 去水（legs-base 18:30 重建的 fair）；CI 下界 > 0 即证伪。n_cum 与样本账只记价内组；
    「真实·未价」组残差放 cost_axis_pp 作对照（原文：另计）。"""
    groups: dict[str, list[float]] = {"价内": [], "未价": []}
    selected: list[dict] = []
    for r in _priced(rows):
        if not _in_date_window(r, window) or (proven_only and not _proven(r)):
            continue
        cls = f19_class(r)
        if cls is None:
            continue
        group, code = cls
        face = _FACE_OF[code]
        groups[group].append((1.0 if r["actual"] == code else 0.0) - float(r["fair"][face]))
        if group == "价内":
            selected.append(r)
    resid, other = groups["价内"], groups["未价"]
    kwargs = dict(stratum="pooled", as_of_policy="registry_window_date",
                  cost_axis_pp=statistics.fmean(other) * 100 if other else None,
                  inputs_hash=_rows_hash(selected), selected_keys=_keys(selected),
                  computed_by="nutmeg.decision.rsi_grading.grade_f19_prospective")
    if not resid:
        return GradeResult(n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0, **kwargs)
    point, lo, hi = _boot_mean_ci(resid, seed=seed, boots=boots)
    return GradeResult(n_cum=len(resid), metric_value_pp=point * 100, ci_low_pp=lo * 100,
                       ci_high_pp=hi * 100, **kwargs)


PROSPECTIVE_ADAPTERS["F19"] = grade_f19_prospective      # 2026-10-16 登记，10-20 对象化
PROOF_GATED = PROOF_GATED | {"F19"}
