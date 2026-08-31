"""传统足彩官方赛果/奖金 —— 结算与回填的唯一权威源（Roadmap D3+A3）。

**D3（AET 口径守卫）**：赛果一律取官方 `lotteryDrawResult`（14 位 3/1/0 串，**90 分钟口径**）。
本模块**不接触** API-Football 的 `goals` 字段——那个字段含加时（2026-08-11 博德实测：
90' 2-2 / goals 3-2），任何用它产赛果的自动化都会把杯赛平局结算成主胜。

**A3（自动回填）**：同一接口（gameNo=90，2026-08-09 落库验证 12/12 精确）一次拿全：
赛果串、任九奖金（prizeLevelListRj）、胜负彩奖金（prizeLevelList）、销量。
产出两件事：①`{issue}-outcomes.json`（喂现有 `decision-reconcile-zucai`，字节兼容
`_zucai_outcomes` 读的格式）；②ledger 的 hits/prize_yuan 自动结账（26102 曾把奖金
估成中位区、实际 ¥21,018——此类估计错误从此由机器一行输出）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

API_URL = ("https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
           "?gameNo=90&provinceId=0&pageSize={page_size}&isVerify=1&pageNo=1")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
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
        return -epsilon <= shortfall < self.stake_count - epsilon


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


def fetch_renjiu_history(*, fetcher=None, page_size: int = 60) -> list[OfficialRenjiuHistory]:
    """Fetch bonus-only gameNo=90 history in provider order."""
    if fetcher is None:
        def fetcher(url):
            import httpx

            response = httpx.get(
                url,
                headers={"User-Agent": _UA, "Referer": "https://www.sporttery.cn/"},
                timeout=20.0,
            )
            response.raise_for_status()
            return response.json()
    payload = fetcher(API_URL.format(page_size=page_size))
    return parse_renjiu_history_payload(payload)


def fetch_official(issue: str, *, fetcher=None, page_size: int = 15) -> OfficialDraw | None:
    """抓官方历史页找指定期号。未开奖/未出现在列表 → None（不是错误）。"""
    if fetcher is None:
        def fetcher(url):
            import httpx
            resp = httpx.get(url, headers={"User-Agent": _UA,
                                           "Referer": "https://www.sporttery.cn/"},
                             timeout=20.0)
            resp.raise_for_status()
            return resp.json()
    payload = fetcher(API_URL.format(page_size=page_size))
    for item in ((payload.get("value") or {}).get("list") or []):
        if str(item.get("lotteryDrawNum")) == str(issue):
            return parse_draw(item)
    return None


def write_outcomes(draw: OfficialDraw, zucai_dir) -> Path:
    """落 {issue}-outcomes.json —— 与 verbs._zucai_outcomes 读的格式字节兼容。"""
    path = Path(zucai_dir) / f"{draw.issue}-outcomes.json"
    path.write_text(json.dumps({
        "issue": draw.issue,
        "source": "sporttery-official gameNo=90 (90分钟口径,lotteryDrawResult)",
        "draw_date": draw.draw_date,
        "results": draw.results,
    }, ensure_ascii=False, indent=1), "utf-8")
    return path


def ticket_hits(faces: dict, results: dict) -> tuple[int, int]:
    """复式票命中数。faces={场次: "31"...}；返回 (命中腿数, 总腿数)。

    复式票中奖注数恒为 0 或 1：每腿至多一个面与赛果相符，全中即恰好组合出 1 注。
    """
    total = len(faces)
    hit = sum(1 for no, f in faces.items() if results.get(str(no)) in set(str(f)))
    return hit, total


def settle_ledger(issue: str, zucai_dir, draw: OfficialDraw, *,
                  settled_at: str) -> list[str]:
    """按 rx 的 final_ticket 计算命中并回填 ledger。返回人读摘要行。

    只结 `settled_at is None` 的行（幂等：已结不重结）。任九奖金 = 9/9 时官方单注奖金 ×1。
    """
    zdir = Path(zucai_dir)
    lines: list[str] = []
    rx_path = zdir / f"{issue}-rx.json"
    faces = None
    if rx_path.exists():
        faces = (json.loads(rx_path.read_text("utf-8")) or {}).get("final_ticket")

    ledger = zdir / "zucai-ledger.jsonl"
    if not ledger.exists():
        return [f"{issue}: 无 ledger 文件"]
    rows = [json.loads(ln) for ln in ledger.read_text("utf-8").splitlines() if ln.strip()]
    changed = False
    for r in rows:
        if str(r.get("issue")) != str(issue) or r.get("settled_at"):
            continue
        if r.get("kind") == "任九" and faces:
            hit, total = ticket_hits(faces, draw.results)
            r["hits"] = hit
            prize = 0.0
            if hit == total and draw.renjiu:
                prize = draw.renjiu["stake_amount"]
            r["prize_yuan"] = prize
            r["settled_at"] = settled_at
            note_add = f" | 官方结算({settled_at}): {hit}/{total}"
            if draw.renjiu:
                note_add += (f", 任九单注 ¥{draw.renjiu['stake_amount']:,.0f}"
                             f"×{draw.renjiu['stake_count']}注")
            r["note"] = (r.get("note") or "") + note_add
            lines.append(f"任九 {hit}/{total} → 派奖 ¥{prize:,.0f} (stake ¥{r.get('stake_yuan')})")
            changed = True
        elif r.get("stake_yuan") == 0:      # 空仓行:补 settled_at 即可
            r["hits"] = None
            r["settled_at"] = settled_at
            lines.append("空仓行已闭账")
            changed = True
        else:
            lines.append(f"{r.get('kind')}: 无结构化票面(rx.final_ticket 缺失),需人工结算")
    if changed:
        ledger.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                          "utf-8")
    return lines or [f"{issue}: ledger 无待结行"]


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
