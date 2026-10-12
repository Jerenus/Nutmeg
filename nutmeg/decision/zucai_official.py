"""传统足彩官方赛果/奖金 —— 结算与回填的唯一权威源（Roadmap D3+A3）。

**D3（AET 口径守卫）**：赛果一律取官方 `lotteryDrawResult`（14 位 3/1/0 串，**90 分钟口径**）。
本模块**不接触** API-Football 的 `goals` 字段——那个字段含加时（2026-08-11 博德实测：
90' 2-2 / goals 3-2），任何用它产赛果的自动化都会把杯赛平局结算成主胜。

**A3（自动回填）**：同一接口（gameNo=90，2026-08-09 落库验证 12/12 精确）一次拿全：
赛果串、任九奖金（prizeLevelListRj）、胜负彩奖金（prizeLevelList）、销量。
产出两件事：①`official-results.json` 的本期赛果串（rsi balance / 复盘编码 / ops-status 读）；
②ledger 的 hits/prize_yuan 自动结账（26102 曾把奖金估成中位区、实际 ¥21,018——此类估计
错误从此由机器一行输出）。（`{issue}-outcomes.json` 喂的 `decision-reconcile-zucai` 已删，
`--write-outcomes` 2026-10-08 随之移除。）
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

API_URL = ("https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
           "?gameNo=90&provinceId=0&pageSize={page_size}&isVerify=1&pageNo=1")
VALID_CODES = {"3", "1", "0"}
RENJIU_RETURN_RATE = 0.64


@dataclass(frozen=True)
class OfficialDraw:
    """一期的官方开奖事实。results 键为场次号 1-14（str），值为 90' 口径 3/1/0。"""

    issue: str
    draw_date: str
    results: dict            # {"1": "3", ...}
    renjiu: dict | None      # {"stake_count": int, "stake_amount": float}
    sfc_first: dict | None   # 胜负彩一等奖 同构
    sfc_second: dict | None
    sale_amount_rj: float | None
    scores: dict | None = None   # {"1": (2,1), ...} 90 分钟比分(czScore),缺则 None


@dataclass(frozen=True)
class OfficialRenjiuHistory:
    """Bonus-only official history; independent from the 14-result settlement string."""

    issue: str
    draw_date: str
    stake_count: int
    stake_amount: float
    sale_amount: float

    @property
    def pool_implied_bonus(self) -> float:
        return self.sale_amount * RENJIU_RETURN_RATE / self.stake_count

    @property
    def observed_return_rate(self) -> float:
        return self.stake_amount * self.stake_count / self.sale_amount

    def payout_consistent_with_return_rate(self) -> bool:
        """64% 常数校验，允许官方单注奖金向下取整到元的损耗。

        每注取整损失 <¥1，故实付总额与 销量×64% 的差必须落在
        [0, stake_count) 区间（26111 实测：43,365 注把观察返奖率压到
        63.78%，旧的 ±0.2pp 平坦容差在高中奖注数下必然误报）。
        """
        expected_total = self.sale_amount * RENJIU_RETURN_RATE
        paid_total = self.stake_amount * self.stake_count
        shortfall = expected_total - paid_total
        epsilon = 1e-9 * max(abs(expected_total), 1.0)
        # 只允许「非负且严格小于 注数×¥1」的取整损耗:
        # 多付(shortfall<0)与少付≥1元/注 都是真实漂移,必须拒绝。
        return -epsilon <= shortfall < self.stake_count


def _num(raw) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def parse_draw(item: dict) -> OfficialDraw:
    """官方 list 条目 → OfficialDraw。赛果串不是 14 个合法码即抛错（宁死不猜）。"""
    codes = str(item.get("lotteryDrawResult") or "").split()
    if len(codes) != 14 or any(c not in VALID_CODES for c in codes):
        raise ValueError(
            f"官方赛果串异常({item.get('lotteryDrawNum')}): {item.get('lotteryDrawResult')!r}")
    results = {str(i + 1): c for i, c in enumerate(codes)}

    def _prize(rows, level=None):
        for p in rows or []:
            if level is None or p.get("prizeLevel") == level:
                cnt, amt = _num(p.get("stakeCount")), _num(p.get("stakeAmount"))
                if cnt is not None and amt is not None:
                    return {"stake_count": int(cnt), "stake_amount": amt}
        return None

    scores: dict = {}
    for m in item.get("matchList") or []:
        raw = str(m.get("czScore") or "")
        if ":" in raw:
            try:
                h, a = raw.split(":")
                scores[str(m.get("matchNum"))] = (int(h), int(a))
            except ValueError:
                pass                      # 比分不可解析 → 该场无 margin 数据,不猜

    return OfficialDraw(
        issue=str(item.get("lotteryDrawNum")),
        draw_date=str(item.get("lotteryDrawTime") or ""),
        results=results,
        renjiu=_prize(item.get("prizeLevelListRj")),
        sfc_first=_prize(item.get("prizeLevelList"), "一等奖"),
        sfc_second=_prize(item.get("prizeLevelList"), "二等奖"),
        sale_amount_rj=_num(item.get("totalSaleAmountRj")),
        scores=scores or None,
    )


def parse_renjiu_history_item(item: dict) -> OfficialRenjiuHistory:
    """Parse only official Renjiu bonus facts; cancelled result faces stay irrelevant."""
    issue = str(item.get("lotteryDrawNum") or "").strip()
    prize = None
    for row in item.get("prizeLevelListRj") or []:
        count = _num(row.get("stakeCount"))
        amount = _num(row.get("stakeAmount"))
        if count is not None and amount is not None:
            prize = (count, amount)
            break
    sale = _num(item.get("totalSaleAmountRj"))
    if (
        not issue
        or prize is None
        or prize[0] <= 0
        or prize[1] <= 0
        or sale is None
        or sale <= 0
    ):
        raise ValueError(f"任九历史奖金事实缺失或非正数({issue or 'unknown'})")
    history = OfficialRenjiuHistory(
        issue=issue,
        draw_date=str(item.get("lotteryDrawTime") or ""),
        stake_count=int(prize[0]),
        stake_amount=float(prize[1]),
        sale_amount=float(sale),
    )
    if not history.payout_consistent_with_return_rate():
        raise ValueError(
            f"任九历史返奖率异常({issue}): {history.observed_return_rate:.4f}"
        )
    return history


def parse_renjiu_history_payload(payload: dict) -> list[OfficialRenjiuHistory]:
    """Parse the official history response without depending on result faces."""
    if not isinstance(payload, dict):
        raise ValueError("official history payload must be an object")
    items = (payload.get("value") or {}).get("list") or []
    if not isinstance(items, list) or not items:
        raise ValueError("official history contains no rows")
    return [parse_renjiu_history_item(item) for item in items]


def fetch_history(*, page_size: int, fetcher=None, timeout: float = 20.0) -> dict:
    """官方 gameNo=90 历史页的原始响应（胜负彩 + 任九奖金 + 赛果串）。

    唯一的抓取处（2026-10-08 B5）：任九奖金历史、单期开奖、gym 奖金缓存此前各写一个 fetcher。
    `fetcher(url) -> dict` 供测试 / 离线文件注入。"""
    url = API_URL.format(page_size=page_size)
    if fetcher is not None:
        return fetcher(url)
    from nutmeg.data.http import SPORTTERY_REFERER, get_json

    return get_json(url, referer=SPORTTERY_REFERER, timeout=timeout)


def fetch_renjiu_history(*, fetcher=None, page_size: int = 60) -> list[OfficialRenjiuHistory]:
    """Fetch bonus-only gameNo=90 history in provider order."""
    return parse_renjiu_history_payload(fetch_history(page_size=page_size, fetcher=fetcher))


def fetch_official(issue: str, *, fetcher=None, page_size: int = 15) -> OfficialDraw | None:
    """抓官方历史页找指定期号。未开奖/未出现在列表 → None（不是错误）。"""
    payload = fetch_history(page_size=page_size, fetcher=fetcher)
    for item in ((payload.get("value") or {}).get("list") or []):
        if str(item.get("lotteryDrawNum")) == str(issue):
            return parse_draw(item)
    return None


def record_official_result(draw: OfficialDraw, zucai_dir) -> Path:
    """把本期 90' 赛果串并入 official-results.json（{期号: "3 1 0 ..."}，幂等）。

    rsi balance / postmortem / ops-status 都读这份；v0.4.0 清理删掉了唯一的写手，
    26132 因此开奖后 F9 仍读不到赛果（2026-09-26）。
    """
    path = Path(zucai_dir) / "official-results.json"
    doc = json.loads(path.read_text("utf-8")) if path.exists() else {}
    doc[str(draw.issue)] = " ".join(draw.results[str(i)] for i in range(1, 15))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    return path


def format_draw(draw: OfficialDraw) -> str:
    codes = " ".join(draw.results[str(i)] for i in range(1, 15))
    out = [f"{draw.issue} 开奖({draw.draw_date}): {codes}"]
    for label, pz in (("任九", draw.renjiu), ("胜负彩一等", draw.sfc_first),
                      ("胜负彩二等", draw.sfc_second)):
        if pz:
            out.append(f"  {label}: {pz['stake_count']:,} 注 × ¥{pz['stake_amount']:,.0f}")
    if draw.sale_amount_rj:
        out.append(f"  任九销量: ¥{draw.sale_amount_rj:,.0f}")
    return "\n".join(out)
