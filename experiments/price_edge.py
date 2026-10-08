#!/usr/bin/env python
"""价格边验证（假期迭代 #2，2026-10-01）：体彩竞彩 had 价 vs titan007 终盘 sharp_fair vs 90' 赛果。

只用磁盘上已有的：`experiments/corpus-v2.json`（jczq 行：closing.sharp_fair + actual）
× `.nutmeg-data/jczq/daily/<日>/sporttery_markets.json`（体彩 had 价）。
全部平注 1 元、按体彩赔率结算。

    uv run python experiments/price_edge.py            # 四张总表
    uv run python experiments/price_edge.py --band 0.7 0.8   # 某个热门带的稳健性切分

⛔这是描述性回看，不是前瞻实验：桶是事后划的，结论只能用来**登记**一个前瞻实验（F 系列），
不能直接变成规则。多重比较：表 1 有 9 桶、表 3 有 5 桶，CI 不含 0 的桶要再看 z 是否过得了桶数校正。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nutmeg.data.prices import devig  # noqa: E402
from nutmeg.ontology.ingest.sporttery import parse_sporttery_markets  # noqa: E402

FACES = ("home", "draw", "away")
CODE = {"home": "3", "draw": "1", "away": "0"}
random.seed(20261001)
_boards: dict[str, dict] = {}


def load_rows(corpus: Path) -> list[dict]:
    rows = json.loads(corpus.read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if r.get("src") == "jczq" and r.get("closing")
            and r.get("actual") in ("3", "1", "0")]


def board(day: str, data_dir: Path) -> dict:
    if day not in _boards:
        path = data_dir / "jczq" / "daily" / day / "sporttery_markets.json"
        table: dict[str, dict] = {}
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            for m in parse_sporttery_markets(doc, business_date=day):
                had = {q.outcome_key: q.decimal_odds for q in m.quotes if q.market_kind == "had"}
                if len(had) == 3:
                    table[m.match_no] = {"had": had, "league": m.league_name}
        _boards[day] = table
    return _boards[day]


def boot_ci(values, n=2000):
    if not values:
        return float("nan"), float("nan")
    k = len(values)
    samples = sorted(sum(values[random.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return samples[int(0.025 * n)], samples[int(0.975 * n)]


def join(corpus: Path, data_dir: Path) -> list[dict]:
    out = []
    for r in load_rows(corpus):
        day, code = r["key"][:10], r["key"][11:]
        px = board(day, data_dir).get(code)
        sharp = r["closing"].get("sharp_fair") or r["closing"].get("all_fair")
        if not px or not sharp:
            continue
        out.append({"day": day, "code": code, "odds": px["had"], "imp": devig(px["had"]),
                    "sharp": sharp, "actual": r["actual"], "league": px["league"],
                    "books": r["closing"].get("sharp_books") or 0})
    return out


def _row(label, xs):
    """xs = [(hit, sharp_p, roi)]"""
    if not xs:
        return
    n = len(xs)
    hit = sum(x[0] for x in xs) / n
    p = sum(x[1] for x in xs) / n
    roi = sum(x[2] for x in xs) / n
    lo, hi = boot_ci([x[2] for x in xs])
    dlo, dhi = boot_ci([x[0] - x[1] for x in xs])
    print(f"| {label} | {n} | {hit*100:.1f}% | {p*100:.1f}% | {(hit-p)*100:+.1f} "
          f"[{dlo*100:+.1f},{dhi*100:+.1f}] | {roi*100:+.1f}% [{lo*100:+.1f},{hi*100:+.1f}] |")


def overview(joined: list[dict]) -> None:
    print(f"对上体彩价 {len(joined)} 场；{min(j['day'] for j in joined)} → "
          f"{max(j['day'] for j in joined)}，{len({j['day'] for j in joined})} 天")
    print("\n## 1. 按终盘 p 分桶（每个面一行）：体彩隐含−终盘、命中−终盘、命中−体彩隐含（pp）")
    print("| 终盘 p 桶 | n | 体彩隐含−终盘 | 命中−终盘 [CI] | 命中−体彩隐含 [CI] |")
    print("|---|---|---|---|---|")
    buckets = defaultdict(list)
    for j in joined:
        for f in FACES:
            hit = j["actual"] == CODE[f]
            buckets[min(int(j["sharp"][f] * 10), 9)].append(
                (j["imp"][f] - j["sharp"][f], hit - j["sharp"][f], hit - j["imp"][f]))
    for b in sorted(buckets):
        xs = buckets[b]
        m = [sum(x[i] for x in xs) / len(xs) * 100 for i in range(3)]
        c2 = boot_ci([x[1] for x in xs])
        c3 = boot_ci([x[2] for x in xs])
        print(f"| {b/10:.1f}–{(b+1)/10:.1f} | {len(xs)} | {m[0]:+.1f} | {m[1]:+.1f} "
              f"[{c2[0]*100:+.1f},{c2[1]*100:+.1f}] | {m[2]:+.1f} "
              f"[{c3[0]*100:+.1f},{c3[1]*100:+.1f}] |")

    print("\n## 2. 终盘隐含 EV 桶 → 实际 ROI（EV = 终盘 p × 体彩赔率 − 1）")
    print("| 隐含 EV 桶 | n | 隐含 EV 均值 | 实际 ROI [CI] |\n|---|---|---|---|")
    edges = [(-1, "< −15%"), (-0.15, "−15%…−10%"), (-0.10, "−10%…−5%"), (-0.05, "−5%…0"),
             (0, "0…+5%"), (0.05, "+5%…+10%"), (0.10, "≥ +10%")]
    ev_b = defaultdict(list)
    for j in joined:
        for f in FACES:
            ev = j["sharp"][f] * j["odds"][f] - 1
            label = next(lab for lo, lab in reversed(edges) if ev >= lo)
            ev_b[label].append((ev, (j["odds"][f] - 1) if j["actual"] == CODE[f] else -1.0))
    for _, label in edges:
        xs = ev_b.get(label, [])
        if not xs:
            continue
        lo, hi = boot_ci([x[1] for x in xs])
        print(f"| {label} | {len(xs)} | {sum(x[0] for x in xs)/len(xs)*100:+.1f}% | "
              f"{sum(x[1] for x in xs)/len(xs)*100:+.1f}% [{lo*100:+.1f}%, {hi*100:+.1f}%] |")

    print("\n## 3. 热门带（终盘最大面）：命中率 / 终盘 p / 命中−终盘 / 押热门 ROI")
    print("| 热门 p 桶 | n | 命中率 | 终盘 p | 命中−终盘 (pp) [CI] | 押热门 ROI [CI] |")
    print("|---|---|---|---|---|---|")
    fav = defaultdict(list)
    for j in joined:
        f = max(FACES, key=lambda x: j["sharp"][x])
        p = j["sharp"][f]
        key = ("<0.5" if p < 0.5 else "0.5–0.6" if p < 0.6 else "0.6–0.7" if p < 0.7
               else "0.7–0.8" if p < 0.8 else "≥0.8")
        hit = j["actual"] == CODE[f]
        fav[key].append((hit, p, (j["odds"][f] - 1) if hit else -1.0))
    for key in ("<0.5", "0.5–0.6", "0.6–0.7", "0.7–0.8", "≥0.8"):
        _row(key, fav.get(key, []))

    print("\n## 4. 汇总策略（平注、体彩赔率）")
    tot = len(joined)
    all3 = sum(((j["odds"][f] - 1) if j["actual"] == CODE[f] else -1.0)
               for j in joined for f in FACES) / (3 * tot)
    best = [((j["odds"][f] - 1) if j["actual"] == CODE[f] else -1.0)
            for j in joined for f in [max(FACES, key=lambda x: j["sharp"][x] * j["odds"][x])]]
    pos = [((j["odds"][f] - 1) if j["actual"] == CODE[f] else -1.0)
           for j in joined for f in FACES if j["sharp"][f] * j["odds"][f] > 1]
    print(f"- 三面全押（抽水基准）：ROI {all3*100:+.1f}%（{3*tot} 注）")
    lo, hi = boot_ci(best)
    print(f"- 每场只押终盘隐含 EV 最高面：ROI {sum(best)/len(best)*100:+.1f}% "
          f"[{lo*100:+.1f}%, {hi*100:+.1f}%]（n={len(best)}）")
    lo, hi = boot_ci(pos)
    print(f"- 只押隐含 EV>0 的面：ROI {sum(pos)/max(len(pos),1)*100:+.1f}% "
          f"[{lo*100:+.1f}%, {hi*100:+.1f}%]（n={len(pos)}，占 {len(pos)/(3*tot)*100:.1f}%）")
    print(f"- 终盘书商数中位 {sorted(j['books'] for j in joined)[tot//2]}")


def band_splits(joined: list[dict], lo: float, hi: float) -> None:
    sel = []
    for j in joined:
        f = max(FACES, key=lambda x: j["sharp"][x])
        if lo <= j["sharp"][f] < hi:
            hit = j["actual"] == CODE[f]
            sel.append({**j, "face": f, "p": j["sharp"][f], "hit": hit,
                        "roi": (j["odds"][f] - 1) if hit else -1.0})
    trip = lambda js: [(j["hit"], j["p"], j["roi"]) for j in js]  # noqa: E731
    print(f"## 热门带 [{lo},{hi}) 稳健性切分 n={len(sel)}")
    print("| 切分 | n | 命中率 | 终盘 p | 命中−终盘 (pp) [CI] | 押热门 ROI [CI] |")
    print("|---|---|---|---|---|---|")
    _row("全部", trip(sel))
    days = sorted({j["day"] for j in sel})
    mid = days[len(days) // 2]
    _row(f"前半（≤{mid}）", trip([j for j in sel if j["day"] <= mid]))
    _row(f"后半（>{mid}）", trip([j for j in sel if j["day"] > mid]))
    _row("热门=主队", trip([j for j in sel if j["face"] == "home"]))
    _row("热门=客队", trip([j for j in sel if j["face"] == "away"]))
    _row("终盘书商 ≥15", trip([j for j in sel if j["books"] >= 15]))
    _row("终盘书商 <15", trip([j for j in sel if j["books"] < 15]))
    leagues = Counter(j["league"] for j in sel)
    for league, _ in leagues.most_common(8):
        _row(f"联赛 {league}", trip([j for j in sel if j["league"] == league]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=ROOT / "experiments" / "corpus-v2.json")
    ap.add_argument("--data-dir", type=Path, default=ROOT / ".nutmeg-data")
    ap.add_argument("--band", nargs=2, type=float, metavar=("LO", "HI"))
    args = ap.parse_args()
    joined = join(args.corpus, args.data_dir)
    if args.band:
        band_splits(joined, *args.band)
    else:
        overview(joined)


if __name__ == "__main__":
    main()
