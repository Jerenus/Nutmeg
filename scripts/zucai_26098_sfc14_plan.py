"""胜负彩/任九 26098 组合优化（禁嘴算,Phase5）.

信念来自 .nutmeg-data/zucai/26098-reads.json(14场并行深研→判决表落位).
脚本只做确定性算术:按判决表允许的表达级别(单/双/全包)枚举尺寸向量,
在注数帽内最大化 P14/P9,并给期望断腿数.判断永不烤进脚本.
"""
import json
from itertools import product, combinations
from pathlib import Path

ROOT = Path(__file__).parents[1]
READS = json.loads((ROOT/".nutmeg-data/zucai/26098-reads.json").read_text())
B = {r["match_no"]: r["belief"] for r in READS}
SYM = {"home":"3","draw":"1","away":"0"}

# 判决表允许级别: match_no -> [(size, faces)] 按压缩优先序(最后一项=处方级)
LEVELS = {
 1:  [("3",),("3","1")],                 # conf4零旗 单3 / 保险31
 13: [("3",),("3","1")],
 3:  [("0",),("0","1"),("3","1","0")],   # conf4 单0 / 双01 / 全
 4:  [("3","1"),("3","1","0")],
 7:  [("3","1"),("3","1","0")],
 8:  [("3","0"),("3","1","0")],
 12: [("3","1"),("3","1","0")],
 2:  [("3","0"),("3","1","0")],
 5:  [("0","1"),("3","1","0")],
 6:  [("1","0"),("3","1","0")],
 9:  [("3","0"),("3","1","0")],
 10: [("3","1"),("3","1","0")],
 11: [("3","1"),("3","1","0")],
 14: [("3","0"),("3","1","0")],
}
def cov(no, faces):
    inv = {"3":"home","1":"draw","0":"away"}
    return sum(B[no][inv[f]] for f in faces)

def enum_best(matches, cap_bets):
    """在注数帽内枚举各场级别,最大化 P(全中)。返回(P, alloc, bets)"""
    opts = [ [ (len(f), cov(m,f), f) for f in LEVELS[m] ] for m in matches ]
    best = None
    def dfs(i, bets, p, alloc):
        nonlocal best
        if bets > cap_bets: return
        if i == len(matches):
            if best is None or p > best[0]: best = (p, list(alloc), bets)
            return
        for size, c, f in opts[i]:
            alloc.append((matches[i], f)); dfs(i+1, bets*size, p*c, alloc); alloc.pop()
    dfs(0, 1, 1.0, [])
    return best

M14 = sorted(LEVELS)
print("=== 胜负彩 S1(14场) 各注数帽最优 ===")
for cap in (96, 144, 192, 288, 432, 576, 864, 1024):
    r = enum_best(M14, cap)
    if not r: continue
    p, alloc, bets = r
    covs = [cov(m, f) for m, f in alloc]
    ebl = sum(1-c for c in covs)
    # P(>=13)
    p13 = sum((1-c)*p/c for c in covs if c > 0)
    code = " ".join("".join(f) for _, f in alloc)
    print(f"cap{cap:>5} → {bets:>4}注 ¥{bets*2:>5} | P14={p:.4%} P(≥13)={p+p13:.3%} | 期望断腿={ebl:.2f}")
    print(f"        code: {code}")

print("\n=== 任九 R9(选9) — 固定保留{1,3,13},枚举其余6席 ===")
rest = [m for m in M14 if m not in (1,3,13)]
for cap in (128, 192, 256, 324, 432, 648):
    best = None
    for keep6 in combinations(rest, 6):
        ms = [1,3,13] + list(keep6)
        r = enum_best(ms, cap)
        if r and (best is None or r[0] > best[0][0]):
            best = (r, ms)
    (p, alloc, bets), ms = best
    covs = [cov(m,f) for m,f in alloc]
    ebl = sum(1-c for c in covs)
    drop = [m for m in M14 if m not in ms]
    code = " ".join(f"{m}:{''.join(f)}" for m, f in sorted(alloc))
    print(f"cap{cap:>4} → {bets:>3}注 ¥{bets*2:>4} | P9={p:.3%} | 期望断腿={ebl:.2f} | 丢{drop}")
    print(f"        {code}")
