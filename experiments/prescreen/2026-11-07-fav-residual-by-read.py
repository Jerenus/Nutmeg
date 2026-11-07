"""26160 复盘的两条核查（2026-11-07）。只读，不进任何决策层。

问 1：研究读「热门被高估」或「锚方 fail」时，能不能反过来押弱方？
      度量＝热门残差（热门实开−市场 p_fav），前瞻样本，自助 95% 区间。
问 2：C 档排除面开出 19/46，是不是最小面被系统低估？
      外部 football-data 收盘价，最大面 45–57% 的场，比最小面的价与实开。
用法：python experiments/prescreen/2026-11-07-fav-residual-by-read.py <12季根目录>
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path


def boot(d: list[float], n: int = 4000) -> tuple[float, float]:
    random.seed(1)
    m = sorted(sum(random.choice(d) for _ in d) / len(d) for _ in range(n))
    return m[int(.025 * n)], m[int(.975 * n)]


def residuals(rows: list[dict]) -> dict:
    out = {}
    def add(name, g):
        d = [float(x["result"]["face"] == x["derived"]["fav"]) - x["derived"]["p_fav"] for x in g]
        if d:
            lo, hi = boot(d)
            out[name] = {"n": len(d), "resid_pp": round(sum(d) / len(d) * 100, 1),
                         "ci": [round(lo * 100, 1), round(hi * 100, 1)]}
    for read in ("agree", "overpriced"):
        add(f"market_read={read}", [x for x in rows if x["research"].get("market_read") == read])
    for ai in ("pass", "fail", "symmetric_damage"):
        add(f"anchor={ai}", [x for x in rows if x["research"].get("anchor_integrity") == ai])
    return out


def min_face(root: Path) -> dict:
    n = priced = hit = 0
    for f in root.glob("*/*.csv"):
        with f.open(encoding="latin-1") as fh:
            for r in csv.DictReader(fh):
                try:
                    o = [float(r.get(k) or 0) for k in ("PSCH", "PSCD", "PSCA")]
                    if min(o) <= 1:
                        o = [float(r.get(k) or 0) for k in ("AvgCH", "AvgCD", "AvgCA")]
                except ValueError:
                    continue
                if min(o) <= 1 or r.get("FTR") not in ("H", "D", "A"):
                    continue
                s = sum(1 / x for x in o)
                p = [1 / x / s for x in o]
                if not .45 <= max(p) < .57:
                    continue
                m = p.index(min(p))
                n += 1
                priced += p[m]
                hit += "HDA".index(r["FTR"]) == m
    return {"n": n, "priced": round(priced / n, 3), "actual": round(hit / n, 3)}


def main() -> None:
    samples = Path("experiments/decision-samples-v1.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in samples.splitlines()]
    rows = [x for x in rows if (x.get("research") or {}).get("prospective")
            and (x.get("result") or {}).get("face") and (x.get("derived") or {}).get("p_fav")]
    result = {"prospective_rows": len(rows), "fav_residual": residuals(rows),
              "c_tier_min_face": min_face(Path(sys.argv[1]))}
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
