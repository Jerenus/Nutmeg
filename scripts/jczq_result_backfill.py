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


def _board_codes(day_dir: Path, day: str) -> set[str]:
    """Return every stable match code recorded for one business day."""
    codes: set[str] = set()
    markets_path = day_dir / "sporttery_markets.json"
    try:
        markets = json.loads(markets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        markets = {}
    for group in markets.get("matchInfoList") or []:
        for match in group.get("subMatchList") or []:
            if (match.get("businessDate") or match.get("matchDate")) != day:
                continue
            code = match.get("matchNumStr")
            if code:
                codes.add(str(code))

    # The live Sporttery response drops closed matches. These snapshots retain the
    # full board captured earlier in the day, so use their union for completeness.
    for filename in ("bold_odds.json", "jczq-legs-base.json"):
        path = day_dir / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("legs") if filename == "jczq-legs-base.json" else payload
        if isinstance(rows, dict):
            codes.update(str(code) for code in rows)
        elif isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = row.get("code") or row.get("match_no")
                if code:
                    codes.add(str(code))
    return codes


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
    current_day = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    client = httpx.Client(headers=HEADERS, timeout=20.0)
    fetched = failed = 0
    messages: list[str] = []
    observed_counts: dict[str, int] = {}
    try:
        for d in dates:
            try:
                board_day = date.fromisoformat(d)
            except ValueError:
                continue
            board_codes = _board_codes(DAILY / d, d)
            existing = done.get(d) or {}
            old_enough = (current_day - board_day).days >= 3
            if d in done and (old_enough or (board_codes and board_codes <= set(existing))):
                continue
            done.pop(d, None)
            try:
                r = client.get(URL.format(d=d))
                r.raise_for_status()
                day = parse_day(r.content.decode("utf-8", "replace"))
            except Exception as exc:      # noqa: BLE001 报告,不静默(假空盘死法)
                failed += 1
                messages.append(f"  ✗ {d}: {type(exc).__name__} {exc}")
                continue
            observed_counts[d] = len(board_codes & set(day))
            if old_enough or (board_codes and board_codes <= set(day)):
                done[d] = day
                fetched += 1
            else:
                messages.append(
                    f"  · {d}: 赛果未齐（{observed_counts[d]}/{len(board_codes)}），暂不封存"
                )
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
    lag = (current_day - max(valid_dates)).days if valid_dates else None
    incomplete: list[tuple[str, int, int]] = []
    for raw in dates:
        try:
            board_day = date.fromisoformat(raw)
        except ValueError:
            continue
        if not 0 <= (current_day - board_day).days < 3:
            continue
        board_codes = _board_codes(DAILY / raw, raw)
        if not board_codes:
            continue
        stored = done.get(raw) or {}
        if not board_codes <= set(stored):
            present = observed_counts.get(raw, len(board_codes & set(stored)))
            incomplete.append((raw, present, len(board_codes)))
    if lag is not None and lag > 2:
        print(f"⚠️RESULTS_STALE: latest={max(valid_dates).isoformat()} lag={lag}d")
    elif incomplete:
        detail = ",".join(f"{d}({present}/{total})" for d, present, total in incomplete)
        print(f"⚠️RESULTS_STALE: incomplete={detail}")
    for message in messages:
        print(message)
    print(f"赛果回填：本轮 {fetched} 天，失败 {failed}；累计 {len(done)} 天 / {n} 场 → {OUT}")
    return 2 if (lag is not None and lag > 2) or incomplete else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.3)
    raise SystemExit(collect(ap.parse_args().sleep))
