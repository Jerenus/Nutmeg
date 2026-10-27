"""研究引用制（2026-10-27 探照灯 P1/P2）：来源可复核 + 覆盖门。

P1 来源可复核：研究 JSON 里每条事实的 `source` 要能点开。这里只做三件事——
从自由文本里**抽 URL**（一处实现，入库桥 / 遥测 / 反证矩阵都从这里取）、
按研究汇总 `evidence_sources`、可选地**回抓**一次看页面还在不在。回抓失败只记录，
不拒收、不弃权（10-26 Tier 1 口径：形式类问题只警告）。

P2 覆盖门：研究员何时该停止检索，由三条可核的条件定（事实层 7 题全部作答 ·
反例检索过 · 来源可复核），不再只靠轮数上限。`research_coverage` 只**算**这三条，
不改任何判断；未收敛的场在分析包 §1 标 ◇，只展示（20 期后看未收敛场许可胆命中率，
再议是否升为门）。
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from nutmeg.decision.rubric_items import FACT_ITEMS, ITEMS

# 完整 URL，或研究员惯写的「站点/路径」裸形（搜狐 sohu.com/a/1090953957）；
# 纯域名（spotvnews.co.kr）不算——点不开具体页
_URL_BODY = r"[A-Za-z0-9\-._~:/?#@!$&'*+=%]+"    # URL 字符；括号/竖线/逗号/分号当作散文分隔
_URL_RE = re.compile(
    rf"https?://{_URL_BODY}"
    rf"|(?<![\w/.])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{{2,}}/{_URL_BODY}"
)
MIN_URLS = 3
MIN_SITES = 2
STOP_REASONS = ("coverage", "budget", "dead_end")
UNDECLARED = "undeclared"


def extract_urls(text: object) -> list[str]:
    """文本里的 URL（去重、保序、补 https://）。非字符串 → []。"""
    if not isinstance(text, str) or not text:
        return []
    out: list[str] = []
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(".。、:：")
        if "://" not in url:
            url = "https://" + url
        if url not in out:
            out.append(url)
    return out


def site_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _active_fact_items(research: dict) -> dict[str, dict]:
    items = ((research.get("rubric") or {}).get("items") or {})
    out = {}
    for item_id, raw in items.items():
        item = ITEMS.get(item_id)
        if item is None or not item.source_required or not isinstance(raw, dict):
            continue
        if raw.get("abstain"):
            continue
        answer = raw.get("answer")
        active = ((item.type == "noul" and answer == "yes")
                  or (item.type == "choice" and answer in item.effect_options))
        if active:
            out[item_id] = raw
    return out


def evidence_sources(research: dict) -> dict:
    """一场研究的来源账：哪些字段带了可点开的 URL、一共几个站点、研究员声明打开过几页。

    `urls` 合并 rubric 必带来源项 + `strength_balance.events[].source` +
    `premise_corrections[].evidence` + `sources_consulted[].url`。"""
    urls: list[str] = []

    def take(text: object) -> list[str]:
        found = extract_urls(text)
        for url in found:
            if url not in urls:
                urls.append(url)
        return found

    items = _active_fact_items(research)
    items_with_url = sum(1 for raw in items.values() if take(raw.get("source")))
    events = [e for e in ((research.get("strength_balance") or {}).get("events") or [])
              if isinstance(e, dict)]
    events_with_url = sum(1 for e in events if take(e.get("source")))
    for correction in research.get("premise_corrections") or []:
        if isinstance(correction, dict):
            take(correction.get("evidence"))
    consulted = [c for c in (research.get("sources_consulted") or []) if isinstance(c, dict)]
    consulted_urls = [u for c in consulted for u in take(c.get("url"))]
    return {
        "urls": urls,
        "sites": sorted({site_of(u) for u in urls}),
        "items_active": len(items),
        "items_with_url": items_with_url,
        "events": len(events),
        "events_with_url": events_with_url,
        "consulted": len(consulted_urls),
        "declared": "sources_consulted" in research,
    }


def probe_sources(urls: Iterable[str], *, timeout: float = 5.0, workers: int = 6) -> dict:
    """回抓：每个 URL 一次 HEAD（405/403 再 GET，不读正文）→ {url: {"ok", "status", "error"}}。
    体育站 WAF 多、HEAD 常被拒，所以 ok=False 只是「这次没打开」，不是「来源是假的」。"""
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    from nutmeg.data.http import browser_headers

    def one(url: str) -> tuple[str, dict]:
        try:
            with httpx.Client(headers=browser_headers(), timeout=timeout,
                              follow_redirects=True) as client:
                response = client.head(url)
                if response.status_code in (403, 405, 501):
                    with client.stream("GET", url) as streamed:
                        response = streamed
                return url, {"ok": response.status_code < 400,
                             "status": response.status_code, "error": ""}
        except Exception as exc:  # noqa: BLE001 —— 网络层任何失败都只记录
            return url, {"ok": False, "status": None, "error": type(exc).__name__}

    urls = list(dict.fromkeys(urls))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(urls))) as pool:
        return dict(pool.map(one, urls))


Probe = Callable[[list[str]], dict]


def attach_sources(research: dict, *, probe: Probe | None = None) -> dict:
    """给研究原件补 `evidence_sources`（含回抓结果 `probe_ok`/`probe`）。只加字段，不改判断。"""
    summary = evidence_sources(research)
    if probe is not None and summary["urls"]:
        results = probe(summary["urls"])
        summary["probe"] = results
        summary["probe_ok"] = sum(1 for r in results.values() if r.get("ok"))
    research["evidence_sources"] = summary
    return summary


def research_coverage(research: dict, *, raw_items: Iterable[str], retried: bool = False) -> dict:
    """覆盖门三条（P2）：事实 7 题全部作答（弃权也算答）· 反例检索过（研究员声明 +
    falsifier 成句）· 来源可复核（≥3 个 URL 且 ≥2 个站点）。三条全过 = converged。

    `raw_items` 是归一前研究员真正写了的 rubric 项（归一后缺项与弃权分不开）。"""
    answered = sorted(set(raw_items) & set(FACT_ITEMS))
    stop = research.get("stop_rule") if isinstance(research.get("stop_rule"), dict) else {}
    falsifier = str((research.get("stance") or {}).get("falsifier") or "").strip()
    sources = research.get("evidence_sources") or evidence_sources(research)
    counter_note = str(stop.get("counter_note") or "").strip()
    facts_ok = len(answered) == len(FACT_ITEMS)
    counter_ok = bool(stop.get("counter_searched")) and bool(falsifier) and bool(counter_note)
    sources_ok = len(sources["urls"]) >= MIN_URLS and len(sources["sites"]) >= MIN_SITES
    declared = str(stop.get("reason") or "")
    reason = declared if declared in STOP_REASONS else UNDECLARED
    if retried and reason == "coverage":
        reason = "budget"           # 撞过轮数上限再说「按覆盖停的」不可信
    return {
        "facts_answered": f"{len(answered)}/{len(FACT_ITEMS)}",
        "facts_ok": facts_ok,
        "counter_searched": counter_ok,
        "counter_note": counter_note[:120],
        "sources_ok": sources_ok,
        "urls": len(sources["urls"]),
        "sites": len(sources["sites"]),
        "converged": facts_ok and counter_ok and sources_ok,
        "stop_reason": reason,
        "stop_reason_declared": declared or None,
        "retried": bool(retried),
    }


def coverage_mark(coverage: dict | None) -> str:
    """分析包 §1 角标：收敛 ✓、未收敛 ◇、无数据 —。"""
    if not isinstance(coverage, dict):
        return "—"
    return "✓" if coverage.get("converged") else "◇"
