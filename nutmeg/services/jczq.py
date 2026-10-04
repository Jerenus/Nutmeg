"""体彩竞彩计算器与赛程列表的抓取器（market_data 的主源；备源是 500.com）。"""
from __future__ import annotations

from typing import Any

import httpx

SPORTTERY_JCZQ_PAGE = "https://www.sporttery.cn/jc/jsq/zqspf/"
SPORTTERY_JCZQ_API = (
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry"
    "?channel=c&poolCode=had,hhad,ttg,crs,hafu"
)
# 体彩 WAF 拦非浏览器 UA（2026-07-04 起 "Nutmeg/0.2" 稳定 403）；整套头须像浏览器
SPORTTERY_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.sporttery.cn",
}


class JczqProviderError(ValueError):
    """体彩接口失败：403/网络/errorCode≠0/响应缺 value。"""


class SportteryJczqCalculatorProvider:
    source_api = SPORTTERY_JCZQ_API
    source_page = SPORTTERY_JCZQ_PAGE

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self) -> dict[str, Any]:
        try:
            response = httpx.get(
                self.source_api,
                headers={"Referer": self.source_page, **SPORTTERY_BROWSER_HEADERS},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JczqProviderError(f"Sporttery JCZQ fetch failed: {exc}") from exc
        if str(payload.get("errorCode")) != "0":
            raise JczqProviderError(
                f"Sporttery JCZQ API error: {payload.get('errorCode')} "
                f"{payload.get('errorMessage')}"
            )
        value = payload.get("value")
        if not isinstance(value, dict):
            raise JczqProviderError("Sporttery JCZQ API response missing value object.")
        return value


SPORTTERY_JCZQ_MATCH_LIST_API = (
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"
)


class SportteryMatchListProvider:
    """赛程列表（含未开售的 Define 场次）。只用来诊断计算器为什么空，不出盘口。

    2026-09-28 出生事故：周一板 11:01 才开售，08:00 计算器返回无 matchInfoList 的
    正常成功响应，被报成「WAF 降级」，诊断方向整个走错。
    """

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self) -> dict[str, Any]:
        try:
            response = httpx.get(
                SPORTTERY_JCZQ_MATCH_LIST_API,
                headers={"Referer": SPORTTERY_JCZQ_PAGE, **SPORTTERY_BROWSER_HEADERS},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JczqProviderError(f"Sporttery match list fetch failed: {exc}") from exc
        value = payload.get("value")
        if str(payload.get("errorCode")) != "0" or not isinstance(value, dict):
            raise JczqProviderError("Sporttery match list API error")
        return value
