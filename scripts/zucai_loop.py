"""足彩判断闭环 · 评估内核 (Discovery Loop kernel)

单一指标 = Brier Skill Score vs 去水市场价:  BSS = 1 - Brier(policy) / Brier(market)
语料 = .nutmeg-data/zucai/*-reads.json (prior/belief) × 官方赛果
用法:
  uv run python scripts/zucai_loop.py corpus                 # 语料体检
  uv run python scripts/zucai_loop.py eval --policy P.json   # 单策略样本外评估
  uv run python scripts/zucai_loop.py tourney P1.json P2.json ...   # 两两锦标赛(BTL)
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import hashlib
import json
import math
import os
import random
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZC = os.path.join(ROOT, ".nutmeg-data", "zucai")
IDX = {"3": "home", "1": "draw", "0": "away"}
FACES = ("home", "draw", "away")


RESULT_CACHE = os.path.join(ROOT, ".nutmeg-data", "zucai", "official-results.json")


def official_results(cache=None):
    """官方赛果串。优先读缓存,缺失时拉体彩 gameNo=90。"""
    cache = cache or RESULT_CACHE
    if os.path.exists(cache):
        return json.load(open(cache))
    import urllib.request
    url = ("https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
           "?gameNo=90&provinceId=0&pageSize=100&isVerify=1&pageNo=1")
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 Chrome/128.0.0.0"),
        "Referer": "https://www.sporttery.cn/"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    out = {it["lotteryDrawNum"]: it["lotteryDrawResult"]
           for it in data["value"]["list"] if it.get("lotteryDrawResult")}
    json.dump(out, open(cache, "w"), ensure_ascii=False, indent=1)
    return out


def load_corpus():
    """→ [{iss, no, prior, belief, actual, conf, note}] 按期号升序"""
    res = official_results()
    rows = []
    for p in sorted(glob.glob(os.path.join(ZC, "*-reads.json"))):
        iss = os.path.basename(p)[:5]
        if iss not in res:
            continue
        act = dict(zip([f"{i:02d}" for i in range(1, 15)], res[iss].split(), strict=False))
        for r in json.load(open(p)):
            m = re.search(r"-(\d{2})-had$", r.get("read_id", "") or "")
            if not m or m.group(1) not in act or not r.get("prior"):
                continue
            rows.append({"iss": iss, "no": m.group(1),
                         "prior": dict(r["prior"]),
                         "belief": dict(r.get("belief") or r["prior"]),
                         "actual": IDX[act[m.group(1)]],
                         "conf": r.get("confidence"), "note": r.get("note", "")})
    rows.sort(key=lambda d: (d["iss"], d["no"]))
    return rows


def brier(dist, actual):
    return sum((dist[k] - (1.0 if k == actual else 0.0)) ** 2 for k in FACES)


def bands(prior):
    t1 = max(prior, key=prior.get)
    v, dr = prior[t1], prior["draw"]
    bt = "T70+" if v >= .70 else "T60-70" if v >= .60 else "T45-60" if v >= .45 else "T<45"
    bd = "D30+" if dr >= .30 else "D25-30" if dr >= .25 else "D<25"
    return t1, bt, bd


def apply_policy(row, policy):
    """policy = {'weights': {'top:T45-60': pp, 'draw:D25-30': pp, ...}, 'scale': float}
    权重单位 pp
    从被加面之外的面等额扣除
    末端重归一。"""
    p = dict(row["prior"])
    t1, bt, bd = bands(p)
    w, sc = policy.get("weights", {}), policy.get("scale", 1.0)
    dt = w.get(f"top:{bt}", 0.0) / 100 * sc
    dd = w.get(f"draw:{bd}", 0.0) / 100 * sc
    if abs(dt) < 1e-12 and abs(dd) < 1e-12:
        return dict(p)                      # 零调整 = 恒等,不得经 clamp/归一化
    q = dict(p)
    q[t1] = p[t1] + dt
    if t1 != "draw":
        q["draw"] = p["draw"] + dd
        donors = [k for k in FACES if k not in (t1, "draw")]
        moved = dt + dd
    else:
        donors = [k for k in FACES if k != t1]
        moved = dt
    for k in donors:
        q[k] = p[k] - moved / len(donors)
    for k in q:
        q[k] = min(max(q[k], .01), .97)
    s = sum(q.values())
    return {k: v / s for k, v in q.items()}


def fit_bands(rows, shrink=10):
    """在给定窗上拟合价格带权重(价格校正残差 × 收缩)。"""
    acc, cnt = {}, {}
    for d in rows:
        t1, bt, bd = bands(d["prior"])
        for key, exp, hit in ((f"top:{bt}", d["prior"][t1], d["actual"] == t1),
                              (f"draw:{bd}", d["prior"]["draw"], d["actual"] == "draw")):
            a = acc.setdefault(key, [0.0, 0])
            a[0] += exp
            a[1] += int(hit)
            cnt[key] = cnt.get(key, 0) + 1
    return {k: ((h - e) / cnt[k]) * cnt[k] / (cnt[k] + shrink) * 100 for k, (e, h) in acc.items()}, cnt  # noqa: E501


def evaluate(rows, policy, boots=4000, seed=7):
    b0 = sum(brier(d["prior"], d["actual"]) for d in rows) / len(rows)
    b1 = sum(brier(apply_policy(d, policy), d["actual"]) for d in rows) / len(rows)
    random.seed(seed)
    bs = []
    for _ in range(boots):
        s = [rows[random.randrange(len(rows))] for _ in range(len(rows))]
        a = sum(brier(d["prior"], d["actual"]) for d in s) / len(s)
        b = sum(brier(apply_policy(d, policy), d["actual"]) for d in s) / len(s)
        bs.append(1 - b / a)
    bs.sort()
    return {"n": len(rows), "brier_market": b0, "brier_policy": b1,
            "bss": 1 - b1 / b0, "ci95": [bs[int(boots * .025)], bs[int(boots * .975)]]}


def pairwise(rows, pa, pb):
    """逐场两两对比 → (A胜, B胜, 平)。BTL 的输入。"""
    wa = wb = tie = 0
    for d in rows:
        x = brier(apply_policy(d, pa), d["actual"])
        y = brier(apply_policy(d, pb), d["actual"])
        if abs(x - y) < 1e-9:
            tie += 1
        elif x < y:
            wa += 1
        else:
            wb += 1
    return wa, wb, tie


def provenance():
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = "unknown"
    return {"git": sha, "at": datetime.datetime.now().isoformat(timespec="seconds")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["corpus", "eval", "tourney", "fit", "excl", "regime",
        "archive", "rank", "turn", "notes", "hyp", "search"])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--policy")
    ap.add_argument("--cut", default="26113")
    a = ap.parse_args()
    rows = load_corpus()
    tr = [d for d in rows if d["iss"] < a.cut]
    te = [d for d in rows if d["iss"] >= a.cut]

    if a.cmd == "corpus":
        moved = sum(1 for d in rows if any(abs(d['prior'][k] - d['belief'][k]) > 1e-9 for k in FACES))  # noqa: E501
        print(f"语料 {len(rows)} 场 / {len(set(d['iss'] for d in rows))} 期  "
              f"[{rows[0]['iss']}..{rows[-1]['iss']}]")
        print(f"判读移动分布: {moved} 场 ({moved/len(rows)*100:.1f}%)")
        print(f"训练窗(<{a.cut}) {len(tr)} 场 / 测试窗 {len(te)} 场")
        print("现状判读 BSS:", f"{evaluate(rows,
            {'weights': {}})['bss']*100:+.2f}% (belief=prior 时恒为0)")
    elif a.cmd == "fit":
        w, c = fit_bands(tr)
        print(json.dumps({"weights": w, "counts": c, "scale": 1.0,
                          "fitted_on": f"<{a.cut}", **provenance()}, ensure_ascii=False, indent=1))
    elif a.cmd == "eval":
        pol = json.load(open(a.policy))
        for name, S in (("样本内(训练窗)", tr), ("★样本外(测试窗)", te)):
            r = evaluate(S, pol)
            print(f"{name:<16} n={r['n']:<4} BSS={r['bss']*100:+6.2f}%  "
                  f"CI[{r['ci95'][0]*100:+.2f}%,{r['ci95'][1]*100:+.2f}%]")
    elif a.cmd == "excl":
        rows = load_tickets()
        print(f"排面决策 {len(rows)} 条 / {len(set(r['iss'] for r in rows))} 期  "
              f"[{min(r['iss'] for r in rows)}..{max(r['iss'] for r in rows)}]\n")
        print(f"{'档':<12}{'n':>5}{'fair均值':>10}{'实际开出':>10}{'R_excl':>10}   95%CI")
        for r in excl_report(rows):
            star = "  ⭐显著" if (r["ci"][0] > 0 or r["ci"][1] < 0) else ""
            print(f"{r['band']:<12}{r['n']:>5}{r['exp']*100:9.1f}%{r['act']*100:9.1f}%"
                  f"{r['R']*100:+9.1f}pp   [{r['ci'][0]*100:+.1f}, {r['ci'][1]*100:+.1f}]{star}")
    elif a.cmd == "turn":
        # 一转：propose(变异) → replay → validate → archive → rank
        base = json.load(open(a.policy)) if a.policy else {"style": "weighted", "scale": 1.0,
                                                           "weights": fit_bands(tr)[0]}
        pol = json.loads(json.dumps(base))
        if a.files:                      # turn <key> <delta_pp>  手动变异
            k = a.files[0]
            dv = float(a.files[1])
            pol.setdefault("weights", {})[k] = pol.get("weights", {}).get(k, 0.0) + dv
            pol["mutation"] = f"{k}{dv:+.2f}pp"
        m_in, m_out = evaluate(tr, pol), evaluate(te, pol)
        reg = "neutral"
        path = archive_put(pol, reg, m_out)
        recs = archive_load()
        names = [r["policy_id"] for r in recs]
        pols = {r["policy_id"]: r["policy"] for r in recs}
        pairs = {}
        for i, x in enumerate(names):
            for y in names[i+1:]:
                wa, wb, _ = pairwise(te, pols[x], pols[y])
                pairs[(x, y)] = (wa, wb)
        sc = btl(names, pairs) if len(names) > 1 else {names[0]: 0.0}
        rank = sorted(names, key=lambda n: -sc[n]).index(policy_id(pol)) + 1
        pw = power_stats(te, pol)
        g = gate_check(m_out, rank, power=pw)
        ok = g["deployable"]
        print(f"变异      {pol.get('mutation', '(基线)')}")
        print(f"样本内    BSS {m_in['bss']*100:+.2f}%")
        print(f"★样本外   BSS {m_out['bss']*100:+.2f}%  CI[{m_out['ci95'][0]*100:+.2f},{m_out['ci95'][1]*100:+.2f}]")  # noqa: E501
        print(f"BTL 排名  {rank}/{len(names)}")
        print(f"配对胜负  {pw['wins']}胜 {pw['losses']}负  符号检验 p={pw['p_sign']:.3f}")
        print(f"功效      80%功效最小可检出 BSS {pw['mde80']*100:.2f}%  → 判定「{g['verdict']}」")
        print("硬闸:", "  ".join(f"{'✅' if v else '❌'}{k.split()[0]}"
                                 for k, v in g["hard"].items()),
              f" 方向分 {g['direction']:.0f}/100  信息量 {g['information']*100:.0f}%")
        print(f"{'✅ 允许进入下期预注册' if ok else '❌ 不得进实盘'}  → {os.path.relpath(path, ROOT)}")  # noqa: E501
        with open(os.path.join(ROOT, "experiments", "attempts.log"), "a") as fh:
            fh.write(f"{datetime.datetime.now().isoformat(timespec='minutes')} | turn | "
                     f"{pol.get('mutation','base')} | {m_out['bss']*100:+.2f}% "
                     f"CI[{m_out['ci95'][0]*100:+.2f},{m_out['ci95'][1]*100:+.2f}] | "
                     f"{'过闸' if ok else '未过闸'}\n")
    elif a.cmd == "search":
        for d in rows:
            d["ann"] = parse_note(d["note"])
        res, ntests = search_factors(tr)
        print(f"训练窗 {len(tr)} 场，枚举 {ntests} 个(因子组合 × 目标)，min_n=25")
        import statistics as _st
        zs = [abs(x["z"]) for x in res]
        print(f"零假设下 {ntests} 次检验的期望最大|z| ≈ "
              f"{_st.NormalDist().inv_cdf(1 - 0.5 / ntests):.2f}"
              f"   实际最大|z| = {zs[0]:.2f}")
        print(f"\n{'因子组合':<38}{'目标':<7}{'n':>4}{'残差':>9}{'z':>7}   测试窗验证")
        print("-" * 96)
        shown = 0
        for x in res:
            if shown >= 12:
                break
            sub = [d for d in te if all(k in features(d) for k in x["factors"])]
            if len(sub) < 15:
                continue
            n2, r2, se2, z2 = _resid([targets(d)[x["target"]] for d in sub])
            same = "✅同向" if r2 * x["r"] > 0 else "❌反向"
            print(f"{' × '.join(x['factors']):<38}{x['target']:<7}{x['n']:>4}"
                  f"{x['r']*100:+8.1f}pp{x['z']:+7.2f}   n={n2:<4}"
                  f"{r2*100:+7.1f}pp z={z2:+5.2f} {same}")
            shown += 1
    elif a.cmd == "notes":
        ann = [parse_note(d["note"]) for d in rows]
        tot = len(rows)
        for k, f in (("有标注", lambda x: x["annotated"]),
                     ("完整度", lambda x: x["integrity"] is not None),
                     ("方向旗", lambda x: bool(x["dir_flags"])),
                     ("无方向旗", lambda x: bool(x["nondir_flags"])),
                     ("崩盘标记", lambda x: bool(x["crash_flags"])),
                     ("四问", lambda x: x["q4"] is not None)):
            c = sum(1 for x in ann if f(x))
            print(f"  {k:<8} {c:>4} / {tot} ({c/tot*100:.0f}%)")
    elif a.cmd == "hyp":
        for d in rows:
            d["ann"] = parse_note(d["note"])

        def t1(d):
            return max(d["prior"], key=d["prior"].get)

        def t3(d):
            return min(d["prior"], key=d["prior"].get)

        T = {
            "正路": lambda d: (d["prior"][t1(d)], int(d["actual"] == t1(d))),
            "非模态": lambda d: (1 - d["prior"][t1(d)], int(d["actual"] != t1(d))),
            "开平": lambda d: (d["prior"]["draw"], int(d["actual"] == "draw")),
            "第3面": lambda d: (d["prior"][t3(d)], int(d["actual"] == t3(d))),
        }
        HYPS = [
            ("方向旗→非模态", lambda d: bool(d["ann"]["dir_flags"]), "非模态"),
            ("方向旗→开平", lambda d: bool(d["ann"]["dir_flags"]), "开平"),
            ("无方向旗→非模态", lambda d: bool(d["ann"]["nondir_flags"]), "非模态"),
            ("C6:无方向旗→第3面", lambda d: bool(d["ann"]["nondir_flags"]), "第3面"),
            ("锚方FAIL→正路", lambda d: d["ann"]["integrity"] == "fail", "正路"),
            ("锚方PASS→正路", lambda d: d["ann"]["integrity"] == "pass", "正路"),
            ("C9崩盘标记→正路", lambda d: bool(d["ann"]["crash_flags"]), "正路"),
            ("基线:全语料→正路", lambda d: True, "正路"),
        ]
        print(f"{'假设':<24}{'n':>5}{'期望':>8}{'实际':>8}{'残差':>9}"
              f"{'95%CI':>17}{'MDE80':>8}  判定")  # noqa: E501
        print("-" * 92)
        for name, sel, tk in HYPS:
            r = falsify(rows, name, sel, T[tk])
            if r.get("verdict") == "样本不足":
                print(f"{name:<24}{r['n']:>5}   样本不足")
                continue
            print(f"{name:<24}{r['n']:>5}{r['exp']*100:7.1f}%{r['act']*100:7.1f}%"
                  f"{r['R']*100:+8.1f}pp  [{r['ci'][0]*100:+5.1f},{r['ci'][1]*100:+5.1f}]"
                  f"{r['mde80']*100:7.1f}pp  {r['verdict']}")  # noqa: E501
    elif a.cmd == "regime":
        reg = issue_regimes(rows)
        cnt = collections.Counter(reg.values())
        for i in sorted(reg):
            print(f"  {i}  {reg[i]}")
        print("\n分布:", dict(cnt))
    elif a.cmd == "archive":
        pol = json.load(open(a.policy))
        pol.setdefault("style", "weighted")
        m = evaluate(te, pol)
        reg = a.files[0] if a.files else "neutral"
        path = archive_put(pol, reg, m)
        print(f"入档 {path}\n  BSS={m['bss']*100:+.2f}% CI[{m['ci95'][0]*100:+.2f},{m['ci95'][1]*100:+.2f}]")  # noqa: E501
    elif a.cmd == "rank":
        recs = archive_load()
        if not recs:
            print("档案为空")
            return
        pols = {r["policy_id"]: r["policy"] for r in recs}
        names = list(pols)
        pairs = {}
        for i, x in enumerate(names):
            for y in names[i+1:]:
                wa, wb, _ = pairwise(te, pols[x], pols[y])
                pairs[(x, y)] = (wa, wb)
        sc = btl(names, pairs) if len(names) > 1 else {names[0]: 0.0}
        order = sorted(names, key=lambda n: -sc[n])
        print(f"{'排名':<4}{'policy':<12}{'style':<12}{'BTL':>7}{'BSS':>8}{'配对胜率':>9}"
              f"{'p值':>7}{'方向分':>7}{'信息量':>7}{'判定':>7}  硬闸  档位 幅度")  # noqa: E501
        for k, n in enumerate(order, 1):
            r = next(x for x in recs if x["policy_id"] == n)
            pw = power_stats(te, r["policy"])
            g = gate_check(r["metrics"], k, power=pw)
            hard = "✅" if g["hard_pass"] else "❌" + "/".join(
                kk.split()[0] for kk, vv in g["hard"].items() if not vv)
            print(f"{k:<4}{n:<12}{r['style']:<12}{sc[n]:+7.3f}"
                  f"{r['metrics']['bss']*100:+7.2f}%{g['winrate']*100:8.1f}%"
                  f"{g['p_sign']:7.3f}{g['direction']:7.0f}{g['information']*100:6.0f}%"
                  f"{g['verdict']:>7}  {hard}  {(g['tier'] or '—'):<4}"
                  f"×{g['deploy_scale']:.1f}")
        top = next(x for x in recs if x["policy_id"] == order[0])
        mde = power_stats(te, top["policy"])["mde80"]
        print(f"\n⚠️ 本窗功效: n={len(te)}，80%功效下最小可检出 BSS ≈ {mde*100:.2f}%。"
              f"「欠功效」= 样本查不出来，**不等于**策略不好。")  # noqa: E501
    elif a.cmd == "tourney":
        pols = {os.path.basename(f): json.load(open(f)) for f in a.files}
        names = list(pols)
        print("两两锦标赛(测试窗,逐场胜负):")
        for i, x in enumerate(names):
            for y in names[i+1:]:
                wa, wb, t = pairwise(te, pols[x], pols[y])
                print(f"  {x} {wa} : {wb} {y}   (平{t})")




# ─────────────────────────── H2 · 表达层指标 ───────────────────────────
FACE_KEY = {"3": "home", "1": "draw", "0": "away"}


def load_tickets():
    """扫全部票面文件 → 去重的排面决策 [{iss,no,face,fair,came_in,band,is_modal}]

    去重口径: (期, 场, 被排面) 唯一 —— 同一期多个票版排掉同一个面只算一次决策。
    """
    res = official_results()
    seen, rows = set(), []
    for p in sorted(glob.glob(os.path.join(ZC, "*-legs*.json"))):
        iss = os.path.basename(p)[:5]
        if iss not in res or not iss.isdigit():
            continue
        try:
            d = json.load(open(p))
        except Exception:
            continue
        legs = d.get("legs") if isinstance(d, dict) else None
        if not isinstance(legs, dict):
            continue
        act = dict(zip([str(i) for i in range(1, 15)], res[iss].split(), strict=False))
        for no, leg in legs.items():
            if not no.isdigit() or not isinstance(leg, dict):
                continue
            faces, fair = leg.get("faces"), leg.get("fair")
            if not faces or not isinstance(fair, dict) or no not in act:
                continue
            modal = max(("3", "1", "0"), key=lambda c: fair[FACE_KEY[c]])
            for c in ("3", "1", "0"):
                if c in faces:
                    continue
                key = (iss, no, c)
                if key in seen:
                    continue
                seen.add(key)
                v = fair[FACE_KEY[c]]
                band = ("翻面(模态)" if c == modal else
                        "省钱≤15" if v <= .15 else
                        "灰带15-20" if v <= .20 else "买方差>20")
                rows.append({"iss": iss, "no": no, "face": c, "fair": v,
                             "came_in": int(act[no] == c), "band": band,
                             "is_modal": c == modal})
    return rows


def excl_report(rows, boots=4000, seed=11):
    out = []
    groups = collections.OrderedDict()
    for r in rows:
        groups.setdefault(r["band"], []).append(r)
    groups["★全体"] = rows
    for band, S in groups.items():
        n = len(S)
        exp = sum(r["fair"] for r in S) / n
        act = sum(r["came_in"] for r in S) / n
        random.seed(seed)
        bs = []
        for _ in range(boots):
            s = [S[random.randrange(n)] for _ in range(n)]
            bs.append(sum(r["came_in"] for r in s) / n - sum(r["fair"] for r in s) / n)
        bs.sort()
        out.append({"band": band, "n": n, "exp": exp, "act": act,
                    "R": act - exp,
                    "ci": [bs[int(boots * .025)], bs[int(boots * .975)]]})
    return out



# ─────────────────────── regime / 档案 / BTL / Gate ───────────────────────
ARCHIVE = os.path.join(ROOT, "experiments", "archive")
STYLES = ("market", "weighted", "ontology", "contrarian")


REGIME_CUTS = (6.97, 7.73)   # 语料三分位, 2026-09-14 标定于 22 期 (cold/neutral/hot 各约 1/3)


def regime_of(rows_of_issue):
    """赛前可判：Σtop1 = 期望模态命中数。不使用赛果。切点=语料三分位。"""
    exp = sum(max(d["prior"].values()) for d in rows_of_issue)
    lo, hi = REGIME_CUTS
    return "cold" if exp <= lo else ("hot" if exp >= hi else "neutral")


def issue_regimes(rows):
    by = collections.OrderedDict()
    for d in rows:
        by.setdefault(d["iss"], []).append(d)
    return {i: regime_of(v) for i, v in by.items()}


def policy_id(pol):
    blob = json.dumps({k: pol.get(k) for k in ("weights", "scale", "style")},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:10]


def archive_put(pol, regime, metrics):
    style = pol.get("style", "weighted")
    pid = policy_id(pol)
    d = os.path.join(ARCHIVE, regime, style)
    os.makedirs(d, exist_ok=True)
    rec = {"policy_id": pid, "regime": regime, "style": style,
           "policy": pol, "metrics": metrics, **provenance()}
    json.dump(rec, open(os.path.join(d, f"{pid}.json"), "w"), ensure_ascii=False, indent=1)
    return os.path.join(d, f"{pid}.json")


def archive_load():
    out = []
    for f in glob.glob(os.path.join(ARCHIVE, "*", "*", "*.json")):
        try:
            out.append(json.load(open(f)))
        except Exception:
            pass
    return out


def btl(names, pairs, iters=300):
    """Bradley-Terry: pairs[(a,b)] = (wins_a, wins_b) → 实力分(log 尺度, 几何均值归一)"""
    r = {n: 1.0 for n in names}
    for _ in range(iters):
        for n in names:
            num = 0.0
            den = 0.0
            for (a, b), (wa, wb) in pairs.items():
                if a == n:
                    num += wa
                    den += (wa + wb) / (r[a] + r[b])
                elif b == n:
                    num += wb
                    den += (wa + wb) / (r[a] + r[b])
            if den > 0:
                r[n] = max(num / den, 1e-9)
        g = sum(r.values()) / len(r)
        r = {k: v / g for k, v in r.items()}
    return {k: math.log(v) for k, v in r.items()}


def power_stats(rows, pol):
    """配对功效：逐场 (policy - market) 的 Brier 差 → se / MDE / 符号检验。"""
    diff = [brier(apply_policy(d, pol), d["actual"]) - brier(d["prior"], d["actual"])
            for d in rows]
    n = len(diff)
    mu = sum(diff) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in diff) / max(n - 1, 1))
    se = sd / math.sqrt(n)
    b0 = sum(brier(d["prior"], d["actual"]) for d in rows) / n
    w = sum(1 for x in diff if x < -1e-12)
    lo = sum(1 for x in diff if x > 1e-12)
    p_sign = 1.0
    if w + lo:
        k = min(w, lo)
        p_sign = min(1.0, 2 * sum(math.comb(w + lo, i) * 0.5 ** (w + lo)
                                  for i in range(k + 1)))
    return {"paired_mean": mu, "se": se, "mde80": 2.80 * se / b0,
            "wins": w, "losses": lo, "p_sign": p_sign}


def _tier(hard_ok, direction, information):
    """三档准入(2026-09-14 放宽)：正式=全幅度 / 试用=半幅度 / 候选=只入档不部署。"""
    if hard_ok and direction >= 60 and information >= 0.50:
        return "正式"
    if hard_ok and direction >= 55 and information >= 0.25:
        return "试用"
    return "候选" if direction >= 40 else None


def gate_check(metrics, rank, human_ok=None, power=None):
    """闸 v2：证据类给分、有效性/权威类硬否决，且分数必须带功效折扣。

    2026-09-14 改版依据：
    1) 现行绝对统计闸要求 n≈5,514 场(≈2.5年)才可能通过；n=154 时 80% 功效的
       最小可检出 BSS 为 2.93%，而点估计仅 0.28% —— 欠功效约 10 倍。
       「不过闸」长期等价于「查不出来」，却被读成「策略不好」。
    2) 但**放松阈值是错的修法**：把分数加权到能过，等于把"分辨不出"洗成"看起来不错"。
       故拆成两个数，不合并：
         方向分 direction  —— 如果样本足够，这个策略看上去有多好
         信息量 information —— 这个样本能支撑多少（= |观测效应| / MDE80）
       部署要求：硬闸全过 AND 方向分≥60 AND (信息量≥50% OR 用户显式行权)。
    """
    hard = {
        "泄漏闸 BSS<=+5%": metrics["bss"] <= 0.05,
        "人类闸 未否决": human_ok is not False,
    }
    winrate = 0.5
    p_sign = 1.0
    if power and (power["wins"] + power["losses"]):
        winrate = power["wins"] / (power["wins"] + power["losses"])
        p_sign = power["p_sign"]
    noninf = 1.0 if (metrics["ci95"][1] > 0 and metrics["bss"] >= 0) else (
        0.5 if metrics["ci95"][1] > 0 else 0.0)
    rankscore = 0.0 if rank is None else max(0.0, 1.0 - (rank - 1) / 5.0)
    direction = 100 * (0.40 * noninf
                       + 0.35 * min(max((winrate - .5) / .10, 0), 1)
                       + 0.25 * rankscore)
    mde = (power or {}).get("mde80")
    information = 0.0 if not mde else min(1.0, abs(metrics["bss"]) / mde)
    verdict = ("确认" if metrics["ci95"][0] > 0 else
               "证伪" if metrics["ci95"][1] < 0 else "欠功效")
    return {
        "hard_pass": all(hard.values()), "hard": hard,
        "direction": direction, "information": information,
        "winrate": winrate, "p_sign": p_sign, "rank": rank,
        "mde80": mde, "verdict": verdict,
        "deployable": all(hard.values()) and direction >= 60 and information >= 0.50,
        # 2026-09-14 放宽:试用档允许半幅度部署(信息量≥25%),候选档只入档
        "tier": _tier(all(hard.values()), direction, information),
        "deploy_scale": {"正式": 1.0, "试用": 0.5}.get(
            _tier(all(hard.values()), direction, information), 0.0),
    }



# ──────────────────── note 解析器（W2 · 私有标注层回填）────────────────────
# 跨期 note 格式不一致(26103 散文 / 26110 括号 / 26122 管道)，故按已知旗名做
# 词表匹配而非结构解析。词表由 2026-09-14 全语料 token 频次提取。
DIR_FLAGS = frozenset({"anchor_shield_out", "self_made_tail", "suspension_breaker_out",
                      "weak_home_draw_trap"})
NONDIR_FLAGS = frozenset({"two_way_instability", "venue_anomaly", "dressing_room_turmoil",
                          "source_disagreement", "undecided_second_leg"})
CRASH_FLAGS = frozenset({"opening_promoted_vs_paper", "opening_new_coach_debut"})
REGIME_FLAGS = frozenset({"league_draw_regime"})


def parse_note(note: str) -> dict:
    """从 reads.note 抽结构化标注。缺失一律返回 None，不猜。"""
    n = note or ""
    found = set(re.findall(r"[a-z][a-z0-9_]{5,}", n))
    integ = None
    m = re.search(r"完整度[:：]\s*(pass|fail)", n)
    if m:
        integ = m.group(1)
    q4 = None
    m = re.search(r"四问[:：]\s*([\d.]+)\s*/\s*([\d.]+)", n)
    if m and float(m.group(2)):
        q4 = float(m.group(1)) / float(m.group(2))
    return {
        "dir_flags": sorted(found & DIR_FLAGS),
        "nondir_flags": sorted(found & NONDIR_FLAGS),
        "crash_flags": sorted(found & CRASH_FLAGS),
        "regime_flags": sorted(found & REGIME_FLAGS),
        "integrity": integ,
        "q4": q4,
        "annotated": bool(found & (DIR_FLAGS | NONDIR_FLAGS | CRASH_FLAGS)) or integ is not None,
    }


def falsify(rows, name, select, target, label_t="事件"):
    """证伪检验：在 select 选中的子集上，target 事件的实际率 vs 价格期望。

    返回 (n, 期望, 实际, 残差pp, 95%CI, MDE80, 判定)。
    判定 = 确认 / 证伪 / 欠功效 —— 关键是把「查不出来」与「不成立」分开。
    """
    S = [(target(d)[0], target(d)[1]) for d in rows if select(d)]
    if len(S) < 8:
        return {"name": name, "n": len(S), "verdict": "样本不足"}
    n = len(S)
    exp = sum(e for e, _ in S) / n
    act = sum(h for _, h in S) / n
    sd = math.sqrt(sum((h - e - (act - exp)) ** 2 for e, h in S) / max(n - 1, 1))
    se = sd / math.sqrt(n)
    random.seed(17)
    bs = []
    for _ in range(5000):
        s = [S[random.randrange(n)] for _ in range(n)]
        bs.append(sum(h for _, h in s) / n - sum(e for e, _ in s) / n)
    bs.sort()
    lo, hi = bs[125], bs[4875]
    mde = 2.80 * se
    verdict = ("⭐确认" if lo > 0 else "⭐反向确认" if hi < 0 else
               "证伪" if abs(hi - lo) / 2 < mde and abs(act - exp) < mde / 2 else "欠功效")
    return {"name": name, "n": n, "exp": exp, "act": act, "R": act - exp,
            "ci": [lo, hi], "mde80": mde, "verdict": verdict, "label": label_t}


# ─────────────────── 因子搜索（train 搜索 → test 验证）───────────────────
def _band_top(v):
    return "70+" if v >= .70 else "60-70" if v >= .60 else "45-60" if v >= .45 else "<45"


def features(d):
    """把每场比赛摊成二值因子。价格因子 + 标注因子 + 板型因子。"""
    p = d["prior"]
    t1 = max(p, key=p.get)
    v = p[t1]
    srt = sorted(p.values(), reverse=True)
    gap = srt[0] - srt[1]
    a = d.get("ann") or parse_note(d["note"])
    conf = d.get("conf")
    f = {
        f"价_top1_{_band_top(v)}": True,
        f"价_平_{'30+' if p['draw'] >= .30 else '25-30' if p['draw'] >= .25 else '<25'}": True,
        f"价_热门在_{ {'home':'主','draw':'平','away':'客'}[t1] }": True,
        f"价_gap_{'大>25' if gap > .25 else '中10-25' if gap > .10 else '小<10'}": True,
        "标_方向旗": bool(a["dir_flags"]),
        "标_无方向旗": bool(a["nondir_flags"]),
        "标_锚方FAIL": a["integrity"] == "fail",
        "标_锚方PASS": a["integrity"] == "pass",
        "标_崩盘标记": bool(a["crash_flags"]),
        "标_conf低(<=2)": conf is not None and conf <= 2,
        "标_conf高(>=4)": conf is not None and conf >= 4,
        "标_双旗齐发": bool(a["dir_flags"]) and bool(a["nondir_flags"]),
        "标_零旗": a["annotated"] and not a["dir_flags"] and not a["nondir_flags"],
    }
    return {k: bool(x) for k, x in f.items() if x}


def targets(d):
    p = d["prior"]
    t1 = max(p, key=p.get)
    t3 = min(p, key=p.get)
    return {
        "正路": (p[t1], int(d["actual"] == t1)),
        "开平": (p["draw"], int(d["actual"] == "draw")),
        "第3面": (p[t3], int(d["actual"] == t3)),
    }


def _resid(S):
    n = len(S)
    exp = sum(e for e, _ in S) / n
    act = sum(h for _, h in S) / n
    r = act - exp
    var = sum(((h - e) - r) ** 2 for e, h in S) / max(n - 1, 1)
    se = math.sqrt(var / n)
    return n, r, se, (r / se if se > 0 else 0.0)


def search_factors(rows, min_n=25, max_order=2):
    """枚举单因子与二阶交互 × 三个目标，按 |z| 排序。价格校正残差。"""
    for d in rows:
        d["ann"] = parse_note(d["note"])
        d["_f"] = features(d)
        d["_t"] = targets(d)
    keys = sorted({k for d in rows for k in d["_f"]})
    combos = [(k,) for k in keys]
    if max_order >= 2:
        combos += [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]]
    out = []
    for c in combos:
        sub = [d for d in rows if all(k in d["_f"] for k in c)]
        if len(sub) < min_n:
            continue
        for tname in ("正路", "开平", "第3面"):
            n, r, se, z = _resid([d["_t"][tname] for d in sub])
            out.append({"factors": c, "target": tname, "n": n, "r": r, "se": se, "z": z})
    out.sort(key=lambda x: -abs(x["z"]))
    return out, len(out)


# ──────────── 本体特征（prep 文件：DC 拟合 / 进球轴 / 比分分布）────────────
def load_prep_corpus():
    """reads(prior/conf/note) ⋈ prep(本体特征) ⋈ 官方赛果。"""
    base = {(d["iss"], str(int(d["no"]))): d for d in load_corpus()}
    out = []
    for iss in sorted({k[0] for k in base}):
        rec = None
        for suffix in ("prep-revision", "prep-afternoon"):
            p = os.path.join(ZC, f"{iss}-{suffix}.json")
            if os.path.exists(p):
                try:
                    r = json.load(open(p)).get("records")
                    if isinstance(r, dict) and r:
                        rec = r
                        break
                except Exception:
                    pass
        if not rec:
            continue
        for no, pr in rec.items():
            d = base.get((iss, str(int(no))))
            if not d or not isinstance(pr, dict):
                continue
            d = dict(d)
            d["prep"] = pr
            out.append(d)
    return out


def onto_features(d):
    """从本体字段派生二值因子。每条都带机制理由，不做盲目组合。"""
    pr = d.get("prep") or {}
    p = d["prior"]
    t1 = max(p, key=p.get)
    lam = pr.get("lambda") or [None, None, None]
    f = {}
    if lam[0] is not None and lam[1] is not None:
        tot = lam[0] + lam[1]
        dif = abs(lam[0] - lam[1])
        # 机制:总进球高 → 强队兑现率高(2026-09-13 中介分析:进球多则强锚+14.6pp)
        f[f"本_总进球λ_{'高>2.9' if tot > 2.9 else '中2.4-2.9' if tot > 2.4 else '低<2.4'}"] = True
        # 机制:预期净胜球大 = 实力差被进球模型确认(与 1X2 独立的第二条证据)
        f[f"本_λ差_{'大>0.8' if dif > 0.8 else '中0.4-0.8' if dif > 0.4 else '小<0.4'}"] = True
    o = pr.get("over25")
    if o is not None:
        f[f"本_大2.5_{'高>60' if o > .60 else '中45-60' if o > .45 else '低<45'}"] = True
    ts = pr.get("top_scores") or []
    if ts:
        # 机制:模态比分概率高 = 比赛形状集中 = 更可预测
        f[f"本_模态比分_{'集中>13' if ts[0][1] > .13 else '分散<=13'}"] = True
        f["本_模态比分是平"] = ts[0][0].split(":")[0] == ts[0][0].split(":")[1]
    hb, ab = pr.get("home_by_2plus"), pr.get("away_by_2plus")
    if hb is not None and ab is not None:
        # 机制:血洗概率 = 强队"打穿"的通道是否存在
        big = hb if t1 == "home" else ab if t1 == "away" else max(hb, ab)
        f[f"本_热门血洗率_{'高>25' if big > .25 else '中15-25' if big > .15 else '低<15'}"] = True
    fl = pr.get("fit_loss")
    if fl is not None:
        # 机制:DC 拟合残差高 = 1X2 与进球盘互相矛盾 = 两个市场不同意
        f[f"本_拟合残差_{'高>0' if fl > 1e-9 else '零'}"] = True
    f["本_有体彩进球锚"] = bool(pr.get("ttg_anchor"))
    lg = pr.get("league")
    if lg:
        f[f"本_联赛_{lg}"] = True
    kb = pr.get("kickoff_bj") or ""
    if len(kb) >= 13:
        try:
            f[f"本_开球_{'深夜>=1点' if int(kb[11:13]) < 6 else '晚间'}"] = True
        except ValueError:
            pass
    return {k: True for k, v in f.items() if v}


# ──────────────── 三档准入 + 机制检验（2026-09-14 用户要求放宽准入）────────────────
TIERS = (("正式", 0.0), ("试用", 1.5), ("候选", 1.0))


def admit_tier(r, ci_lo, ci_hi, z):
    """三档准入：正式=CI不含0 / 试用=|z|≥1.5 / 候选=|z|≥1.0 / 否则不入档。

    放宽准入的目的是让更多候选进入观察，而不是让更多候选进入实盘——
    试用档只允许半幅度部署，候选档只入档不部署。
    """
    if ci_lo > 0 or ci_hi < 0:
        return "正式"
    if abs(z) >= 1.5:
        return "试用"
    if abs(z) >= 1.0:
        return "候选"
    return None


def mechanism_checks(cells):
    """机制检验：比显著性更能挡住噪声，且几乎零成本。

    cells = [(标签, 残差, n), ...] 按自然序（如休息天数递增）。
    返回 (通过?, 明细)。2026-09-14 赛程密集因子正是被这两条拦下的：
    CI 不含 0 但对称性失败、相邻档反号。
    """
    out = {}
    vals = [c[1] for c in cells]
    # ① 无大幅反号（弱条件）
    flips = sum(1 for i in range(len(vals) - 1)
                if vals[i] * vals[i + 1] < 0 and abs(vals[i] - vals[i + 1]) > 0.15)
    out["① 相邻档无大幅反号"] = flips == 0
    # ② ⭐真趋势（强条件，2026-09-15 补）：相邻档差分至少 2/3 同号，
    #    且首尾跨度 ≥ 档内最大绝对残差。仅靠 ① 会放过「平坦无趋势」——
    #    赔率位移因子在 n=132 时看似有信号，扩到 n=339 后序列变成
    #    +2.4/-1.5/+4.6/+2.1/+3.9（纯平），而 ① 仍判通过。
    if len(vals) >= 3:
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        pos = sum(1 for d in diffs if d > 0)
        same_dir = max(pos, len(diffs) - pos) / len(diffs)
        span = abs(vals[-1] - vals[0])
        out["② 存在真趋势(差分同向≥2/3 且首尾跨度足够)"] = (
            same_dir >= 2 / 3 and span >= max(abs(v) for v in vals))
    # ③ 样本充分
    out["③ 样本 主档n≥25"] = max((c[2] for c in cells), default=0) >= 25
    return all(out.values()), out

if __name__ == "__main__":
    main()
