"""官方奖金反推人群：log 任九奖金 = a + b·S + γ·X。

S = −Σ ln p(实际赛果)（市场意外度，非作废场）；X = 触发面「实开数 − 市场期望数」。
γ>0：触发面开出时奖池多付 → 全国人群少买它；γ<0：人群多买。估计用 Frisch–Waugh 两步 OLS，
按期 bootstrap 取 CI。观测单位是期——每期只有一个奖金。
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

from nutmeg.decision.crowd_source import FACES, CrowdMatch, load_board
from nutmeg.decision.crowd_trigger import evaluate, facts, fires
from nutmeg.decision.rsi_grading import GradeResult
from nutmeg.gym.prizes import load_prizes

N_MATCHES = 14
BOOTS = 2000
BANDS = ((0, 20), (20, 35), (35, 50), (50, 65), (65, 101))
GROUPS = ("national", "top5", "other")
MIN_HITS = 8                       # 提名门：窗口内触发面至少实开 8 次
_FACE_CN = {"3": "主胜", "1": "平局", "0": "客胜"}
_GROUP_CN = {"national": "国家队", "top5": "五大联赛", "other": "其他联赛"}


@dataclass(frozen=True)
class IssueObs:
    issue: str
    s: float
    log_prize: float
    board: tuple[CrowdMatch, ...]
    results: tuple[str, ...]          # 按场号 1..14："3"/"1"/"0"/"*"


@dataclass(frozen=True)
class GammaFit:
    n: int
    gamma: float
    ci_low: float
    ci_high: float
    issues: tuple[str, ...]
    rows: tuple[tuple[float, float, float], ...]


def surprise(board, results) -> float:
    return sum(-math.log(m.p[results[m.no - 1]]) for m in board if results[m.no - 1] != "*")


def _in_window(issue: str, window: dict | None) -> bool:
    if not window:
        return True
    lo, hi = window.get("issue_from"), window.get("issue_to")
    return (not lo or issue >= str(lo)) and (not hi or issue <= str(hi))


def load_observations(zdir: Path, *, window: dict | None = None) -> list[IssueObs]:
    """官方任九有人中奖、赛果 14 场、zgzcw 板面 14 场齐全的期。"""
    out = []
    for issue, row in sorted(load_prizes(zdir).items()):
        if not _in_window(issue, window):
            continue
        prize = (row.get("renjiu") or {}).get("stake_amount")
        results = tuple(str(row.get("results") or "").split())
        loaded = load_board(zdir, issue)
        if not prize or prize <= 0 or len(results) != N_MATCHES or loaded is None:
            continue
        board = tuple(loaded[1])
        if len(board) != N_MATCHES:
            continue
        out.append(IssueObs(issue, surprise(board, results), math.log(prize), board, results))
    return out


def excess(trigger: dict, obs: IssueObs) -> float:
    board = list(obs.board)
    total = 0.0
    for m in board:
        actual = obs.results[m.no - 1]
        if actual == "*":
            continue
        hit = {face: evaluate(trigger, facts(m, face, board)) for face in FACES}
        total += (1.0 if hit[actual] else 0.0) - sum(m.p[f] for f in FACES if hit[f])
    return total


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    return my - b * mx, b


def _gamma(rows) -> float:
    s = [r[0] for r in rows]
    y = [r[1] for r in rows]
    x = [r[2] for r in rows]
    ay, by = _ols(s, y)
    ax, bx = _ols(s, x)
    ry = [yi - (ay + by * si) for yi, si in zip(y, s, strict=True)]
    rx = [xi - (ax + bx * si) for xi, si in zip(x, s, strict=True)]
    return _ols(rx, ry)[1]


def fit_gamma(observations: list[IssueObs], trigger: dict, *, seed: int = 7,
              boots: int = BOOTS) -> GammaFit:
    rows = tuple((o.s, o.log_prize, excess(trigger, o)) for o in observations)
    issues = tuple(o.issue for o in observations)
    if len(rows) < 3:
        return GammaFit(len(rows), 0.0, 0.0, 0.0, issues, rows)
    rng = random.Random(seed)
    draws = sorted(_gamma([rng.choice(rows) for _ in rows]) for _ in range(boots))
    return GammaFit(len(rows), _gamma(rows), draws[int(0.025 * boots)],
                    draws[int(0.975 * boots) - 1], issues, rows)


def grade_crowd(doc: dict, zdir: Path, *, mode: str, seed: int = 7,
                boots: int = BOOTS) -> GradeResult:
    """metric = sign·γ·100（每多开一个触发面奖金变化 %）；正数 = 假说方向成立。"""
    window = doc.get("replay_window") if mode == "replay" else doc["window"]
    # 没有窗口就没有样本——绝不退化成「全部期次」（那会把提名块混进验证）。
    observations = load_observations(zdir, window=window) if window else []
    fit = fit_gamma(observations, doc["trigger"], seed=seed, boots=boots)
    sign = 1.0 if doc["crowd_bias"] == "under" else -1.0
    lo, hi = sorted((sign * fit.ci_low * 100, sign * fit.ci_high * 100))
    raw = json.dumps({"exp": doc["exp_id"], "mode": mode, "issues": fit.issues,
                      "rows": fit.rows}, separators=(",", ":")).encode()
    return GradeResult(
        stratum="zucai", n_cum=fit.n, metric_value_pp=round(sign * fit.gamma * 100, 3) + 0.0,
        ci_low_pp=round(lo, 3) + 0.0, ci_high_pp=round(hi, 3) + 0.0, cost_axis_pp=None,
        as_of_policy="per_issue_official_renjiu_prize",
        inputs_hash=hashlib.sha256(raw).hexdigest(),
        computed_by="nutmeg.decision.crowd_model.grade_crowd", selected_keys=fit.issues)


def bucket_triggers() -> list[tuple[str, dict]]:
    """提名文法：3 个纯面桶 + 面 × 市场档 × 联赛组 45 桶 = 48。"""
    out = []
    for face in FACES:
        is_face = {"field": "face", "op": "==", "v": face}
        out.append((_FACE_CN[face], is_face))
        for lo, hi in BANDS:
            for group in GROUPS:
                out.append((f"{_GROUP_CN[group]}·{_FACE_CN[face]}·市场 {lo}–{min(hi, 100)}%",
                            {"all": [is_face,
                                     {"field": "p_face", "op": ">=", "v": lo},
                                     {"field": "p_face", "op": "<=", "v": hi - 0.01},
                                     {"field": "league_group", "op": "==", "v": group}]}))
    return out


def _fire_set(trigger: dict, observations: list[IssueObs]) -> set[tuple[str, int, str]]:
    return {(o.issue, no, face) for o in observations for no, face in fires(trigger, list(o.board))}


def _hits(trigger: dict, observations: list[IssueObs]) -> int:
    """窗口内触发面实际开出的次数。"""
    return sum(1 for o in observations for no, face in fires(trigger, list(o.board))
               if o.results[no - 1] == face)


def nominate(observations: list[IssueObs], *, existing: dict[str, dict], top: int = 3,
             seed: int = 7, boots: int = BOOTS) -> list[dict]:
    """扫 48 桶 → 按证据强度 z = |γ|/标准误 取前 top。

    门：CI 不含 0、实开 ≥ MIN_HITS；与已登记假说或已选候选触发集合重叠 ≥50% 的不提。
    不按 |γ| 排——2026-10-07 首轮实测：|γ| 前三全是稀有桶（1 次实开、CI 宽到 200%），
    在未看过的块上翻号；按 z 排第一的平局桶在未看过的块上复现。
    """
    taken = [s for s in (_fire_set(t, observations) for t in existing.values()) if s]
    buckets = bucket_triggers()
    found = []
    for label, trigger in buckets:
        fset = _fire_set(trigger, observations)
        if not fset or any(len(fset & s) >= 0.5 * len(fset) for s in taken):
            continue
        hits = _hits(trigger, observations)
        if hits < MIN_HITS:
            continue
        fit = fit_gamma(observations, trigger, seed=seed, boots=boots)
        if fit.n < 3 or fit.ci_low <= 0 <= fit.ci_high:
            continue
        z = abs(fit.gamma) / max(1e-9, (fit.ci_high - fit.ci_low) / 3.92)
        found.append((z, label, trigger, fit, fset, hits))
    found.sort(key=lambda r: -r[0])
    out, chosen = [], []
    for z, label, trigger, fit, fset, hits in found:
        if len(out) >= top:
            break
        if any(len(fset & s) >= 0.5 * min(len(fset), len(s)) for s in chosen):
            continue
        chosen.append(fset)
        bias = "under" if fit.gamma > 0 else "over"
        out.append({
            "label_cn": f"全国人群{'少买' if bias == 'under' else '多买'}{label}",
            "trigger": trigger, "crowd_bias": bias,
            "evidence": {"window": [fit.issues[0], fit.issues[-1]], "n": fit.n, "hits": hits,
                         "z": round(z, 2), "gamma_pct": round(fit.gamma * 100, 2),
                         "ci_pct": [round(fit.ci_low * 100, 2), round(fit.ci_high * 100, 2)],
                         "buckets_scanned": len(buckets)},
        })
    return out
