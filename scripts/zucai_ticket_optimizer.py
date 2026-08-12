"""传统足彩构票优化器 —— CLAUDE.md/AGENTS.md 的 q 条「两阶段构票」的确定性算术支撑。

⚠️ 本脚本**不做任何判断**。判断（每场的面集合）由主循环按 q 条阶段①「共振定面」给出，
   本脚本只做阶段②「盖率定场」的枚举 + 期望奖金侧的全包排序。禁嘴算。

用法：
    uv run python scripts/zucai_ticket_optimizer.py 26102
    uv run python scripts/zucai_ticket_optimizer.py 26102 --rx rx.json --pick 9 --budget 3000

面集合 rx.json 形如 {"1": "310", "2": "01", "5": "3", "3": null}   (null = 该场判定为"散"，直接排除)
未提供 --rx 时读 .nutmeg-data/zucai/<issue>-rx.json；再没有则全部按全包处理并提示。

输出：
  1. 各腿盖率表（按盖率降序，标注等级）
  2. 全包场按 top1 升序（爆冷度）—— 同注数下应优先保留最冷的，见 q 条
  3. P(9/9) 前沿：注数 / 金额 / 命中率 / 回本门槛 / 全包场次 / 丢弃场次
  4. 任意两点的 EV 交叉点（单注奖金高于此值时哪一档胜出）
"""
import argparse
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
FACE_NAME = {"3": "主", "1": "平", "0": "客"}
NOTE_YUAN = 2


def load_fair(issue: str) -> dict[int, dict[str, float]]:
    """{场次号: {'3': 主fair, '1': 平fair, '0': 客fair}} —— 一律用国际去水 fair。"""
    p = ROOT / f".nutmeg-data/zucai/{issue}-dcfit.json"
    if not p.exists():
        raise SystemExit(f"缺 {p}；先跑 scripts/zucai_{issue}_dcfit.py")
    d = json.loads(p.read_text("utf-8"))
    out = {}
    for k, v in d.items():
        f = v["fair_had_euro"]
        out[int(k)] = {"3": f["home"], "1": f["draw"], "0": f["away"], "_name": v["name"]}
    return out


def load_rx(issue: str, path: str | None, matches: list[int]) -> dict[int, str | None]:
    p = Path(path) if path else ROOT / f".nutmeg-data/zucai/{issue}-rx.json"
    if not p.exists():
        print(f"⚠️ 未找到面集合 {p}，全部按全包处理（阶段①未做，结果仅供参考）")
        return {k: "310" for k in matches}
    raw = json.loads(p.read_text("utf-8"))
    return {int(k): v for k, v in raw.items()}


def cover(fair: dict, faces: str) -> float:
    return sum(fair[c] for c in dict.fromkeys(faces))


def grade(faces: str | None) -> str:
    if faces is None:
        return "排除"
    return {1: "单选", 2: "双选", 3: "全包"}[len(dict.fromkeys(faces))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("issue")
    ap.add_argument("--rx", default=None, help="面集合 JSON 路径")
    ap.add_argument("--pick", type=int, default=9, help="选几场（任九=9，胜负彩=14）")
    ap.add_argument("--budget", type=float, default=None, help="金额上限(元)，只显示不超过的档")
    ap.add_argument("--top", type=int, default=8, help="前沿显示几档")
    args = ap.parse_args()

    fair = load_fair(args.issue)
    rx = load_rx(args.issue, args.rx, sorted(fair))
    live = {k: v for k, v in rx.items() if v}
    if len(live) < args.pick:
        raise SystemExit(f"可用场次 {len(live)} < --pick {args.pick}")

    print(f"=== {args.issue} 期 · 各腿盖率（阶段①产出，本脚本不改）===")
    rows = sorted(live, key=lambda k: -cover(fair[k], live[k]))
    for k in rows:
        f, faces = fair[k], live[k]
        picks = "".join(FACE_NAME[c] for c in dict.fromkeys(faces))
        print(f"  场{k:>2} {f['_name']:<16} {grade(faces)} {picks:<6} {cover(f, faces)*100:5.1f}%"
              f"   fair {f['3']*100:4.1f}/{f['1']*100:4.1f}/{f['0']*100:4.1f}")
    excluded = sorted(k for k, v in rx.items() if not v)
    if excluded:
        print(f"  阶段①已排除（判定「散」）: {excluded}")

    fulls = [k for k in live if len(dict.fromkeys(live[k])) == 3]
    if fulls:
        print(f"\n=== 全包场按爆冷度排序（top1 越低淘汰力越强；同注数下优先保留）===")
        for k in sorted(fulls, key=lambda k: max(fair[k][c] for c in "310")):
            t1 = max(fair[k][c] for c in "310")
            face = next(c for c in "310" if fair[k][c] == t1)
            print(f"  场{k:>2} {fair[k]['_name']:<16} top1 {t1*100:5.1f}% ({FACE_NAME[face]})")

    print(f"\n=== P({args.pick}/{args.pick}) 前沿 ===")
    best: dict[int, tuple[float, tuple[int, ...]]] = {}
    for combo in itertools.combinations(sorted(live), args.pick):
        n, p = 1, 1.0
        for k in combo:
            n *= len(dict.fromkeys(live[k]))
            p *= cover(fair[k], live[k])
        if n not in best or p > best[n][0]:
            best[n] = (p, combo)
    # 同注数同命中率下，把全包换成最冷的几场（P 不变，期望奖金更高）
    fixed: dict[int, tuple[float, tuple[int, ...]]] = {}
    for n, (p, combo) in best.items():
        nf = sum(1 for k in combo if len(dict.fromkeys(live[k])) == 3)
        keep_nonfull = [k for k in combo if len(dict.fromkeys(live[k])) != 3]
        coldest = sorted(fulls, key=lambda k: max(fair[k][c] for c in "310"))[:nf]
        cand = tuple(sorted(keep_nonfull + coldest))
        if len(cand) == args.pick:
            pc = 1.0
            for k in cand:
                pc *= cover(fair[k], live[k])
            if abs(pc - p) < 1e-9:
                combo = cand
        fixed[n] = (p, combo)

    shown = []
    for n in sorted(fixed):
        amt = n * NOTE_YUAN
        if args.budget and amt > args.budget:
            continue
        p, combo = fixed[n]
        nf = sorted(k for k in combo if len(dict.fromkeys(live[k])) == 3)
        drop = sorted(set(fair) - set(combo))
        print(f"  {n:>5}注 ¥{amt:>7,.0f}  P={p*100:5.2f}%  回本门槛¥{amt/p:>8,.0f}"
              f"  全包={nf}  丢={drop}")
        shown.append((n, amt, p))
        if len(shown) >= args.top:
            break

    if len(shown) >= 2:
        print("\n=== EV 交叉点（单注奖金高于此值时，注数更多的一档胜出）===")
        for (na, ca, pa), (nb, cb, pb) in itertools.combinations(shown, 2):
            if abs(pa - pb) < 1e-9:
                continue
            x = (cb - ca) / (pb - pa)
            if x > 0:
                hi = nb if pb > pa else na
                print(f"  {na}注 vs {nb}注:  > ¥{x:>8,.0f} → 【{hi}注】")

    print("\n⚠️ 回本门槛 = 成本 ÷ 命中率，是「该期单注奖金需达到多少才不亏」，非收益承诺。")
    print("   历史参照：26093 冷门度低 ¥2,510 / 26096 极难之夜 ¥16,097。")


if __name__ == "__main__":
    main()
