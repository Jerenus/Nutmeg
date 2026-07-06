"""MD3 2026-06-24 六场：从国际去水 fair 反推 Dixon-Coles 比分矩阵。
确定性算术支撑（禁嘴算）：模态比分 / 净胜分布 / 让球 cover 概率 / 大小球。
拟合 (lambda_home, lambda_away, rho) 到 fair 1X2 + over(line)。"""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# fair from bold_odds.json (去水) + sporttery total line + hhad line(主队视角)
M = {
 "049 瑞士-加拿大":   dict(h=0.410116, d=0.303216, a=0.286668, ou=2.5, over=0.469188, hcap=-1, line="瑞士-1"),
 "050 波黑-卡塔尔":   dict(h=0.670713, d=0.195714, a=0.133573, ou=2.5, over=0.604708, hcap=-1, line="波黑-1"),
 "051 苏格兰-巴西":   dict(h=0.115271, d=0.191799, a=0.69293,  ou=2.5, over=0.508434, hcap=+1, line="苏格兰+1/巴西-1"),
 "052 摩洛哥-海地":   dict(h=0.799834, d=0.139565, a=0.060601, ou=2.5, over=0.60824,  hcap=-2, line="摩洛哥-2"),
 "053 南非-韩国":     dict(h=0.187095, d=0.253181, a=0.559724, ou=2.5, over=0.46591,  hcap=+1, line="南非+1/韩国-1"),
 "054 捷克-墨西哥":   dict(h=0.255982, d=0.254281, a=0.489737, ou=2.25,over=0.52646,  hcap=+1, line="捷克+1/墨西哥-1"),
}
MAXG = 12
idx = np.arange(MAXG+1)

def dc_matrix(lh, la, rho):
    ph = poisson.pmf(idx, lh)
    pa = poisson.pmf(idx, la)
    mat = np.outer(ph, pa)
    # Dixon-Coles low-score 修正
    mat[0,0] *= 1 - lh*la*rho
    mat[0,1] *= 1 + lh*rho
    mat[1,0] *= 1 + la*rho
    mat[1,1] *= 1 - rho
    mat = np.clip(mat, 1e-15, None)
    return mat/mat.sum()

def probs(mat, line):
    H = np.tril(mat, -1).sum()   # home>away
    D = np.trace(mat)
    A = np.triu(mat, 1).sum()    # away>home
    tot = np.add.outer(idx, idx)
    over = mat[tot > line].sum()
    return H, D, A, over

def fit(m):
    def loss(x):
        lh, la, rho = x
        if not (0.1<lh<4 and 0.1<la<4 and -0.2<rho<0.1): return 1e6
        H,D,A,ov = probs(dc_matrix(lh,la,rho), m["ou"])
        # 1X2 权重高，over 权重中
        return 4*((H-m["h"])**2+(D-m["d"])**2+(A-m["a"])**2) + 1.5*(ov-m["over"])**2
    best=None
    for lh0 in (0.6,1.0,1.4,1.8,2.2):
        for la0 in (0.6,1.0,1.4,1.8,2.2):
            r=minimize(loss,[lh0,la0,-0.05],method="Nelder-Mead",
                       options=dict(xatol=1e-4,fatol=1e-10,maxiter=4000))
            if best is None or r.fun<best.fun: best=r
    return best.x

def margin_dist(mat):
    # 主队净胜分布
    d={}
    for i in range(MAXG+1):
        for j in range(MAXG+1):
            d[i-j]=d.get(i-j,0)+mat[i,j]
    return d

print(f"{'match':16} {'lh':>5} {'la':>5} {'rho':>6} | {'H':>5}{'D':>5}{'A':>5}{'ov':>5} | top scores")
print("-"*100)
RES={}
for name,m in M.items():
    lh,la,rho=fit(m)
    mat=dc_matrix(lh,la,rho)
    H,D,A,ov=probs(mat,m["ou"])
    # top 6 比分
    flat=[((i,j),mat[i,j]) for i in range(6) for j in range(6)]
    flat.sort(key=lambda x:-x[1])
    tops=" ".join(f"{i}-{j}:{p*100:.0f}%" for (i,j),p in flat[:6])
    print(f"{name:16} {lh:5.2f} {la:5.2f} {rho:6.3f} | {H*100:4.0f}%{D*100:4.0f}%{A*100:4.0f}%{ov*100:4.0f}% | {tops}")
    RES[name]=dict(lh=lh,la=la,rho=rho,mat=mat,margin=margin_dist(mat))

print("\n=== 净胜分布 + 让球 cover (主队视角净胜) ===")
for name,m in M.items():
    md=RES[name]["margin"]
    g=lambda k:md.get(k,0)*100
    # 主队净胜: ...-2 -1 0(平) +1 +2 +3+
    h3=sum(v for k,v in md.items() if k>=3)*100
    a2=sum(v for k,v in md.items() if k<=-2)*100
    print(f"\n{name}  线[{m['line']}]")
    print(f"  主净胜: 客胜2+ {a2:4.1f} | 客胜1 {g(-1):4.1f} | 平 {g(0):4.1f} | 主胜1 {g(1):4.1f} | 主胜2 {g(2):4.1f} | 主胜3+ {h3:4.1f}")
    # 让球解读
    hc=m["hcap"]
    if hc==-1:  # 主-1
        rang={"让胜(主净2+)":sum(v for k,v in md.items() if k>=2),
              "让平(主净恰1)":md.get(1,0),
              "让负(主平或负)":sum(v for k,v in md.items() if k<=0)}
    elif hc==-2: # 主-2
        rang={"让胜(主净3+)":sum(v for k,v in md.items() if k>=3),
              "让平(主净恰2)":md.get(2,0),
              "受让(主净≤1)":sum(v for k,v in md.items() if k<=1)}
    elif hc==+1: # 主+1 (客-1)
        rang={"主+1(主平/胜)":sum(v for k,v in md.items() if k>=0),
              "让平(客净恰1)":md.get(-1,0),
              "客-1(客净2+)":sum(v for k,v in md.items() if k<=-2)}
    print("  让球: "+" | ".join(f"{k} {v*100:.1f}" for k,v in rang.items()))
