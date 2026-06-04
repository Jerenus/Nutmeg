"""okooo 赛果抓取 —— live 复盘（jczq-tiered-review / jczq-bold-review）共用。

spec §33（2026-06-04）：从退役的 ``jczq_review`` 模块剥离出来。原 ``jczq_review``
（v1 generator 复盘服务）已删除，但其中的 okooo 结果 provider 是引擎无关的共享件，
tiered/bold 两条 live 复盘链都借它抓比分 + 各池实际结果。此模块只含抓取/解析，
不含任何 v1 选腿/评分逻辑。
"""

from __future__ import annotations

import re
from datetime import date
from html import unescape
from typing import Protocol

import httpx


class JczqResultProvider(Protocol):
    source_page: str

    def fetch_results(self, run_date: str) -> dict[str, dict[str, str]]: ...


class OkoooJczqResultProvider:
    source_page = "https://m.okooo.com/kaijiang/sport.php"

    _POOL_TYPES = {
        "had": "SportteryNWDL",
        "hhad": "SportteryWDL",
        "crs": "SportteryScore",
        "ttg": "SportteryTotalGoals",
        "hafu": "SportteryHalfFull",
    }

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch_results(self, run_date: str) -> dict[str, dict[str, str]]:
        prefix = _weekday_prefix(run_date)
        results: dict[str, dict[str, str]] = {}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148"
            )
        }
        for pool, lottery_type in self._POOL_TYPES.items():
            url = f"{self.source_page}?LotteryNo={run_date}&LotteryType={lottery_type}"
            response = self._client.get(url, headers=headers)
            response.raise_for_status()
            text = response.content.decode("gb18030", errors="replace")
            for cells in _parse_result_rows(text):
                match_no = f"{prefix}{cells[0]}"
                row = results.setdefault(match_no, {})
                score, half_score = _parse_score_cell(cells[4] if len(cells) > 4 else "")
                if score:
                    row["score"] = score
                if half_score:
                    row["half_score"] = half_score
                actual, odds = _parse_pool_result_and_odds(pool, cells[-1])
                row[pool] = actual
                if odds is not None:
                    row[f"{pool}_odds"] = f"{odds:.2f}"
        return results


def _parse_result_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
        cells = [
            _clean_html(cell)
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
        ]
        if cells and cells[0].isdigit():
            rows.append(cells)
    return rows


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split())


def _parse_score_cell(value: str) -> tuple[str, str]:
    score_match = re.search(r"(\d+\s*:\s*\d+)", value)
    half_match = re.search(r"半场\s*(\d+\s*:\s*\d+)", value)
    score = score_match.group(1).replace(" ", "") if score_match else ""
    half_score = half_match.group(1).replace(" ", "") if half_match else ""
    return score, half_score


def _parse_pool_result_and_odds(pool: str, value: str) -> tuple[str, float | None]:
    token = value.split()[0] if value.split() else value.strip()
    odds = None
    for part in value.split()[1:]:
        try:
            odds = float(part)
            break
        except ValueError:
            continue
    if pool == "had":
        return {"主": "胜", "平": "平", "客": "负"}.get(token, token), odds
    if pool == "hhad":
        return {"主": "让胜", "平": "让平", "客": "让负"}.get(token, token), odds
    if pool == "hafu":
        parts = token.split("-")
        label = {"3": "胜", "1": "平", "0": "负"}
        if len(parts) == 2:
            return f"{label.get(parts[0], parts[0])}/{label.get(parts[1], parts[1])}", odds
    return token, odds


def _weekday_prefix(value: str) -> str:
    day = date.fromisoformat(value)
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day.weekday()]
