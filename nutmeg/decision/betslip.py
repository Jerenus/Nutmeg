"""实票登记 —— 把「没入账 = 没打」从口号做成入口。

**Why.** 宪法第 4 条写着 ledger writeback 原则，但直到 2026-09-11 都没有"登记一张已经买了的票"
的入口：`express` 只按预算桶生成**草稿**（每桶占满 cap、非串关桶均分成单关），记不了真实票面
的四件事——**倍数、方案号、试玩/实购、混合过关**。后果是连续三期的账是空的：
26120 J864、26121 U1/U2、26122 四张任九 + 三张竞彩，全部靠 chat 里的截图与内联 python 入账，
方案号至今空着。账是空的，`user_exercise_record` 就只能靠记忆复盘，刹车条款（连续两期全灭 →
减半）也失去了可执行的输入。

**这个模块只做确定性算术，不做任何判断**：注数、票价、命中率、派奖、结算。
"该买哪面"不归它管（那是主循环判读层），"该不该买"也不归它管（那是审计门与用户行权）。

注数公式（已用 26122 实票逐张核对）：
- 任九：从 ≥9 场里选 9 场，注数 = Σ_{9-场子集} Π(每场面数)；恰好 9 场时退化为 Π(面数)。
- 胜负彩：14 场全选，注数 = Π(面数)。
- 竞彩 N 串 1（含混合过关）：注数 = Σ_{M∈过关方式} Σ_{M-腿子集} Π(每腿选项数)。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import reduce
from itertools import combinations
from pathlib import Path

from nutmeg.decision.reconcile import normalize_selection, settle_ticket_leg

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
FACE_ZH = {"3": "主胜", "1": "平", "0": "客胜"}
CHANNELS = ("jczq", "renjiu", "shengfucai")
PRICE_PER_NOTE = 2
RENJIU_PICK = 9
SFC_MATCHES = 14


class BetslipError(ValueError):
    """票面登记的结构性错误（面集合非法、过关方式不可能、渠道未知等）。"""


# ---------------------------------------------------------------------------
# 面集合解析（item 2：不再人肉读截图）
# ---------------------------------------------------------------------------

def parse_faces(token: str) -> str:
    """`"310"` / `"31"` / `"3"` → 规范化面集合；`*` `-` `空` → 空串（未选该场）。

    出生事故 26122：我把用户截图里的 `4·31`（排客胜）读成 `4·30`（排平），据此算了三轮
    候选比较，结论一度反向。**人眼读 31/30 是系统性错误源**，票面输入必须走解析器。
    """
    t = (token or "").strip()
    if t in ("", "*", "-", "—", "–"):
        return ""
    t = t.replace("，", "").replace(",", "").replace(" ", "")
    if not set(t) <= set(FACE_KEYS) or len(set(t)) != len(t):
        raise BetslipError(f"非法面集合 `{token}`：只接受 3/1/0 的不重复组合")
    return "".join(sorted(t, key="310".index))


def parse_faces_row(text: str, *, n_matches: int = SFC_MATCHES) -> dict[str, str]:
    """一行票面 → `{场次: 面集合}`。两种写法都接受，且都不需要人眼对位：

    1. **位置式**（500.com 方案页整行）：`"310 10 0 3 310 31 30 * 1 * * * 3 *"` —— 恰好
       `n_matches` 个 token，`*`/`-` 表示该场未选。
    2. **点名式**：`"2·310 3·10 4·31 13·3"` 或 `"2:310,3:10"` —— 与顺序无关，适合手敲。
    """
    raw = (text or "").replace("，", ",").replace("、", " ").replace("｜", " ")
    raw = raw.replace("|", " ").replace("\n", " ")
    if "·" in raw or ":" in raw or "：" in raw:
        out: dict[str, str] = {}
        for chunk in raw.replace(",", " ").split():
            sep = "·" if "·" in chunk else (":" if ":" in chunk else "：")
            if sep not in chunk:
                continue
            no, faces = chunk.split(sep, 1)
            faces = parse_faces(faces)
            if faces:
                out[str(int(no))] = faces
        if not out:
            raise BetslipError(f"点名式票面解析不出任何场次：{text!r}")
        return out
    tokens = [t for t in raw.replace(",", " ").split() if t]
    if len(tokens) != n_matches:
        raise BetslipError(
            f"位置式票面需要恰好 {n_matches} 个 token（`*` 表示未选），实得 {len(tokens)} 个")
    return {str(i + 1): f for i, t in enumerate(tokens) if (f := parse_faces(t))}


# ---------------------------------------------------------------------------
# 注数算术
# ---------------------------------------------------------------------------

def _product(values) -> int:
    return reduce(lambda a, b: a * b, values, 1)


def zucai_note_count(faces: dict[str, str], *, channel: str) -> int:
    """任九/胜负彩注数。任九选 >9 场即复式，按 9-场子集求和（不是简单连乘）。"""
    sizes = [len(set(f)) for f in faces.values() if f]
    if channel == "shengfucai":
        if len(sizes) != SFC_MATCHES:
            raise BetslipError(f"胜负彩须覆盖 {SFC_MATCHES} 场，实得 {len(sizes)} 场")
        return _product(sizes)
    if len(sizes) < RENJIU_PICK:
        raise BetslipError(f"任九至少选 {RENJIU_PICK} 场，实得 {len(sizes)} 场")
    return sum(_product(c) for c in combinations(sizes, RENJIU_PICK))


def parlay_note_count(leg_options: list[int], combo_sizes: list[int]) -> int:
    """竞彩过关注数。`leg_options`=每腿选项数；`combo_sizes`=[2,3] 表示 2串1+3串1。"""
    n = len(leg_options)
    if not combo_sizes:
        raise BetslipError("竞彩票必须声明过关方式（如 [4] 表示 4串1）")
    total = 0
    for m in combo_sizes:
        if not 1 <= m <= n:
            raise BetslipError(f"{m}串1 与腿数 {n} 不匹配")
        total += sum(_product(c) for c in combinations(leg_options, m))
    return total


# ---------------------------------------------------------------------------
# 对象
# ---------------------------------------------------------------------------

@dataclass
class SlipLeg:
    """一条已买的腿。`selections` 是**已选面**列表（竞彩 had/hhad 用 home/draw/away）。"""
    key: str                      # 竞彩=周五003；足彩=场次号
    name: str = ""
    market: str = "had"           # had | hhad | ttg | crs
    line: float | None = None     # hhad 让球线（体彩 3 路口径，禁亚盘直觉）
    selections: tuple[str, ...] = ()
    odds: tuple[float, ...] = ()  # 与 selections 同序；足彩无赔率留空
    fair: dict | None = None      # 去水市场基线，用于 P 与排面分级

    @property
    def n_options(self) -> int:
        return max(1, len(self.selections))

    @property
    def coverage(self) -> float | None:
        """本腿盖住的市场概率；缺 fair 或市场未支持 → None（不伪造）。

        ⚠️hhad 的 fair 必须是**让球三路**分布（让胜/让平/让负），不是 had 分布——
        体彩让球是 3 路不是亚盘，混用会系统性高估约 28pp（7/06 教训）。
        """
        if not self.fair:
            return None
        keys = [normalize_selection(self.market, s) for s in self.selections]
        if any(k is None for k in keys):
            return None
        if self.market in ("had", "hhad"):
            return sum(self.fair.get(k, 0.0) for k in dict.fromkeys(keys))
        if self.market == "ttg":
            # 进球桶 fair 允许 `{"7":..}` 或 sporttery 的 `{"total_7":..}` 两种键。
            return sum(self.fair.get(k, self.fair.get(f"total_{k}", 0.0))
                       for k in dict.fromkeys(keys))
        return None


@dataclass
class BetSlip:
    """一张**已经买了的**票。与 `express` 的草稿票区别：这里的字段来自现实，不来自预算。"""
    slip_id: str
    channel: str                  # jczq | renjiu | shengfucai
    placed_at: str                # ISO 日期/时刻
    legs: list[SlipLeg]
    multiplier: int = 1
    combo_sizes: tuple[int, ...] = ()     # 竞彩过关方式；足彩留空
    issue: str = ""                       # 足彩期号
    scheme_no: str = ""                   # 方案号/实票号
    purchased: bool = True                # False = 试玩虚拟方案（不进净值）
    note: str = ""
    faces: dict[str, str] = field(default_factory=dict)   # 足彩票面（渲染与结算用）

    # -- 算术 ------------------------------------------------------------
    @property
    def notes(self) -> int:
        if self.channel == "jczq":
            return parlay_note_count([lg.n_options for lg in self.legs],
                                     list(self.combo_sizes))
        return zucai_note_count(self.faces, channel=self.channel)

    @property
    def stake_yuan(self) -> int:
        return self.notes * PRICE_PER_NOTE * self.multiplier

    @property
    def hit_probability(self) -> float | None:
        """P(整票全对)。任何一腿缺 fair → None（禁嘴算，缺数据不伪造）。"""
        covs = [lg.coverage for lg in self.legs]
        if not covs or any(c is None for c in covs):
            return None
        if self.channel == "jczq" and self.combo_sizes and \
                max(self.combo_sizes) < len(self.legs):
            return None      # 混合过关的"至少中一串"不是单一连乘,留给结算层算
        return round(_product(covs), 6)

    @property
    def p_any_combo(self) -> float | None:
        """混合过关：中**任意一串**的概率（枚举每腿中/不中的 2^n 个情景，精确不近似）。

        为什么不是各串概率相加：串与串共享腿、彼此高度相关，相加会系统性高估。
        J3 型（3 腿 2串1+3串1）的"至少中一串"= 至少 2 腿命中。
        """
        if self.channel != "jczq" or not self.combo_sizes:
            return None
        covs = [lg.coverage for lg in self.legs]
        if any(c is None for c in covs):
            return None
        n = len(covs)
        total = 0.0
        for mask in range(1 << n):
            hit = [bool(mask >> i & 1) for i in range(n)]
            if not any(all(hit[i] for i in combo)
                       for m in self.combo_sizes for combo in combinations(range(n), m)):
                continue
            p = 1.0
            for i in range(n):
                p *= covs[i] if hit[i] else (1 - covs[i])
            total += p
        return round(total, 6)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["notes"] = self.notes
        d["stake_yuan"] = self.stake_yuan
        d["hit_probability"] = self.hit_probability
        d["p_any_combo"] = self.p_any_combo
        return d

    @classmethod
    def from_dict(cls, payload: dict) -> BetSlip:
        legs = [SlipLeg(**{k: (tuple(v) if k in ("selections", "odds") else v)
                           for k, v in lg.items() if k in SlipLeg.__annotations__})
                for lg in payload.get("legs", [])]
        return cls(
            slip_id=payload["slip_id"], channel=payload["channel"],
            placed_at=payload.get("placed_at", ""), legs=legs,
            multiplier=int(payload.get("multiplier", 1)),
            combo_sizes=tuple(payload.get("combo_sizes", ())),
            issue=str(payload.get("issue", "")),
            scheme_no=str(payload.get("scheme_no", "")),
            purchased=bool(payload.get("purchased", True)),
            note=str(payload.get("note", "")),
            faces=dict(payload.get("faces", {})),
        )


# ---------------------------------------------------------------------------
# 结算（item 3：多市场 + 串关）
# ---------------------------------------------------------------------------

@dataclass
class SlipSettlement:
    slip_id: str
    settled_legs: int
    pending_legs: int
    won_legs: int
    combos_total: int
    combos_won: int
    payout_yuan: float | None     # 竞彩可算；足彩派彩式玩法须外部给单注奖金
    pnl_yuan: float | None
    detail: list[str]


def _leg_result(leg: SlipLeg, result: dict) -> tuple[str | None, bool | None]:
    """→ (实际结果键, 本腿是否命中)；赛果缺或 pick 不可规约 → (None, None) pending。"""
    actual = settle_ticket_leg(
        market=leg.market,
        pick=normalize_selection(leg.market, leg.selections[0]) if leg.selections else "",
        line=leg.line,
        outcome_90=result.get("outcome_90"),
        goals_h=result.get("goals_h"),
        goals_a=result.get("goals_a"),
    )
    if actual is None:
        return None, None
    picks = {normalize_selection(leg.market, s) for s in leg.selections}
    return actual, actual in picks


def settle_slip(slip: BetSlip, results: dict[str, dict], *,
                prize_per_note: float | None = None) -> SlipSettlement:
    """按 90' 三源赛果结算一张票。

    `results` = {腿 key: {"outcome_90":"home|draw|away","goals_h":int,"goals_a":int}}。
    竞彩：按中奖串的赔率连乘算派奖（确定性）。足彩：派彩式，须外部传 `prize_per_note`
    （官方 gameNo=90 单注奖金），否则 payout 留 None——**缺数据绝不伪造派奖**。
    """
    detail: list[str] = []
    status: dict[str, bool | None] = {}
    for lg in slip.legs:
        actual, hit = _leg_result(lg, results.get(lg.key, {}))
        status[lg.key] = hit
        mark = "?" if hit is None else ("✓" if hit else "✗")
        detail.append(
            f"{mark} {lg.key} {lg.name} {lg.market}"
            f"{('@' + str(lg.line)) if lg.line is not None else ''} "
            f"{'/'.join(lg.selections)} → {actual or '未结'}")
    settled = sum(1 for v in status.values() if v is not None)
    won = sum(1 for v in status.values() if v is True)

    combos_total = combos_won = 0
    payout: float | None = None
    if slip.channel == "jczq":
        idx = list(range(len(slip.legs)))
        payout = 0.0
        undecided = False
        for m in (slip.combo_sizes or (len(slip.legs),)):
            for combo in combinations(idx, m):
                combos_total += 1
                marks = [status[slip.legs[i].key] for i in combo]
                if any(v is None for v in marks):
                    undecided = True
                    continue
                if all(marks):
                    combos_won += 1
                    odds = _product([slip.legs[i].odds[0] for i in combo
                                     if slip.legs[i].odds] or [0])
                    payout += odds * PRICE_PER_NOTE * slip.multiplier
        if undecided:
            payout = None
        else:
            payout = round(payout, 2)
    else:
        faces_hit = all(v for v in status.values() if v is not None)
        if prize_per_note is not None and settled == len(slip.legs):
            combos_total = slip.notes
            combos_won = slip.notes if faces_hit else 0
            payout = round(prize_per_note * combos_won * slip.multiplier, 2)

    pnl = None if payout is None else round(payout - slip.stake_yuan, 2)
    return SlipSettlement(
        slip_id=slip.slip_id, settled_legs=settled,
        pending_legs=len(slip.legs) - settled, won_legs=won,
        combos_total=combos_total, combos_won=combos_won,
        payout_yuan=payout, pnl_yuan=pnl, detail=detail)


# ---------------------------------------------------------------------------
# 登记簿（单一文件，幂等按 slip_id）
# ---------------------------------------------------------------------------

def registry_path(data_dir) -> Path:
    return Path(data_dir) / "betslips.jsonl"


def load_slips(data_dir, *, issue: str | None = None,
               channel: str | None = None) -> list[BetSlip]:
    path = registry_path(data_dir)
    if not path.exists():
        return []
    rows = [json.loads(ln) for ln in path.read_text("utf-8").splitlines() if ln.strip()]
    slips = [BetSlip.from_dict(r) for r in rows]
    if issue:
        slips = [s for s in slips if s.issue == str(issue)]
    if channel:
        slips = [s for s in slips if s.channel == channel]
    return slips


def register_slip(data_dir, slip: BetSlip) -> str:
    """幂等写入（同 slip_id 覆盖）。返回人读摘要行。"""
    if slip.channel not in CHANNELS:
        raise BetslipError(f"未知渠道 {slip.channel}；只接受 {CHANNELS}")
    path = registry_path(data_dir)
    rows = []
    if path.exists():
        rows = [json.loads(ln) for ln in path.read_text("utf-8").splitlines() if ln.strip()]
    rows = [r for r in rows if r.get("slip_id") != slip.slip_id]
    rows.append(slip.to_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    kind = {"jczq": "竞彩", "renjiu": "任九", "shengfucai": "胜负彩"}[slip.channel]
    tag = "" if slip.purchased else "（试玩·不进净值）"
    p = slip.hit_probability
    return (f"登记 {slip.slip_id} {kind} {slip.notes} 注 × {slip.multiplier} 倍 = "
            f"¥{slip.stake_yuan:,}{tag}"
            + (f"｜P(全对)={p * 100:.2f}%" if p is not None else "")
            + (f"｜P(中任意一串)={q * 100:.2f}%"
               if (q := slip.p_any_combo) is not None and len(slip.combo_sizes) > 1 else "")
            + (f"｜方案 {slip.scheme_no}" if slip.scheme_no else "｜⚠️方案号待补"))


def format_slips(slips: list[BetSlip]) -> str:
    if not slips:
        return "(无已登记票面)"
    lines = []
    stake = 0
    for s in slips:
        stake += s.stake_yuan if s.purchased else 0
        p = s.hit_probability
        lines.append(
            f"  {s.slip_id:<16} {s.channel:<11} {s.notes:>5} 注 ×{s.multiplier:<3} "
            f"¥{s.stake_yuan:>6,}"
            + ("" if s.purchased else " [试玩]")
            + (f"  P={p * 100:5.2f}%" if p is not None else "  P=—")
            + (f"  方案 {s.scheme_no}" if s.scheme_no else "  ⚠️方案号待补"))
    lines.append(f"合计实购投入 ¥{stake:,}（试玩不计）")
    return "\n".join(lines)
