"""足彩奖金模型：奖金 = f(板面意外度)，给审票 V1 的「中了能拿多少」用。

动机（2026-10-01）：任九一等奖奖金与「全板按市场概率的意外度」强相关——热板人人都中、
奖金几十到几百元；冷板奖金几万。一张票**恰好在它中的那些板上拿到的奖金**远低于全局中位数
（帽内 max-P 形状 42 期中 11 次，中时奖金中位 ¥215 vs 全局中位 ¥4,098）。
用全局中位数算期望回报率会高估十倍。

模型：log(prize) = a + b·S，S = −Σ_i ln p_i(实际赛果)（非作废场求和，p 来自期次 fair）。
因 S 可加，一张票（每场允许面集合 A_i）的 E[奖金·1{中}] = e^a · Π_i Σ_{ω∈A_i} p_i(ω)^{1−b}
（未选的场 A_i = 全部三面），精确、无需枚举 3^14。

用法：
    uv run python scripts/zucai_prize_model.py            # 拟合 + 回测，不写
    uv run python scripts/zucai_prize_model.py --write    # 写 .nutmeg-data/zucai/prize-model.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

from nutmeg.gym.board import FACES, list_issues, load_zucai_issue
from nutmeg.gym.policies.zucai import best_point, frontier_legs

CHANNELS = {"renjiu": "renjiu", "shengfucai": "sfc_first"}


def surprise(issue, *, picks: int | None = None) -> float | None:
    """−Σ ln p(actual)；picks=9 时只取 9 场最热门（任九派奖主要由热门场决定）。"""
    results = (issue.results or "").split()
    if len(results) != len(issue.matches):
        return None
    terms = []
    for no, m in sorted(issue.matches.items(), key=lambda kv: int(kv[0])):
        code = results[int(no) - 1]
        if code == "*":
            continue
        face = {"3": "home", "1": "draw", "0": "away"}.get(code)
        p = float(m.fair.get(face, 0.0)) if face else 0.0
        if p <= 0:
            return None
        terms.append(-math.log(p))
    if picks:
        terms = sorted(terms)[:picks]
    return sum(terms)


def ols(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys, strict=True)]
    sd = math.sqrt(sum(r * r for r in resid) / max(1, len(xs) - 2))
    return a, b, sd


def expected_prize_hit(model: dict, allowed: dict[str, list[str]], fair: dict[str, dict]) -> float:
    """E[奖金·1{中}] = e^a Π_i Σ_{ω∈A_i} p^(1−b)；log-normal 残差用 e^{sd²/2} 校正均值。"""
    a, b, sd = model["a"], model["b"], model["resid_sd"]
    total = math.exp(a + sd * sd / 2)
    for no, probs in fair.items():
        faces = allowed.get(no) or list(FACES)
        total *= sum(float(probs[f]) ** (1 - b) for f in faces)
    return total


def fit(data_dir: Path, channel: str, *, seed: int = 7) -> dict:
    key = CHANNELS[channel]
    rows = []
    for issue_id in list_issues(data_dir):
        z = load_zucai_issue(data_dir, issue_id)
        if len(z.matches) < 14 or not z.prizes:
            continue
        prize = (z.prizes.get(key) or {}).get("stake_amount")
        if not prize or prize <= 0:            # 无人中奖的期（胜负彩 14/100）不进拟合
            continue
        s = surprise(z)
        if s is None:
            continue
        rows.append((issue_id, s, math.log(prize), prize, z))
    xs = [r[1] for r in rows]
    ys = [r[2] for r in rows]
    a, b, sd = ols(xs, ys)
    rng = random.Random(seed)
    boots = []
    for _ in range(400):
        sample = [rng.choice(rows) for _ in rows]
        boots.append(ols([r[1] for r in sample], [r[2] for r in sample])[1])
    boots.sort()
    corr = statistics.correlation(xs, ys)
    return {"channel": channel, "n": len(rows), "a": round(a, 4), "b": round(b, 4),
            "resid_sd": round(sd, 4), "corr": round(corr, 3),
            "b_ci95": [round(boots[int(0.025 * len(boots))], 3),
                       round(boots[int(0.975 * len(boots))], 3)],
            "prize_median": round(statistics.median(r[3] for r in rows), 1),
            "issues": [r[0] for r in rows], "_rows": rows}


def backtest_maxp(model: dict, rows: list, *, cap: int = 400) -> dict:
    """帽内 max-P 任九点：模型预测的期望回报 vs 实际回报（同一批期次）。"""
    pred, real, hits = [], [], 0
    for _issue_id, _s, _ly, prize, z in rows:
        pt = best_point(frontier_legs(z), channel="renjiu", cap_yuan=cap)
        if not pt:
            continue
        results = z.results.split()
        faces = {str(no): [ {"3": "home", "1": "draw", "0": "away"}[c] for c in fs]
                 for no, fs in pt["faces"].items()}
        fair = {no: m.fair for no, m in z.matches.items()}
        e_prize_hit = expected_prize_hit(model, faces, fair)
        pred.append(e_prize_hit / pt["stake_yuan"])
        hit = all(results[int(no) - 1] in fs for no, fs in pt["faces"].items())
        hits += hit
        real.append(prize / pt["stake_yuan"] if hit else 0.0)
    return {"n": len(pred), "hits": hits,
            "pred_mean_ratio": round(statistics.mean(pred), 3),
            "real_mean_ratio": round(statistics.mean(real), 3),
            "median_pred_ratio": round(statistics.median(pred), 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=".nutmeg-data")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    out = {"fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "formula": "log(prize) = a + b*S, S = -sum ln p(actual) over 14 matches; "
                      "E[prize*hit] = exp(a + sd^2/2) * prod_i sum_{w in A_i} p_i(w)^(1-b)",
           "channels": {}}
    for channel in CHANNELS:
        model = fit(data_dir, channel)
        rows = model.pop("_rows")
        line = (f"{channel}: n={model['n']} log(prize)={model['a']:+.3f}+{model['b']:.3f}·S "
                f"(b CI95 {model['b_ci95']}) corr={model['corr']} resid_sd={model['resid_sd']} "
                f"median=¥{model['prize_median']:,.0f}")
        print(line)
        if channel == "renjiu":
            bt = backtest_maxp(model, rows)
            model["backtest_maxp"] = bt
            print(f"  回测帽内 max-P：n={bt['n']} 中 {bt['hits']} · 模型期望回报率均值 "
                  f"{bt['pred_mean_ratio']} vs 实际 {bt['real_mean_ratio']}"
                  f"（预测中位 {bt['median_pred_ratio']}）")
        out["channels"][channel] = model
    if args.write:
        target = data_dir / "zucai" / "prize-model.json"
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {target}")


if __name__ == "__main__":
    main()
