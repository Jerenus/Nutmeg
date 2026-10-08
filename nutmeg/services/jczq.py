"""体彩竞彩计算器与赛程列表的抓取器（market_data 的主源；备源是 500.com）。"""
from __future__ import annotations

from typing import Any

import httpx

# 体彩 WAF 拦非浏览器 UA（2026-07-04 起 "Nutmeg/0.2" 稳定 403）；整套头须像浏览器
from nutmeg.data.http import SPORTTERY_HEADERS, get_json

SPORTTERY_JCZQ_PAGE = "https://www.sporttery.cn/jc/jsq/zqspf/"
SPORTTERY_JCZQ_API = (
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry"
    "?channel=c&poolCode=had,hhad,ttg,crs,hafu"
)


class JczqProviderError(ValueError):
    """体彩接口失败：403/网络/errorCode≠0/响应缺 value。"""


def _sporttery_value(url: str, what: str) -> dict[str, Any]:
    """GET 体彩 webapi → `value` 对象；任何失败都是 JczqProviderError（主源→备源回退靠它）。"""
    try:
        payload = get_json(url, headers=SPORTTERY_HEADERS, referer=SPORTTERY_JCZQ_PAGE)
    except (httpx.HTTPError, ValueError) as exc:
        raise JczqProviderError(f"Sporttery {what} fetch failed: {exc}") from exc
    if str(payload.get("errorCode")) != "0":
        raise JczqProviderError(
            f"Sporttery {what} API error: {payload.get('errorCode')} {payload.get('errorMessage')}"
        )
    value = payload.get("value")
    if not isinstance(value, dict):
        raise JczqProviderError(f"Sporttery {what} API response missing value object.")
    return value


class SportteryJczqCalculatorProvider:
    source_api = SPORTTERY_JCZQ_API
    source_page = SPORTTERY_JCZQ_PAGE

    def fetch(self) -> dict[str, Any]:
        return _sporttery_value(self.source_api, "JCZQ")


SPORTTERY_JCZQ_MATCH_LIST_API = (
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"
)


class SportteryMatchListProvider:
    """赛程列表（含未开售的 Define 场次）。只用来诊断计算器为什么空，不出盘口。

    2026-09-28 出生事故：周一板 11:01 才开售，08:00 计算器返回无 matchInfoList 的
    正常成功响应，被报成「WAF 降级」，诊断方向整个走错。
    """

    def fetch(self) -> dict[str, Any]:
        return _sporttery_value(SPORTTERY_JCZQ_MATCH_LIST_API, "match list")
