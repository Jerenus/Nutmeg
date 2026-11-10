# ruff: noqa: E501
"""因子挖掘第 5 轮：把内部池 B 里露头的价格/场景主题拿到独立样本上复核（2026-11-10）。只读。

两份独立样本：
  FD  football-data.co.uk 12 季 22 级联赛（1516–2627），残差对 Pinnacle 收盘（缺则 Avg 收盘）；
      前八季开发（1516–2223）、后四季验证（2324–2627）。
  JC  jc-history × titan 收盘 sharp（2025-08-01 → 2026-05-17，早于 decision-samples-v1 窗口，与内部池不重叠）。
      没有联赛字段：用样本表里「队→国内联赛」映射，两队都认得且联赛不同＝跨联赛（欧战/洲际杯代理）。

每个格：n、热门/平/弱方残差（实开 − 收盘 P）、相对其余行的超额、z（零假设方差 p(1−p)）、开发/验证两段。
用法：uv run python experiments/prescreen/2026-11-10-factor-mining-external.py <football-data 根目录> [--json-out 路径]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".nutmeg-data"
TARGETS = ("fav", "draw", "dog")
TOP = {"E0", "D1", "I1", "SP1", "F1"}
SECOND = {"E1", "E2", "E3", "EC", "D2", "I2", "SP2", "F2", "SC1", "SC2", "SC3"}
_FACE = {"胜": "H", "平": "D", "负": "A"}


def num(x):
    try:
        v = float(x)
        return v if v > 1 else None
    except (TypeError, ValueError):
        return None


def trio(r, prefix):
    o = [num(r.get(prefix + s)) for s in "HDA"]
    return o if all(o) else None


def fair(o):
    s = sum(1 / x for x in o)
    return [1 / x / s for x in o]


def band(p):
    return "A≥80" if p >= .8 else "B65–79" if p >= .65 else "b57–64" if p >= .57 else "C45–56" if p >= .45 else "D<45"


def base_row(p, ftr, d: date) -> dict | None:
    """p＝[主,平,客] 去水收盘。→ 行（热门/平/弱方的 P 与命中 + 通用价格因子）。"""
    if p[0] == p[2]:
        return None
    fi, di = (0, 2) if p[0] > p[2] else (2, 0)
    res = "HDA".index(ftr)
    return dict(
        p={"fav": p[fi], "draw": p[1], "dog": p[di]},
        hit={"fav": res == fi, "draw": res == 1, "dog": res == di},
        date=d, fi=fi, cat={
            "band": band(p[fi]), "fav_side": "home" if fi == 0 else "away",
            "weekday": "midweek" if d.weekday() in (1, 2, 3) else "weekend",
        }, num={"p_draw": p[1], "p_dog": p[di]})


def load_fd(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.glob("*/*.csv")):
        season, lg = path.parent.name, path.stem
        games = []
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("FTR") not in ("H", "D", "A") or not (r.get("Date") or "").strip():
                    continue
                close = trio(r, "PSC") or trio(r, "AvgC") or trio(r, "B365C") or trio(r, "PS") or trio(r, "B365")
                if not close:
                    continue
                ds = r["Date"].strip()
                try:
                    d = datetime.strptime(ds, "%d/%m/%Y" if len(ds.split("/")[-1]) == 4 else "%d/%m/%y").date()
                except ValueError:
                    continue
                row = base_row(fair(close), r["FTR"], d)
                if not row:
                    continue
                fi = row["fi"]
                row["split"] = "dev" if season <= "2223" else "val"
                row["cat"]["tier"] = "top5" if lg in TOP else "second" if lg in SECOND else "other_top"
                op = trio(r, "PS") or trio(r, "Avg") or trio(r, "B365")
                if op and (trio(r, "PSC") or trio(r, "AvgC")):
                    row["num"]["open_to_close_fav"] = (fair(op)[fi] - row["p"]["fav"]) * -100
                mx, av = trio(r, "MaxC"), trio(r, "AvgC")
                if mx and av:
                    row["num"]["dispersion_fav"] = (mx[fi] / av[fi] - 1) * 100
                ps, avc = trio(r, "PSC"), trio(r, "AvgC")
                if ps and avc:
                    row["num"]["sharp_minus_soft_fav"] = (fair(ps)[fi] - fair(avc)[fi]) * 100
                    row["num"]["sharp_minus_soft_draw"] = (fair(ps)[1] - fair(avc)[1]) * 100
                ou = next(((num(r.get(a + ">2.5")), num(r.get(a + "<2.5"))) for a in ("PC", "AvgC", "P", "Avg", "BbAv")
                           if num(r.get(a + ">2.5")) and num(r.get(a + "<2.5"))), None)
                if ou:
                    row["num"]["p_under25"] = (1 / ou[1]) / (1 / ou[0] + 1 / ou[1])
                games.append(row)
        games.sort(key=lambda g: g["date"])
        for i, gm in enumerate(games):          # 赛季阶段：按该联赛该季场次序的分位
            q = i / max(len(games) - 1, 1)
            gm["cat"]["phase"] = "first10%" if q < .10 else "last10%" if q > .90 else "middle"
        rows += games
    return rows


def team_league_map() -> dict[str, str]:
    votes: dict[str, Counter] = defaultdict(Counter)
    skip = ("欧冠", "欧罗巴", "欧协联", "欧国联", "国际赛", "nations", "杯", "cup", "copa", "亚冠", "世预", "友谊", "亚运")
    for line in (ROOT / "experiments" / "decision-samples-v1.jsonl").read_text(encoding="utf-8").splitlines():
        x = json.loads(line)
        comp = x.get("competition")
        if not comp or any(k in comp.lower() for k in skip):
            continue
        for side in ("home", "away"):
            if x.get(side):
                votes[x[side]][comp] += 1
    return {t: c.most_common(1)[0][0] for t, c in votes.items() if c.most_common(1)[0][1] >= 2}


def load_jc(until: str = "2026-05-18") -> list[dict]:
    hist = json.loads((DATA / "jczq" / "jc-history.json").read_text(encoding="utf-8"))
    tl = team_league_map()
    rows = []
    for day in sorted(hist):
        if day >= until:
            continue
        p = DATA / "jczq" / "daily" / day / "closing_odds.json"
        if not p.exists():
            continue
        cl = json.loads(p.read_text(encoding="utf-8"))
        for code, m in hist[day].items():
            o = ((m.get("sp") or {}).get("had") or {}).get("outcome")
            sharp = (cl.get(code) or {}).get("sharp") or {}
            f = sharp.get("fair_probability")
            if o not in _FACE or not f:
                continue
            row = base_row([f["home"], f["draw"], f["away"]], _FACE[o], date.fromisoformat(day))
            if not row:
                continue
            fi = row["fi"]
            side = "home" if fi == 0 else "away"
            row["split"] = "dev" if day < "2026-01-01" else "val"
            row["cat"]["weekday"] = "midweek" if code[:2] in ("周二", "周三", "周四") else "weekend"
            op = sharp.get("opening_odds")
            if op and all(op.get(k, 0) > 1 for k in ("home", "draw", "away")):
                fo = fair([op["home"], op["draw"], op["away"]])
                row["num"]["open_to_close_fav"] = (row["p"]["fav"] - fo[fi]) * 100
                row["num"]["open_to_close_draw"] = (row["p"]["draw"] - fo[1]) * 100
            pb = (sharp.get("per_book_odds") or {}).get(side)
            if pb and len(pb) >= 5:
                row["num"]["dispersion_fav"] = float(np.std(pb) / np.mean(pb) * 100)
            ts = (cl.get(code) or {}).get("updated_at_max")
            if ts:
                h = (datetime.fromisoformat(ts).hour + 8) % 24 if ts.endswith("Z") else datetime.fromisoformat(ts).hour
                row["cat"]["hour"] = "night_0_8" if h < 8 else "day_8_20" if h < 20 else "eve_20_24"
            lh, la = tl.get(m.get("home")), tl.get(m.get("away"))
            if lh and la:
                row["cat"]["cross_league"] = "cross(欧战代理)" if lh != la else "same_league"
            hh = (m.get("sp") or {}).get("hhad") or {}
            if hh.get("line") is not None:
                ln = float(hh["line"])
                row["cat"]["hhad_line"] = "fav让≥2" if abs(ln) >= 2 else "fav让1" if (ln < 0) == (fi == 0) else "fav受让"
            rows.append(row)
    return rows


def terciles(rows: list[dict]) -> None:
    for name in sorted({k for r in rows for k in r["num"]}):
        vals = np.array([r["num"][name] for r in rows if r["num"].get(name) is not None], float)
        if len(vals) < 300:
            continue
        lo, hi = np.quantile(vals, [1 / 3, 2 / 3])
        for r in rows:
            v = r["num"].get(name)
            if v is not None:
                r["cat"][name] = f"low(<{lo:.2f})" if v < lo else f"high(>{hi:.2f})" if v > hi else "mid"


def stats(rows: list[dict], mask: np.ndarray, t: str) -> dict | None:
    if mask.sum() < 30 or (~mask).sum() < 30:
        return None
    res = np.array([r["hit"][t] - r["p"][t] for r in rows])
    v0 = np.array([r["p"][t] * (1 - r["p"][t]) for r in rows])
    a, b = res[mask], res[~mask]
    se = math.sqrt(v0[mask].mean() / len(a) + v0[~mask].mean() / len(b))
    se1 = math.sqrt(v0[mask].mean() / len(a))
    return dict(n=int(mask.sum()), resid_pp=round(a.mean() * 100, 2), resid_z=round(a.mean() / se1, 2),
                excess_pp=round((a.mean() - b.mean()) * 100, 2), z=round((a.mean() - b.mean()) / se, 2))


def run(rows: list[dict], label: str, pairs: list[tuple[tuple, tuple]]) -> list[dict]:
    terciles(rows)
    split = np.array([r["split"] for r in rows])
    levels: dict[tuple, np.ndarray] = {}
    for i, r in enumerate(rows):
        for k, v in r["cat"].items():
            levels.setdefault((k, v), np.zeros(len(rows), bool))[i] = True
    cells = [((k,), m) for k, m in sorted(levels.items())]
    for a, b in pairs:
        for ka, ma in levels.items():
            for kb, mb in levels.items():
                if ka[0] == a[0] and kb[0] == b[0] and (a[1] is None or ka[1].startswith(a[1])) \
                        and (b[1] is None or kb[1].startswith(b[1])):
                    cells.append(((ka, kb), ma & mb))
    base = {t: round(float(np.mean([r["hit"][t] - r["p"][t] for r in rows])) * 100, 2) for t in TARGETS}
    print(f"\n## {label}：n={len(rows)}，池残差 {base}")
    print("| 格 | 面 | n | 残差 (z) | 超额 | z | 开发段超额 (n,z) | 验证段超额 (n,z) | 两段同号且各 |z|≥2 |")
    print("|---|---|---|---|---|---|---|---|---|")
    out = []
    for keys, m in cells:
        for t in TARGETS:
            s = stats(rows, m, t)
            if not s:
                continue
            parts = {}
            for nm in ("dev", "val"):
                sel = split == nm
                sub = [r for r, f in zip(rows, sel, strict=True) if f]
                parts[nm] = stats(sub, m[sel], t) if sel.sum() else None
            d_, v_ = parts["dev"], parts["val"]
            holds = bool(d_ and v_ and d_["excess_pp"] * v_["excess_pp"] > 0 and abs(d_["z"]) >= 2 and abs(v_["z"]) >= 2)
            rec = dict(sample=label, cell=" & ".join(f"{k}={v}" for k, v in keys), target=t, **s, dev=d_, val=v_, holds=holds)
            out.append(rec)
            if abs(s["z"]) >= 2 or holds:
                def f(x):
                    return f"{x['excess_pp']:+.1f} (n{x['n']}, z{x['z']:+.1f})" if x else "—"
                print(f"| {rec['cell']} | {t} | {s['n']} | {s['resid_pp']:+.1f} ({s['resid_z']:+.1f}) | {s['excess_pp']:+.1f} | "
                      f"{s['z']:+.2f} | {f(d_)} | {f(v_)} | {'✓' if holds else ''} |")
    n_sig = sum(abs(r["z"]) >= 2 for r in out)
    print(f"\n共 {len(out)} 个检验，|z|≥2 的 {n_sig} 个（纯噪声期望 ≈{len(out) * .0455:.0f}），两段都站住 {sum(r['holds'] for r in out)} 个")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fd_root")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    fd_pairs = [(("band", None), ("fav_side", None)), (("band", None), ("weekday", None)),
                (("band", None), ("p_under25", None)), (("band", None), ("open_to_close_fav", None)),
                (("band", None), ("dispersion_fav", None)), (("band", None), ("phase", None)),
                (("band", None), ("tier", None)), (("band", None), ("sharp_minus_soft_fav", None)),
                (("p_draw", None), ("p_under25", None)), (("p_draw", None), ("weekday", None)),
                (("tier", None), ("weekday", None)), (("phase", None), ("tier", None))]
    jc_pairs = [(("band", None), ("fav_side", None)), (("band", None), ("weekday", None)),
                (("band", None), ("hour", None)), (("band", None), ("cross_league", None)),
                (("band", None), ("open_to_close_fav", None)), (("band", None), ("dispersion_fav", None)),
                (("p_draw", None), ("weekday", None)), (("p_draw", None), ("hour", None)),
                (("cross_league", None), ("weekday", None)), (("band", None), ("hhad_line", None))]
    out = run(load_fd(Path(args.fd_root)), "FD football-data 12 季", fd_pairs)
    out += run(load_jc(), "JC jc-history 2025-08→2026-05-17", jc_pairs)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
