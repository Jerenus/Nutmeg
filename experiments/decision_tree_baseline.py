"""决策树基线（2026-10-19）：在 decision-samples-v1 的前瞻行上学「市场热门不翻」。

无 sklearn，手写 CART（Gini，深度 ≤3，叶 ≥30）+ 5 折分层 CV；对照＝市场 p_fav 本身。
只报 AUC / Brier / 分裂变量，不出规则。
"""

from __future__ import annotations

import json
import math
import random

import numpy as np

random.seed(7)
np.random.seed(7)

with open("experiments/decision-samples-v1.jsonl", encoding="utf-8") as fh:
    rows = [json.loads(line) for line in fh]
rows = [
    r
    for r in rows
    if r.get("result")
    and (r.get("research") or {}).get("prospective") is True
    and r["derived"].get("fav")
]
print("前瞻训练集 n =", len(rows))


def period(d):
    return 0 if d < "2026-09-26" else (1 if d < "2026-10-05" else 2)


def feats(r):
    rs, d = r["research"], r["derived"]
    fav = d["fav"]
    anchor_is_fav = None
    if rs.get("anchor_side") in ("home", "away"):
        anchor_is_fav = 1.0 if (rs["anchor_side"] == "home") == (fav == "3") else 0.0
    elif rs.get("anchor_side") == "none":
        anchor_is_fav = -1.0
    lq = rs.get("license_questions") or {}
    dp = rs.get("death_proofs") or {}

    # 弱方（非热门两面）的死亡三证最大值
    def pc(x):
        if x is None:
            return None
        m = str(x).split("/")[0]
        return float(m) if m.replace(".", "").isdigit() else None

    dog_faces = [f for f in "310" if f != fav]
    dog_proofs = [pc(dp.get(f)) for f in dog_faces]
    dog_proofs = [x for x in dog_proofs if x is not None]
    ld = r.get("load") or {}
    f = {
        "p_fav": d["p_fav"],
        "sys_delta": d.get("sys_delta_fav_pp"),
        "drift": d.get("drift_fav_pp"),
        "anchor_is_fav": anchor_is_fav,
        "integ_fail": {"fail": 1.0, "symmetric_damage": 0.5, "pass": 0.0}.get(
            rs.get("anchor_integrity")
        ),
        "hole_rel": {"fav": 1.0, "dog": -1.0, "both": 0.5, "none": 0.0}.get(d.get("hole_rel")),
        "hole_priced": None if d.get("hole_priced") is None else float(bool(d["hole_priced"])),
        "verdict": {
            "home_clear": 2,
            "away_clear": 2,
            "home_edge": 1,
            "away_edge": 1,
            "even": 0,
        }.get(rs.get("verdict")),
        "stance_is_fav": None
        if rs.get("stance_face") not in ("3", "1", "0")
        else float(rs["stance_face"] == fav),
        "cover_is_draw": None
        if rs.get("stance_cover") not in ("3", "1", "0")
        else float(rs["stance_cover"] == "1"),
        "overpriced": None
        if not rs.get("market_read")
        else float(str(rs["market_read"]).startswith("overpriced")),
        "q1_spine": None if lq.get("q1_spine") is None else float(lq["q1_spine"]),
        "q2_route": None if lq.get("q2_route") is None else float(lq["q2_route"]),
        "q3a": None if lq.get("q3a_opponent_scores") is None else float(lq["q3a_opponent_scores"]),
        "q3b": None
        if lq.get("q3b_opponent_takes_points") is None
        else float(lq["q3b_opponent_takes_points"]),
        "dog_proofs_max": max(dog_proofs) if dog_proofs else None,
        "confidence": rs.get("confidence")
        if isinstance(rs.get("confidence"), (int, float))
        else None,
        "rubric_abstain": rs.get("rubric_abstain_n"),
        "kappa": (r.get("reader_b") or {}).get("kappa"),
        "rest_diff": ld.get("rest_diff"),
        "pm_log_volume": math.log10((r.get("polymarket") or {}).get("volume") or 1)
        if r.get("polymarket")
        else None,
        "label_real": (
            {"none": 0.0, "weak": 0.0, "real": 1.0, "strong": 1.0}.get(rs.get("upset_label"))
            if rs.get("upset_label_src") == "underdog_path.strength"
            else None
        ),
        "label_side_is_dog": (
            None if d.get("underdog_is_market_dog") is None else float(d["underdog_is_market_dog"])
        ),
        "period": period(r["date"]),
        "home_is_fav": float(fav == "3"),
    }
    return f


X_dicts = [feats(r) for r in rows]
y = np.array([1.0 if r["derived"]["fav_hit"] else 0.0 for r in rows])
names = list(X_dicts[0].keys())


def num(v):
    if isinstance(v, dict):
        v = v.get("value", v.get("kappa"))
    if isinstance(v, bool):
        return float(v)
    return float(v) if isinstance(v, (int, float)) else np.nan


X = np.array([[num(x[n]) for n in names] for x in X_dicts])
pf = X[:, names.index("p_fav")]
print("热门实开率 %.3f ｜ 市场均值 %.3f" % (y.mean(), pf.mean()))
print("非空率：", {n: round(float(np.mean(~np.isnan(X[:, i]))), 2) for i, n in enumerate(names)})


def auc(s, t):
    order = np.argsort(s)
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    # 平均秩处理 ties
    s_sorted = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = (i + j + 2) / 2
        i = j + 1
    n1 = t.sum()
    n0 = len(t) - n1
    return (ranks[t == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def gini(t):
    if len(t) == 0:
        return 0
    p = t.mean()
    return 2 * p * (1 - p)


class Node:
    def __init__(self, idx, depth):
        self.idx, self.depth, self.feat, self.thr, self.left, self.right, self.miss_left = (
            idx,
            depth,
            None,
            None,
            None,
            None,
            True,
        )


def grow(Xa, ya, idx, depth, max_depth, min_leaf):
    node = Node(idx, depth)
    node.value = ya[idx].mean()
    if depth >= max_depth or len(idx) < 2 * min_leaf:
        return node
    best = (0.0, None, None, None, None)
    g0 = gini(ya[idx]) * len(idx)
    for j in range(Xa.shape[1]):
        col = Xa[idx, j]
        valid = ~np.isnan(col)
        if valid.sum() < 2 * min_leaf:
            continue
        vals = np.unique(col[valid])
        if len(vals) < 2:
            continue
        cand = (
            np.quantile(vals, np.linspace(0.1, 0.9, 9))
            if len(vals) > 12
            else (vals[:-1] + vals[1:]) / 2
        )
        for thr in np.unique(cand):
            for miss_left in (True, False):
                left = (col <= thr) | (np.isnan(col) if miss_left else False)
                right = ~left
                if left.sum() < min_leaf or right.sum() < min_leaf:
                    continue
                g = g0 - gini(ya[idx[left]]) * left.sum() - gini(ya[idx[right]]) * right.sum()
                if g > best[0]:
                    best = (g, j, thr, miss_left, left)
    if best[1] is None or best[0] < 0.5:
        return node
    g, j, thr, miss_left, left = best
    node.feat, node.thr, node.miss_left, node.gain = j, thr, miss_left, g
    node.left = grow(Xa, ya, idx[left], depth + 1, max_depth, min_leaf)
    node.right = grow(Xa, ya, idx[~left], depth + 1, max_depth, min_leaf)
    return node


def predict(node, x):
    while node.feat is not None:
        v = x[node.feat]
        go_left = (np.isnan(v) and node.miss_left) or (not np.isnan(v) and v <= node.thr)
        node = node.left if go_left else node.right
    return node.value


def show(node, ind=0):
    if node.feat is None:
        print(" " * ind + f"→ 热门不翻 {node.value:.2f}（n={len(node.idx)}）")
        return
    print(
        " " * ind
        + f"[{names[node.feat]} ≤ {node.thr:.2f}"
        + f"{'，缺失走左' if node.miss_left else ''}] gain {node.gain:.1f}"
    )
    show(node.left, ind + 2)
    print(" " * ind + f"[{names[node.feat]} > {node.thr:.2f}]")
    show(node.right, ind + 2)


def cv(max_depth, min_leaf, folds=5, reps=3):
    aucs, briers, aucs_m, briers_m = [], [], [], []
    n = len(y)
    for rep in range(reps):
        rng = np.random.RandomState(rep)
        pos, neg = rng.permutation(np.where(y == 1)[0]), rng.permutation(np.where(y == 0)[0])
        fold_of = np.empty(n, int)
        fold_of[pos] = np.arange(len(pos)) % folds
        fold_of[neg] = np.arange(len(neg)) % folds
        pred = np.zeros(n)
        for k in range(folds):
            tr, te = np.where(fold_of != k)[0], np.where(fold_of == k)[0]
            tree = grow(X, y, tr, 0, max_depth, min_leaf)
            pred[te] = [predict(tree, X[i]) for i in te]
        aucs.append(auc(pred, y))
        briers.append(np.mean((pred - y) ** 2))
        aucs_m.append(auc(pf, y))
        briers_m.append(np.mean((pf - y) ** 2))
    return np.mean(aucs), np.std(aucs), np.mean(briers), np.mean(aucs_m), np.mean(briers_m)


print("\n## 5 折分层 CV ×3（对照＝市场 p_fav）")
print(f"{'深度/叶':<10}{'树 AUC':>10}{'±':>6}{'树 Brier':>10}{'市场 AUC':>10}{'市场 Brier':>11}")
for md, ml in ((1, 40), (2, 30), (3, 30), (3, 20), (4, 20)):
    a, sd, b, am, bm = cv(md, ml)
    print(f"{md}/{ml:<8}{a:>10.3f}{sd:>6.3f}{b:>10.4f}{am:>10.3f}{bm:>11.4f}")

# 逐特征配对 CV：p_fav + 该特征的深度 2 树（树总先切 p_fav，测不出增量——
# 保留作对照，真正的增量检验见下方残差检验）
print("\n## 逐特征：p_fav + 该特征 的深度 2 树 vs 只有 p_fav（CV AUC 差，正＝有增量）")
base_cols = [names.index("p_fav")]
res = []
for j, nme in enumerate(names):
    if nme == "p_fav":
        continue
    cols = base_cols + [j]
    Xs = X[:, cols]
    aucs = []
    for rep in range(3):
        rng = np.random.RandomState(rep)
        pos, neg = rng.permutation(np.where(y == 1)[0]), rng.permutation(np.where(y == 0)[0])
        fold_of = np.empty(len(y), int)
        fold_of[pos] = np.arange(len(pos)) % 5
        fold_of[neg] = np.arange(len(neg)) % 5
        pred = np.zeros(len(y))
        for k in range(5):
            tr, te = np.where(fold_of != k)[0], np.where(fold_of == k)[0]
            tree = grow(Xs, y, tr, 0, 2, 30)
            pred[te] = [predict(tree, Xs[i]) for i in te]
        aucs.append(auc(pred, y))
    res.append((np.mean(aucs), nme))
Xs = X[:, base_cols]
aucs = []
for rep in range(3):
    rng = np.random.RandomState(rep)
    pos, neg = rng.permutation(np.where(y == 1)[0]), rng.permutation(np.where(y == 0)[0])
    fold_of = np.empty(len(y), int)
    fold_of[pos] = np.arange(len(pos)) % 5
    fold_of[neg] = np.arange(len(neg)) % 5
    pred = np.zeros(len(y))
    for k in range(5):
        tr, te = np.where(fold_of != k)[0], np.where(fold_of == k)[0]
        tree = grow(Xs, y, tr, 0, 2, 30)
        pred[te] = [predict(tree, Xs[i]) for i in te]
    aucs.append(auc(pred, y))
base = np.mean(aucs)
print(f"只有 p_fav（深度 2 树）CV AUC = {base:.3f}；市场连续值 AUC = {auc(pf, y):.3f}")
for a, nme in sorted(res, reverse=True):
    print(f"  {nme:<16} {a:.3f}  ({a - base:+.3f})")

print("\n## 全样本拟合树（深度 3，叶 ≥30）——只看分裂变量，不当规则")
tree = grow(X, y, np.arange(len(y)), 0, 3, 30)
show(tree)


# ---------------- 残差检验：logit(p_fav) + 单特征 的逻辑回归，CV 对数损失 ----------------
def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_lr(A, t, l2=1.0, iters=50):
    w = np.zeros(A.shape[1])
    for _ in range(iters):
        z = A @ w
        p = 1 / (1 + np.exp(-z))
        g = A.T @ (p - t) + l2 * np.r_[0, w[1:]]
        H = (A * (p * (1 - p))[:, None]).T @ A + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)])
        w -= np.linalg.solve(H, g)
    return w


def design(cols):
    parts = [np.ones(len(y)), logit(pf)]
    for j in cols:
        c = X[:, j].copy()
        miss = np.isnan(c)
        mu, sd = np.nanmean(c), np.nanstd(c) or 1.0
        c = np.where(miss, 0.0, (c - mu) / sd)
        parts.append(c)
        if miss.any():
            parts.append(miss.astype(float))
    return np.column_stack(parts)


def cv_logloss(A, reps=5, folds=5):
    lls, coefs = [], []
    for rep in range(reps):
        rng = np.random.RandomState(100 + rep)
        pos, neg = rng.permutation(np.where(y == 1)[0]), rng.permutation(np.where(y == 0)[0])
        fold_of = np.empty(len(y), int)
        fold_of[pos] = np.arange(len(pos)) % folds
        fold_of[neg] = np.arange(len(neg)) % folds
        pred = np.zeros(len(y))
        for k in range(folds):
            tr, te = fold_of != k, fold_of == k
            w = fit_lr(A[tr], y[tr])
            pred[te] = 1 / (1 + np.exp(-(A[te] @ w)))
            coefs.append(w[2] if A.shape[1] > 2 else np.nan)
        pred = np.clip(pred, 1e-4, 1 - 1e-4)
        lls.append(-np.mean(y * np.log(pred) + (1 - y) * np.log(1 - pred)))
    return np.mean(lls), np.std(lls), np.array(coefs)


raw_ll = -np.mean(y * np.log(np.clip(pf, 1e-4, 1)) + (1 - y) * np.log(np.clip(1 - pf, 1e-4, 1)))
base_ll, base_sd, _ = cv_logloss(design([]))
print("\n## 残差检验：市场 logit 重校准 + 单特征（5 折 ×5，对数损失越低越好）")
print(
    f"市场原值 logloss {raw_ll:.4f}｜市场重校准（只拟 a+b·logit p）CV {base_ll:.4f} ±{base_sd:.4f}"
)
print(
    f"{'特征':<16}{'非空':>6}{'CV logloss':>12}{'Δ vs 重校准':>13}"
    f"{'系数(标准化)':>14}{'系数同号折':>10}"
)
out = []
for j, nme in enumerate(names):
    if nme == "p_fav":
        continue
    ll, sd, cf = cv_logloss(design([j]))
    same = max((cf > 0).mean(), (cf < 0).mean())
    out.append((ll - base_ll, nme, ll, cf.mean(), same, float(np.mean(~np.isnan(X[:, j])))))
for d, nme, ll, c, same, nn in sorted(out):
    print(f"{nme:<16}{nn:>6.2f}{ll:>12.4f}{d:>+13.4f}{c:>+14.3f}{same:>10.2f}")

# 前两名合在一起 + 时段稳定性
top = [nme for d, nme, *_ in sorted(out)[:3] if d < 0]
if top:
    ll, sd, _ = cv_logloss(design([names.index(n) for n in top]))
    print(f"\n前 {len(top)} 个改善特征合并 {top}：CV {ll:.4f}（Δ {ll - base_ll:+.4f}）")
    per = X[:, names.index("period")]
    print("分时段单变量残差（热门实开 − 市场，按特征二分）：")
    for n in top:
        j = names.index(n)
        c = X[:, j]
        med = np.nanmedian(c)
        for pv, lab in ((0, "≤09-25"), (1, "09-26..10-04"), (2, "≥10-05")):
            for side, m in (("≤中位", (c <= med)), (">中位", (c > med))):
                sel = (per == pv) & m & ~np.isnan(c)
                if sel.sum() >= 8:
                    print(
                        f"  {n:<14}{lab:<14}{side:<6} n={int(sel.sum()):>3}"
                        f"  残差 {100 * (y[sel].mean() - pf[sel].mean()):+6.1f}"
                        f" ±{100 * math.sqrt(y[sel].mean() * (1 - y[sel].mean()) / sel.sum()):4.1f}"
                    )
