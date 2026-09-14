#!/usr/bin/env python
"""因子 2 —— 让球线的**离散位移**（初盘 → 终盘），区别于已证伪的赔率连续位移。

机制（先写死，再跑）：书商**改赔率**是连续微调、成本近零；**改线**是把标的换成另一个
离散档位，是一次承诺。已证伪的「位移动量」测的是赔率漂移（26124-26125 两轮，扩样后
符号翻转）；本因子测的是**线本身是否跨档**——两者不是同一个量。

数据源 ``vip.titan007.com/AsianOdds_n.aspx?id={match_id}``，每家公司一行三组：

====================================  ==============================================
组                                     识别
====================================  ==============================================
初盘                                   单元格带 ``title="YYYY-MM-DD HH:MM"`` 时间戳
``oddstype="wholeLastOdds"``（隐藏）   ⛔**滚球盘**，``display:none``，一律不取
``oddstype="wholeOdds"``               终盘（末次赛前）
====================================  ==============================================

⛔泄漏纪律：中间那组是赛中盘（实测 3062530 初/终皆「一球/球半」而它是「平手/半球」）。
把它当终盘用即为赛果泄漏——本脚本按 ``oddstype`` 属性取，不按列序取。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

import httpx

Z = Path(".nutmeg-data/zucai")
OUT = Z / "t7-handicap.json"
URL = "http://vip.titan007.com/AsianOdds_n.aspx?id={mid}"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
    "Referer": "http://vip.titan007.com/",
}
_RE_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_RE_CELL = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S)
_RE_GOALS = re.compile(r'goals\s*=\s*"([-\d.]+)"')
_RE_TITLE_TS = re.compile(r'title="(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"')
_RE_ODDSTYPE = re.compile(r'oddstype\s*=\s*"(\w+)"')


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).replace("&nbsp;", " ").strip()


def parse_handicap(page: str) -> list[dict]:
    """每家公司一条 ``{company, opening_goals, closing_goals, opened_at}``。

    只取**主盘**行（公司名非空）；``盘2``/``盘3`` 次要盘行公司名为空，跳过。
    """
    i = page.find('id="odds"')
    if i < 0:
        return []
    body = page[i:page.find("</table>", i)]
    out: list[dict] = []
    for row in _RE_ROW.findall(body):
        cells = _RE_CELL.findall(row)
        if len(cells) < 10:
            continue
        company = _text(cells[1][1])
        if not company:                       # 次要盘行（盘2/盘3）
            continue
        opening = closing = opened_at = None
        for attrs, _html in cells:
            goals = _RE_GOALS.search(attrs)
            if not goals:
                continue
            kind = _RE_ODDSTYPE.search(attrs)
            if kind and kind.group(1) == "wholeLastOdds":
                continue                      # ⛔滚球盘
            if kind and kind.group(1) == "wholeOdds":
                closing = float(goals.group(1))
            elif _RE_TITLE_TS.search(attrs):
                opening = float(goals.group(1))
                opened_at = _RE_TITLE_TS.search(attrs).group(1)
        if opening is None or closing is None:
            continue
        out.append({"company": company, "opening_goals": opening,
                    "closing_goals": closing, "opened_at": opened_at})
    return out


def collect(sleep_s: float, limit: int | None) -> None:
    t7 = json.load(open(Z / "t7-backfill.json"))
    done = json.load(open(OUT)) if OUT.exists() else {}
    fetched = failed = 0
    client = httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True)
    try:
        for issue, matches in sorted(t7.items()):
            bucket = done.setdefault(issue, {})
            for no, rec in sorted(matches.items(), key=lambda kv: int(kv[0])):
                if no in bucket or not rec.get("match_id"):
                    continue
                if limit is not None and fetched >= limit:
                    print(f"到达 --limit {limit}，停")
                    return
                try:
                    resp = client.get(URL.format(mid=rec["match_id"]))
                    resp.raise_for_status()
                    books = parse_handicap(resp.content.decode("utf-8", "replace"))
                except Exception as exc:      # noqa: BLE001 报告,不静默(假空盘死法)
                    failed += 1
                    print(f"  ✗ {issue}/{no}: {type(exc).__name__} {exc}")
                    continue
                if len(books) < 8:
                    failed += 1
                    print(f"  ✗ {issue}/{no}: 仅解出 {len(books)} 家，丢弃")
                    continue
                op = statistics.median(b["opening_goals"] for b in books)
                cl = statistics.median(b["closing_goals"] for b in books)
                moved = sum(1 for b in books
                            if b["closing_goals"] != b["opening_goals"])
                bucket[no] = {
                    "match_id": rec["match_id"], "n_books": len(books),
                    "opening_median": op, "closing_median": cl,
                    "line_move": round(cl - op, 3),
                    "moved_share": moved / len(books),
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
    print(f"采集完成：本轮 {fetched} 场，失败 {failed}；累计 {total} 场 → {OUT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    collect(a.sleep, a.limit)


if __name__ == "__main__":
    main()
