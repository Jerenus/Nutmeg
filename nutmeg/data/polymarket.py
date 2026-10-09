"""Polymarket 公开接口的取数件（2026-10-09）。

设计稿：docs/superpowers/specs/2026-10-09-polymarket-attention-design.md。

只读、零鉴权：Gamma `/sports`（联赛系列）、`/events`（对阵事件）、CLOB `/prices-history`（走势）。
只做取数与形状归一，不对号、不判断；单测一律注入 `fetch(url, params) → JSON`。
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from urllib.parse import urlencode

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
SOCCER_CODES = frozenset({
    # 英格兰 / 德国 / 西班牙 / 法国 / 意大利（含次级）
    "epl", "elc", "el1", "bun", "bl2", "lal", "es2", "fl1", "fr2", "sea", "itsb",
    # 荷 / 葡 / 北欧 / 比 / 奥 / 土 / 苏格兰
    "ere", "ned2", "por", "pt2", "swe", "nor", "den", "bel1", "aut", "tur", "sclc",
    # 日 / 韩 / 巴西
    "jap", "ja2", "kor", "bra",
    # 欧战 / 国家队 / 洲际
    "ucl", "uel", "col", "unl", "ewq", "ueq", "fif", "acle", "lib", "sud",
})
"""足球联赛系列码，按 Polymarket 自己的写法（`/sports` 的 `sport` 字段；2026-10-09 核对：法乙是
`fr2`、意乙 `itsb`、西乙 `es2`、欧国联 `unl`）。只收我们板面会出现的联赛——全部足球系列有 183 个，
逐个请求太重。表外的码忽略。"""
PAGE = 100
MAX_PAGES = 100

Fetch = Callable[[str, dict], object]


def default_fetch(url: str, params: dict) -> object:
    from nutmeg.data.http import get_json

    return get_json(f"{url}?{urlencode(params)}" if params else url, headers={})


def soccer_series(fetch: Fetch = default_fetch) -> dict[str, str]:
    """→ {联赛码: 系列 id}，只留足球白名单里的码。"""
    out = {}
    for row in fetch(f"{GAMMA}/sports", {}) or []:
        if isinstance(row, dict) and row.get("sport") in SOCCER_CODES and row.get("series"):
            out[str(row["sport"])] = str(row["series"])
    return out


def series_events(fetch: Fetch, series_id: str, *, closed: bool,
                  end_min: str | None = None, end_max: str | None = None) -> list[dict]:
    """一个系列在结束日窗口内的对阵事件（标题含 vs）；按页拉到空页为止。"""
    out: list[dict] = []
    for page in range(MAX_PAGES):
        params = {"series_id": series_id, "closed": "true" if closed else "false",
                  "limit": PAGE, "offset": page * PAGE}
        if end_min:
            params["end_date_min"] = end_min
        if end_max:
            params["end_date_max"] = end_max
        batch = fetch(f"{GAMMA}/events", params)
        if not isinstance(batch, list) or not batch:
            break
        out += [e for e in batch if isinstance(e, dict) and _TITLE.match(str(e.get("title") or ""))]
    return out


_TITLE = re.compile(r"^(?:[^:]{2,40}:\s*)?(.+?)\s+vs\.?\s+(.+?)(?:\s+-\s+.*)?$")
_SIDE_MARKET = re.compile(r"\s+-\s+\S")
_SUB_SLUG = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z]")


def _num(value) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def normalize_event(ev: dict) -> dict | None:
    """事件 → {id,title,end,home,away,volume,liquidity,volume24hr,markets[question,bid,ask,token]}；
    标题不是「A vs B」→ None。"""
    title = str(ev.get("title") or "")
    m = _TITLE.match(title)
    if not m or _SIDE_MARKET.search(title) or _SUB_SLUG.search(str(ev.get("slug") or "")):
        return None              # 附加盘 / 子事件（标题带「- …」或 slug 日期后带后缀）只留主事件
    markets = []
    for market in ev.get("markets") or []:
        if not isinstance(market, dict):
            continue
        try:
            tokens = json.loads(market.get("clobTokenIds") or "[]")
        except (TypeError, ValueError):
            tokens = []
        markets.append({"question": str(market.get("question") or ""),
                        "bid": _num(market.get("bestBid")), "ask": _num(market.get("bestAsk")),
                        "token": tokens[0] if tokens else None})
    return {"id": str(ev.get("id")), "title": ev.get("title"),
            "end": str(ev.get("endDate") or "")[:10],
            "home": m.group(1).strip(), "away": m.group(2).strip(),
            "volume": _num(ev.get("volume")) or 0.0, "liquidity": _num(ev.get("liquidity")),
            "volume24hr": _num(ev.get("volume24hr")), "markets": markets}


def price_trend(fetch: Fetch, token: str, *, interval: str = "1w",
                fidelity: int = 360) -> tuple[float | None, float | None]:
    """一个结果代币在区间内的首尾价格；无历史 → (None, None)。"""
    doc = fetch(f"{CLOB}/prices-history",
                {"market": token, "interval": interval, "fidelity": fidelity}) or {}
    history = doc.get("history") if isinstance(doc, dict) else None
    if not history:
        return None, None
    return _num(history[0].get("p")), _num(history[-1].get("p"))
