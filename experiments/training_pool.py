#!/usr/bin/env python
"""样本养料：预登记实验的窗前历史样本（训练 / 探索用，永不进判决）。

每个按语料结账的实验，把语料里窗口开始前的行交给**同一个**结账适配器（选样逻辑不复制），
按当时的前瞻证明分档出读数：
  · proven   —— provably_prospective=True（判断时刻有不可改的记录且早于开球）
  · unproven —— None（文件声明的时刻，可改，无法证明早于开球）
  · leaked   —— False（证明晚于开球，只作反面对照）
再给两组规划数：前瞻窗口按当前速度攒到 n_min 还要多少天；若历史读数就是真效应，到 n_min 时
三种判决（证伪 / 成立 / 跨线不判）各有多大概率（与 `Falsifier.evaluate` 同口径，只看 CI 两端），
以及要多少样本才有 80% 的把握出非跨线判决（CI 半宽 ∝ 1/√n 外推）。

历史样本只能做三件事：估计效应量与方差、检验适配器能跑通、排期。它们是形成这些假设的同一批
数据，所以不能当证据（RSI：重放结果进不了判决）。

用法：python experiments/training_pool.py [--corpus …] [--samples …] [--today 日期] [--json 输出]
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nutmeg.decision import rsi_samples  # noqa: E402
from nutmeg.decision.rsi_grading import PROSPECTIVE_ADAPTERS  # noqa: E402

EXPERIMENTS = ("F5", "F9", "F10", "F11", "F13", "F14", "F15", "K1")
TIERS = {"proven": True, "unproven": None, "leaked": False}
_FACES = {"3": "home", "1": "draw", "0": "away"}


def _registry(exp: str) -> dict:
    with open(os.path.join(ROOT, "experiments", "registry", f"{exp}.json"), encoding="utf-8") as f:
        return json.load(f)


def _reading(result) -> dict:
    return {"n": result.n_cum, "value_pp": round(result.metric_value_pp, 2),
            "ci": [round(result.ci_low_pp, 2), round(result.ci_high_pp, 2)]}


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def power(reading: dict, falsifier: dict) -> dict | None:
    """历史点估计若为真：到 n_min 时三种判决的概率，与 80% 出非跨线判决所需的 n。"""
    n, (lo, hi), mu = reading["n"], reading["ci"], reading["value_pp"]
    if n < 10 or hi <= lo:
        return None
    sd_row = (hi - lo) / 2 / 1.96 * math.sqrt(n)  # 每行的标准差（pp）
    se = sd_row / math.sqrt(falsifier["n_min"])
    t = falsifier["threshold_pp"]
    upper_below = _phi((t - 1.96 * se - mu) / se)      # CI 上界 < t
    lower_above = 1 - _phi((t + 1.96 * se - mu) / se)  # CI 下界 > t
    if falsifier["direction"] == "lt_means_falsified":
        falsified, survived = upper_below, lower_above
    else:
        falsified, survived = lower_above, upper_below
    gap = abs(mu - t)
    return {"p_falsified": round(falsified, 2), "p_survived": round(survived, 2),
            "p_inconclusive": round(1 - falsified - survived, 2),
            "n_decisive_80": math.ceil(((1.96 + 0.84) * sd_row / gap) ** 2) if gap else None}


def call_proxy_rows(rows: list[dict], before: str) -> list[dict]:
    """F14 的窗前代理：stance 契约（09-23）之前，足彩判读文件的 `call`（处方面，如 3 / 31 / 10）
    就是当时的结构表态。改写成 stance 标签交给 F14 适配器；全包（310）与文字表态不算。
    `call` 来自可改的判读文件，前瞻性只是声明，一律记 unproven。"""
    out = []
    for r in rows:
        call = str(r.get("call") or "")
        if r.get("src") != "zucai" or str(r.get("date") or "") >= before:
            continue
        faces_ok = all(c in _FACES for c in call) and len(set(call)) == len(call)
        if not (1 <= len(call) <= 2) or not faces_ok:
            continue
        labels = {**(r.get("labels") or {}),
                  "stance_structure": "single" if len(call) == 1 else "double",
                  "stance_face": call[0], "stance_cover": call[1] if len(call) == 2 else ""}
        out.append({**r, "labels": labels, "provably_prospective": None})
    return out


def prediction_proxy_rows(rows: list[dict], stances: list[dict], *,
                          forced: bool | None = None) -> list[dict]:
    """F14 的另一份窗前代理：内核预测账里的单场面集承诺（`experiments/prediction_stances.py`
    转录）。登记时刻是内核写的，早于开球即 proven；赛果与市场覆盖仍取语料同一行。
    `forced`：None 全收，False 去掉 26131 那期强制表态，True 只要强制表态。"""
    by_key = {r.get("key"): r for r in rows}
    out = []
    for s in stances:
        r = by_key.get(s["key"])
        if r is None or (forced is not None and s["forced"] is not forced):
            continue
        faces = s["faces"]
        labels = {**(r.get("labels") or {}), "stance_structure": s["structure"],
                  "stance_face": faces[0], "stance_cover": faces[1] if len(faces) == 2 else ""}
        out.append({**r, "labels": labels, "provably_prospective": True if s["proven"] else None})
    return out


def inventory(rows: list[dict], ledger: dict, today: str,
              stances: list[dict] | None = None) -> dict:
    out: dict[str, dict] = {}
    for exp in EXPERIMENTS:
        doc = _registry(exp)
        window, falsifier = doc["window"], doc["falsifier"]
        start = window["date_from"]
        adapter = PROSPECTIVE_ADAPTERS[exp]
        history = [r for r in rows if r.get("date") and str(r["date"]) < start]
        entry: dict = {"window_from": start, "n_min": falsifier["n_min"],
                       "threshold_pp": falsifier["threshold_pp"], "bound": falsifier["bound"],
                       "direction": falsifier["direction"], "history": {}}
        everything = adapter(history, window={"date_from": ""})
        entry["history"]["all"] = _reading(everything)
        by_key = {r.get("key"): r for r in history}
        days = sorted({str(by_key[k]["date"]) for k in everything.selected_keys if k in by_key})
        entry["history_days"] = [days[0], days[-1], len(days)] if days else None
        entry["history_per_match_day"] = round(everything.n_cum / len(days), 1) if days else 0.0
        for tier, flag in TIERS.items():
            subset = [r for r in history if r.get("provably_prospective") is flag]
            entry["history"][tier] = _reading(adapter(subset, window={"date_from": ""}))
        if exp == "F14":
            proxy = call_proxy_rows(rows, before="2026-09-23")
            proxy_result = adapter(proxy, window={"date_from": ""})
            entry["history"]["zucai_call_proxy"] = _reading(proxy_result)
            if stances:
                for name, forced in (("prediction_proxy", None),
                                     ("prediction_proxy_unforced", False)):
                    proxy = [r for r in prediction_proxy_rows(rows, stances, forced=forced)
                             if r["provably_prospective"] is True]
                    entry["history"][name] = _reading(adapter(proxy, window={"date_from": ""}))
        scratch = copy.deepcopy(ledger)
        current, _ = rsi_samples.grade(scratch, exp, rows, adapter, window=window, at=today)
        days = max(1, (date.fromisoformat(today) - date.fromisoformat(start)).days)
        rate = current.n_cum / days
        remaining = falsifier["n_min"] - current.n_cum
        if remaining <= 0:
            to_go = 0
        else:
            to_go = math.ceil(remaining / rate) if rate > 0 else None
        entry["prospective"] = {**_reading(current), "per_day": round(rate, 2),
                                "days_to_n_min": to_go}
        entry["power_if_history_true"] = power(entry["history"]["all"], falsifier)
        if "prediction_proxy" in entry["history"]:
            entry["power_if_prediction_proxy_true"] = power(
                entry["history"]["prediction_proxy"], falsifier)
        out[exp] = entry
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=os.path.join(ROOT, "experiments", "corpus-v2.json"))
    ap.add_argument("--samples", default=os.path.join(ROOT, "experiments", "rsi-samples.json"))
    ap.add_argument("--stances",
                    default=os.path.join(ROOT, "experiments", "prediction-stances.json"))
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    with open(args.corpus, encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    stances = None
    if os.path.exists(args.stances):
        with open(args.stances, encoding="utf-8") as f:
            stances = json.load(f)["rows"]
    result = inventory(rows, rsi_samples.load(args.samples), args.today, stances)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    for exp, e in result.items():
        h, p = e["history"], e["prospective"]
        tiers = "  ".join(
            f"{k} n={v['n']} {v['value_pp']:+.1f} [{v['ci'][0]:+.1f},{v['ci'][1]:+.1f}]"
            for k, v in h.items())
        print(f"{exp}（窗口 {e['window_from']} 起，n_min {e['n_min']}，"
              f"门槛 {e['threshold_pp']:+}）")
        print(f"  窗前：{tiers}")
        print(f"  历史日程：{e['history_days']}  每比赛日 {e['history_per_match_day']} 条")
        print(f"  前瞻：n={p['n']} {p['value_pp']:+.1f} [{p['ci'][0]:+.1f},{p['ci'][1]:+.1f}]  "
              f"{p['per_day']}/天  到 n_min 约 {p['days_to_n_min']} 天")
        for label, field in (("历史效应", "power_if_history_true"),
                             ("预测账效应", "power_if_prediction_proxy_true")):
            w = e.get(field)
            if w:
                print(f"  {label}为真时，到 n_min：证伪 {w['p_falsified']} / "
                      f"成立 {w['p_survived']} / 跨线 {w['p_inconclusive']}；"
                      f"80% 出判决需 n≈{w['n_decisive_80']}")


if __name__ == "__main__":
    main()
