#!/usr/bin/env python
"""因子 1 —— 书商分歧度（连续量）的采集与检验。

**为什么值得单独采一遍。** 生产管线只取配置里的 6-7 家锐盘、且是「先平均赔率再去水」
（`_consensus_market`）；titan007 的 1x2d 接口每场实际给 **150+ 家**，各家之间的
**离散度**从来没被取出来过——它被平均掉了。

现有 RULEBOOK 里与它最接近的是「旗-无方向」词典里的 `盘源分歧≥3pp`：那是**体彩 vs
国际两源**的二值旗，只驱动动作（降格全包），**从未被量成概率残差**。本因子问的是
另一件事：**同一时刻 150 家书商彼此差多少**。

机制（先写死，再跑）：分歧度是**共识置信度**的度量，不是价格的函数。各家模型/敞口
不一致时，共识点估计的信息量低，真实分布比共识声称的更宽 → 三面应向均匀收缩，
即「大热该被下调、冷门与平局该被上调」。

⛔泄漏纪律：只收 ``updated_at <= kickoff`` 的报价；赛后才更新的行一律丢。
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

Z = Path(".nutmeg-data/zucai")
OUT = Z / "t7-dispersion.json"
FACES = ("home", "draw", "away")


def _devig(odds: dict[str, float]) -> dict[str, float]:
    """单家报价去水（比例法）。与仓内全局口径一致：先取倒数再归一。"""
    raw = {k: 1.0 / odds[k] for k in FACES}
    s = sum(raw.values())
    return {k: v / s for k, v in raw.items()}


def _kickoffs(issue: str) -> dict[str, datetime]:
    path = Z / f"{issue}-issue.json"
    if not path.exists():
        return {}
    out: dict[str, datetime] = {}
    for m in json.load(open(path)).get("matches", []):
        try:
            out[str(m["match_no"])] = datetime.fromisoformat(str(m["kickoff_bj"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _consensus(quotes) -> dict[str, float] | None:
    """与生产同口径：先平均赔率再去水（`_consensus_market`）。"""
    if not quotes:
        return None
    odds = {k: statistics.fmean(q[k] for q in quotes) for k in FACES}
    return _devig(odds)


def _stats(probs: list[dict[str, float]]) -> dict:
    cell = {}
    for f in FACES:
        xs = sorted(p[f] for p in probs)
        cell[f] = {
            "mean": statistics.fmean(xs),
            "sd": statistics.pstdev(xs) if len(xs) > 1 else 0.0,
            "p10": xs[max(0, int(0.10 * len(xs)) - 1)],
            "p90": xs[min(len(xs) - 1, int(0.90 * len(xs)))],
        }
    # 分歧度标量：三面 sd 之和（面内离散的总量，单位 pp）
    cell["dispersion"] = sum(cell[f]["sd"] for f in FACES)
    cell["n_books"] = len(probs)
    return cell


def _backfill_issue(issue: str) -> None:
    """把该期 match_id/fair 从 f2 观察单补进 t7-backfill，让采集仪看得见本期（26129 事故）。"""
    bf = Z / "t7-backfill.json"
    t7 = json.load(open(bf)) if bf.exists() else {}
    if issue in t7:
        return
    obs = json.loads((Z / f"{issue}-f2-observation.json").read_text("utf-8"))["observations"]
    t7[issue] = {no: {"match_id": r["match_id"], "fair": r["fair"]} for no, r in obs.items()}
    bf.write_text(json.dumps(t7, ensure_ascii=False), "utf-8")


def collect(sleep_s: float, limit: int | None, overwrite: bool = False,
            issue: str | None = None) -> None:
    from nutmeg.data.titan007 import Titan007Client, Titan007Error

    t7 = json.load(open(Z / "t7-backfill.json"))
    done = json.load(open(OUT)) if OUT.exists() else {}
    client = Titan007Client()
    fetched = failed = skipped_stale = no_kickoff = 0
    try:
        for issue, matches in sorted(t7.items()):
            ko = _kickoffs(issue)
            bucket = done.setdefault(issue, {})
            for no, rec in sorted(matches.items(), key=lambda kv: int(kv[0])):
                if no in bucket and not overwrite:
                    continue
                if limit is not None and fetched >= limit:
                    print(f"到达 --limit {limit}，停")
                    return
                mid = rec.get("match_id")
                if not mid:
                    continue
                if no not in ko:
                    no_kickoff += 1
                    continue
                try:
                    quotes = client.fetch_euro_odds(mid)
                except (Titan007Error, Exception) as exc:   # noqa: BLE001 报告,不静默
                    failed += 1
                    print(f"  ✗ {issue}/{no} {mid}: {type(exc).__name__} {exc}")
                    continue
                cutoff = ko.get(no)
                if cutoff is None:
                    # ⛔拿不到开球时刻就无法证明报价是赛前的 → 丢整场，绝不放行。
                    # 26101 之前的期次没有 issue.json，静默放行会让泄漏纪律失效。
                    no_kickoff += 1
                    continue
                usable, stale = [], 0
                for q in quotes:
                    if q.updated_at and q.updated_at > cutoff:
                        stale += 1
                        continue
                    usable.append(q)
                skipped_stale += stale
                if len(usable) < 20:
                    print(f"  ✗ {issue}/{no}: 可用书目仅 {len(usable)}（丢弃）")
                    failed += 1
                    continue
                # 陈盘污染检验（2026-09-14 加）：按「距开球多久更新过」分层重算共识。
                # 实测多数书商末次更新在开球前 ~8 小时，固定 2h/6h 档几乎恒空；
                # 改用**该场自身的新鲜度分位**分层——尺度无关，任何场都有样本。
                pairs = [(((cutoff - q.updated_at).total_seconds() / 3600.0)
                          if q.updated_at else None, q) for q in usable]
                lags = sorted(x for x, _ in pairs if x is not None)
                med_lag = lags[len(lags) // 2] if lags else None
                q1_lag = lags[len(lags) // 4] if lags else None
                by_recency: dict[str, list] = {"all": [q.current for _, q in pairs]}
                by_recency["fresh_half"] = [
                    q.current for x, q in pairs if x is not None and med_lag is not None
                    and x <= med_lag]
                by_recency["fresh_quarter"] = [
                    q.current for x, q in pairs if x is not None and q1_lag is not None
                    and x <= q1_lag]
                by_recency["stale_half"] = [
                    q.current for x, q in pairs if x is not None and med_lag is not None
                    and x > med_lag]
                bucket[no] = {
                    "match_id": mid,
                    "kickoff": cutoff.isoformat() if cutoff else None,
                    "stale_dropped": stale,
                    "current": _stats([_devig(q.current) for q in usable]),
                    "opening": _stats([_devig(q.opening) for q in usable]),
                    "lag_hours_median": (statistics.median(lags) if lags else None),
                    "lag_hours_p90": (sorted(lags)[int(0.9 * len(lags))] if lags else None),
                    "consensus": {k: _consensus(v) for k, v in by_recency.items()},
                    "n_recent": {k: len(v) for k, v in by_recency.items()},
                    "consensus_opening": _consensus([q.opening for q in usable]),
                }
                fetched += 1
                if fetched % 25 == 0:
                    OUT.write_text(json.dumps(done, ensure_ascii=False), "utf-8")
                    print(f"  …{fetched} 场已采（中途落盘）")
                time.sleep(sleep_s)
    finally:
        client.close()
        OUT.write_text(json.dumps(done, ensure_ascii=False), "utf-8")
    total = sum(len(v) for v in done.values())
    print(f"采集完成：本轮 {fetched} 场，失败 {failed}，无开球时刻丢场 {no_kickoff}，"
          f"赛后报价丢弃 {skipped_stale} 条；累计 {total} 场 → {OUT}")
    if issue:
        # RSI 接线（2026-09-18）：采完登记 F1c 义务；失败只打印，不影响采集。
        from nutmeg.decision.rsi_wiring import after_observation_artifact
        ko = _kickoffs(issue)
        day = min(ko.values()).date().isoformat() if ko else datetime.now().date().isoformat()
        after_observation_artifact(exp="F1c", duty="dispersion-observation", issue=issue, day=day,
                                   artifact=OUT, n_rows=len(done.get(issue, {})), data_dir=Z.parent)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true",
                    help="重采并覆盖已有条目（字段升级时用）")
    ap.add_argument("--issue", default=None,
                    help="先把该期 match_id（取自 <期>-f2-observation.json）补进 t7-backfill 再采，"
                         "采完登记 F1c 义务")
    a = ap.parse_args()
    if a.issue:
        _backfill_issue(a.issue)
    collect(a.sleep, a.limit, a.overwrite, issue=a.issue)


if __name__ == "__main__":
    main()
