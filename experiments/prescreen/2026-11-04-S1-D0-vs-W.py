import glob
import json
import math
import random
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, ".")
from nutmeg.decision.zucai_draft import load_board, prescription_point

pz = json.load(open(".nutmeg-data/zucai/official-prizes.json"))
print("prize keys", list(pz)[:4])
recs = None
for k, v in pz.items():
    if isinstance(v, (dict, list)) and len(v) > 20:
        recs = v
        print("records under", k, type(v).__name__, len(v))
        break
sample = recs[0] if isinstance(recs, list) else recs[sorted(recs)[-1]]
print("sample", json.dumps(sample, ensure_ascii=False)[:500])


def rj_prize(issue):
    r = (
        recs.get(issue)
        if isinstance(recs, dict)
        else next(
            (x for x in recs if str(x.get("issue") or x.get("lotteryDrawNum")) == issue), None
        )
    )
    if not r:
        return None
    for key in ("rj_prize", "renjiu_prize", "prize_rj", "renjiu_per_note"):
        if key in r:
            return float(r[key])
    if "prizeLevelListRj" in r and r["prizeLevelListRj"]:
        return float(str(r["prizeLevelListRj"][0]["stakeAmount"]).replace(",", ""))
    rj = r.get("renjiu") or r.get("rj")
    if isinstance(rj, dict):
        for key in ("prize", "per_note", "stakeAmount", "amount", "stake_amount"):
            if key in rj:
                return float(str(rj[key]).replace(",", ""))
    return None


off = json.load(open(".nutmeg-data/zucai/official-results.json"))
FACE = {"home": "3", "draw": "1", "away": "0"}


def order(f):
    return sorted(f, key=lambda k: -f[k])


def notes(fs):
    return math.prod(len(x) for x in fs.values())


def W_dict(legs):
    # 字典主形：板型按 ≥65% 场数 → 单数；单=最大面最高的 s 场；
    # 其余按 P 排的 9 场双(模态+第二面)；硬币当双；超帽先把 p1/(p1+p2) 最高的双改单
    board = sorted(legs, key=lambda n: -max(legs[n]["market"].values()))
    nAB = sum(1 for n in legs if max(legs[n]["market"].values()) >= 0.65)
    s = 2 if nAB <= 2 else 3 if nAB == 3 else 4
    cap = {2: 128, 3: 64, 4: 32}[s]
    pick = board[:9]
    fs = {}
    for i, n in enumerate(pick):
        o = [FACE[k] for k in order(legs[n]["market"])]
        fs[n] = o[0] if i < s else o[0] + o[1]
    while notes(fs) > cap:
        c = [n for n in fs if len(fs[n]) == 2]
        n = max(
            c,
            key=lambda n: (lambda f: f[0] / (f[0] + f[1]))(
                sorted(legs[n]["market"].values(), reverse=True)
            ),
        )
        fs[n] = fs[n][0]
    return fs, s, nAB


def score(fs, res, prize):
    hit = {n: (res[int(n) - 1] in f) for n, f in fs.items()}
    won = sum(1 for sub in combinations(list(fs), 9) if all(hit[n] for n in sub))
    return 2 * notes(fs), won * prize, won > 0


out = []
for p in sorted(glob.glob(".nutmeg-data/zucai/*-legs-base.json")):
    iss = re.search(r"(\d{5})-legs", p).group(1)
    if iss not in off or "*" in off[iss]:
        continue
    try:
        legs = load_board(Path(".nutmeg-data"), iss)
    except Exception as e:
        print("skip", iss, repr(e)[:80])
        continue
    pr = rj_prize(iss)
    if pr is None:
        continue
    res = off[iss].split()
    w, s, nAB = W_dict(legs)
    d4 = prescription_point(legs, channel="renjiu", cap_yuan=400)
    d8 = prescription_point(legs, channel="renjiu", cap_yuan=800)
    rec = {"issue": iss, "nAB": nAB, "shape": f"{s}单", "prize": pr}
    for name, fs in (("W", w), ("D0_400", d4 and d4["faces"]), ("D0_800", d8 and d8["faces"])):
        if not fs:
            rec[name] = None
            continue
        c, pay, h = score(fs, res, pr)
        rec[name] = (c, pay, h)
    out.append(rec)
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)


def summ(rs, a, b):
    rs = [r for r in rs if r[a] and r[b]]
    diff = [(r[a][1] - r[a][0]) - (r[b][1] - r[b][0]) for r in rs]
    rng = random.Random(7)
    boots = sorted(sum(diff[rng.randrange(len(diff))] for _ in diff) for _ in range(4000))
    na = sum(r[a][1] - r[a][0] for r in rs)
    nb = sum(r[b][1] - r[b][0] for r in rs)
    print(
        f"  n={len(rs)} {a} 净 {na:+.0f} 中 {sum(r[a][2] for r in rs)} "
        f"投 {sum(r[a][0] for r in rs)} | {b} 净 {nb:+.0f} 中 {sum(r[b][2] for r in rs)} "
        f"投 {sum(r[b][0] for r in rs)} | 配对差 {sum(diff):+.0f} "
        f"CI[{boots[99]:+.0f},{boots[3899]:+.0f}] "
        f"P(>0)={sum(1 for x in boots if x > 0) / 4000:.2f}"
    )


print("issues", len(out), out[0]["issue"], "→", out[-1]["issue"])
for lab, sel in (
    ("全部", out),
    ("26134 起", [r for r in out if r["issue"] >= "26134"]),
    ("冷板 nAB≤2", [r for r in out if r["nAB"] <= 2]),
    ("冷板 26134 起", [r for r in out if r["nAB"] <= 2 and r["issue"] >= "26134"]),
    ("非冷板", [r for r in out if r["nAB"] > 2]),
):
    print(lab)
    summ(sel, "D0_400", "W")
    summ(sel, "D0_800", "W")
for r in out:
    if r["issue"] >= "26134":
        print(
            r["issue"],
            r["shape"],
            "nAB",
            r["nAB"],
            "W",
            r["W"],
            "D0_400",
            r["D0_400"],
            "D0_800",
            r["D0_800"],
        )
