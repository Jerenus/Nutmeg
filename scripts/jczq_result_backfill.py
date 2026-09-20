#!/usr/bin/env python
"""竞彩历史比分回填 —— 因子 4（让球三路跨盘残差）的结算源。

``jc.titan007.com/handle/JcResult.aspx?d=YYYY-MM-DD`` 每行 22-24 字段，实测布局
（2026-09-14，用 ``.nutmeg-data/jczq/daily/2026-09-07/results-0907.json`` 的
两源赛果校验 3/3 通过）：

===== ==============================
下标   含义
===== ==============================
0      titan007 match_id
1      开球时刻
4      **竞彩编号**（如 ``周一001``）
8/10   主/客队名变体
11/12  **全场** 主/客 进球
13/14  半场 主/客 进球
22     亚盘线
===== ==============================

⚠️页面实为 UTF-8（与欧赔页同）；按 gb18030 解会得到乱码但字段切分仍对——本脚本
显式按 UTF-8 解，避免队名核对时被乱码误导。
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

DAILY = Path(".nutmeg-data/jczq/daily")
OUT = Path(".nutmeg-data/jczq/jc-results.json")
URL = "http://jc.titan007.com/handle/JcResult.aspx?d={d}"
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/126", "Referer": "http://jc.titan007.com/"}


def parse_day(text: str) -> dict[str, dict]:
    """``{竞彩编号: {match_id, ft_home, ft_away, ht_home, ht_away, line}}``。"""
    if "$" not in text:
        return {}
    out: dict[str, dict] = {}
    for raw in text[text.index("$") + 1:].split("!"):
        f = raw.split("^")
        if len(f) < 23:
            continue
        try:
            rec = {
                "match_id": f[0].strip(),
                "ft_home": int(f[11]), "ft_away": int(f[12]),
                "ht_home": int(f[13]), "ht_away": int(f[14]),
                "line": f[22].strip(),
            }
        except (ValueError, IndexError):
            continue
        tag = f[4].strip()
        if tag:
            out[tag] = rec
    return out


def collect(sleep_s: float, *, today: date | None = None) -> int:
    dates = sorted(d for d in os.listdir(DAILY)
                   if (DAILY / d / "sporttery_markets.json").exists())
    done = json.load(open(OUT)) if OUT.exists() else {}
    client = httpx.Client(headers=HEADERS, timeout=20.0)
    fetched = failed = 0
    messages: list[str] = []
    try:
        for d in dates:
            if d in done:
                continue
            try:
                r = client.get(URL.format(d=d))
                r.raise_for_status()
                day = parse_day(r.content.decode("utf-8", "replace"))
            except Exception as exc:      # noqa: BLE001 报告,不静默(假空盘死法)
                failed += 1
                messages.append(f"  ✗ {d}: {type(exc).__name__} {exc}")
                continue
            if not day:
                messages.append(f"  · {d}: 板面空（无竞彩赛事或已过期）")
            done[d] = day
            fetched += 1
            time.sleep(sleep_s)
    finally:
        client.close()
        OUT.write_text(json.dumps(done, ensure_ascii=False), "utf-8")
    n = sum(len(v) for v in done.values())
    valid_dates = []
    for raw in done:
        try:
            valid_dates.append(date.fromisoformat(raw))
        except ValueError:
            continue
    current_day = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    lag = (current_day - max(valid_dates)).days if valid_dates else None
    if lag is not None and lag > 2:
        print(f"⚠️RESULTS_STALE: latest={max(valid_dates).isoformat()} lag={lag}d")
    for message in messages:
        print(message)
    print(f"赛果回填：本轮 {fetched} 天，失败 {failed}；累计 {len(done)} 天 / {n} 场 → {OUT}")
    return 2 if lag is not None and lag > 2 else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.3)
    raise SystemExit(collect(ap.parse_args().sleep))
