#!/usr/bin/env python
"""竞彩历史扩容（假期迭代 #5，2026-10-01）：按日期区间抓 titan007 JcResult，
把 **赛果 + 开奖 SP 赔率** 存进 `.nutmeg-data/jczq/jc-history.json`（与每日结算源
`jc-results.json` 分开，不动它的语义）。

JcResult 页按 `$` 分三段：联赛表 / 赛果行 / SP 行。赛果行沿用 `jczq_result_backfill.parse_day`
的字段（titan007 id、竞彩编号、全场/半场比分、亚盘线）；SP 行每场 11 字段：
`id^胜平负结果^SP^让球结果(线)^SP^总进球^SP^半全场^SP^比分^SP`——只有**开奖那个面**的赔率，
没有三面全价。所以历史板面的 belief 只能用终盘（titan007 sharp），派奖用开奖 SP。

    uv run python scripts/jczq_history_backfill.py --from 2025-08-01 --to 2026-05-17 [--sleep 0.3]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from jczq_result_backfill import HEADERS, URL, parse_day  # noqa: E402

OUT = ROOT / ".nutmeg-data" / "jczq" / "jc-history.json"
_LINE = re.compile(r"^(.*?)\(([+-]?\d+(?:\.\d+)?)\)$")


def _num(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_sp(text: str) -> dict[str, dict]:
    """SP 段 → {titan007 id: {had, hhad, ttg, hafu, crs}}；每项 {outcome, odds[, line]}。"""
    parts = text.split("$")
    if len(parts) < 3:
        return {}
    out: dict[str, dict] = {}
    for raw in parts[2].split("!"):
        f = raw.split("^")
        if len(f) < 11 or not f[0].strip():
            continue
        line = None
        hhad_outcome = f[3].strip()
        m = _LINE.match(hhad_outcome)
        if m:
            hhad_outcome, line = m.group(1), _num(m.group(2))
        out[f[0].strip()] = {
            "had": {"outcome": f[1].strip(), "odds": _num(f[2])},
            "hhad": {"outcome": hhad_outcome, "line": line, "odds": _num(f[4])},
            "ttg": {"outcome": f[5].strip(), "odds": _num(f[6])},
            "hafu": {"outcome": f[7].strip(), "odds": _num(f[8])},
            "crs": {"outcome": f[9].strip(), "odds": _num(f[10])},
        }
    return out


def parse_names(text: str) -> dict[str, dict]:
    """赛果行里的队名/联赛（第 8/10 字段是队名变体，取简体第一个）。"""
    if "$" not in text:
        return {}
    out: dict[str, dict] = {}
    for raw in text.split("$")[1].split("!"):
        f = raw.split("^")
        if len(f) < 23:
            continue
        code = f[4].strip()
        if code:
            out[code] = {"home": f[8].split(",")[0].strip(), "away": f[10].split(",")[0].strip()}
    return out


def parse_history_day(text: str) -> dict[str, dict]:
    results = parse_day(text)
    sp = parse_sp(text)
    names = parse_names(text)
    for code, rec in results.items():
        rec.update(names.get(code, {}))
        rec["sp"] = sp.get(rec["match_id"])
    return results


def collect(start: date, end: date, *, sleep_s: float = 0.3, force: bool = False) -> dict:
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    client = httpx.Client(headers=HEADERS, timeout=20.0)
    fetched = failed = skipped = 0
    try:
        day = start
        while day <= end:
            d = day.isoformat()
            day += timedelta(days=1)
            if d in done and not force:
                skipped += 1
                continue
            try:
                r = client.get(URL.format(d=d))
                r.raise_for_status()
                parsed = parse_history_day(r.content.decode("utf-8", "replace"))
            except Exception as exc:  # noqa: BLE001 —— 报告不静默
                failed += 1
                print(f"  ✗ {d}: {type(exc).__name__} {exc}")
                continue
            done[d] = parsed
            fetched += 1
            time.sleep(sleep_s)
    finally:
        client.close()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(dict(sorted(done.items())), ensure_ascii=False), encoding="utf-8")
    matches = sum(len(v) for v in done.values())
    with_sp = sum(1 for v in done.values() for rec in v.values() if rec.get("sp"))
    print(f"历史回填：本轮 {fetched} 天（跳过 {skipped}，失败 {failed}）；累计 {len(done)} 天 / "
          f"{matches} 场，带 SP {with_sp} → {OUT}")
    return {"fetched": fetched, "failed": failed, "days": len(done), "matches": matches,
            "with_sp": with_sp}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--force", action="store_true", help="已抓过的天也重抓")
    args = ap.parse_args()
    collect(date.fromisoformat(args.start), date.fromisoformat(args.end), sleep_s=args.sleep,
            force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
