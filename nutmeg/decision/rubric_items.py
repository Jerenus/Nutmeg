"""判断 rubric r1 问题表（设计 2026-10-02-rubric-judgment-contract）。

一项只问一件事；每项有类型（noul 是非 / choice 多选一 / dist 概率分布）、阶段、效应、
上限 pp、是否必须带来源。**上限只许从结账往下调或退役**（T13：权重从不事前写）。
Jev 形状：类型化问题 → 概率 + 可弃权，不生成解释。
"""
from __future__ import annotations

from dataclasses import dataclass, field

RUBRIC_VERSION = "r3"
SUPPORTED_VERSIONS = ("r1", "r2", "r3")
"""评分器只认这些版本的答案（语料行带 `rubric_version`）；改表＝新版本，旧版本的 n 不混进来。
r2/r3 只退役上限、问题表一字未改，所以 r1/r2/r3 的答案可比，三版一起结账。"""
PHASES = ("fact", "structure", "price", "conclusion")
SIDES = ("home", "away")
UNKNOWN = "unknown"
SOURCE_TIERS = ("club_official", "league_official", "press", "aggregator", "social", UNKNOWN)
"""来源层级：2026-10-02 起只采集不加权；r2 候选——按层级看逐项有效性后再决定是否按层级定上限。"""
RUBRIC_CHANGELOG = (
    {"version": "r1", "date": "2026-10-02", "change": "首版：事实 7 / 结构 6 / 价格 2 项",
     "evidence": "docs/superpowers/evidence/2026-10-02-rubric-judgment-contract.md"},
    {"version": "r2", "date": "2026-10-19",
     "change": "10 项拨动上限退役（问题照问、照记账、T13 逐项照测，不再拨动）："
               "9 项 T13 propose_zero（F_absence_home/F_absence_away/F_goalkeeper/F_venue/"
               "O_other_event/S_spine_intact/S_underdog_path/S_draw_mode/S_crash_candidate）"
               "+ F_rotation（propose_change −14.1pp，与效应方向相反）；只留 F_suspension"
               "（above_floor/hold）。Jun 2026-10-19 裁「可以」",
     "evidence": "docs/superpowers/evidence/2026-10-19-rsi-protocol-v2.md#rubric-r2"},
    {"version": "r3", "date": "2026-10-20",
     "change": "F_suspension 拨动上限退役（T13 严格 n 136→191 后 observed +9.5→+0.6pp、"
               "p 0.04→0.90，propose_zero；收件箱 RSI-f94e4c）。起所有项不拨动，belief＝市场；"
               "问题表一字未改、照答照结账。Jun 2026-10-20 裁「批」",
     "evidence": "docs/superpowers/evidence/2026-10-19-rsi-protocol-v2.md#rubric-r3"},
)
"""增删项的治理：①证据文档说明为什么（结账数据或两读 kappa）→ ②这里加一条 changelog →
③`RUBRIC_VERSION` 升号、`SUPPORTED_VERSIONS` 决定评分器混不混旧版 →
④退役项写 `until`，新项写 `since` → ⑤K1 与逐项因子按版本过滤。没有证据文档不许改表。"""


@dataclass(frozen=True)
class Item:
    id: str
    phase: str
    type: str                       # noul | choice | dist
    options: tuple[str, ...] = ()   # choice 的选项（含 unknown）
    effect: str = ""                # down:home | down:away | up:draw | down:side（按答案取侧）
                                    # | down:anchor | up:underdog | ""（只记录）
    cap_pp: int = 0                 # 单项最大拨动；0＝只记录
    source_required: bool = False   # 答"是"/有效选项时必须带 source + captured_at
    tier: str = "state"             # 派生 tilt.evidence 的 tier
    kind: str = ""                  # 派生 tilt.evidence 的 kind（TILT_KIND_LEXICON）
    text: str = ""                  # 问题原文（读者 B 的提示词）
    effect_options: tuple[str, ...] = field(default_factory=tuple)   # choice 里带效应的选项
    since: str = "r1"               # 进表版本
    until: str | None = None        # 退役版本（None＝在用）
    cap_until: str | None = None    # 上限退役的版本：问题照问、照记账，不再拨动（r2 起）


ITEMS: dict[str, Item] = {}


def _add(item: Item) -> None:
    ITEMS[item.id] = item


# ── 事实层（合取门：没有任何事实项成立 → 拨动预算为 0，无锚归零）──────────────
_add(Item("F_absence_home", "fact", "noul", effect="down:home", cap_pp=6, source_required=True,
          tier="official", kind="absence_official",
          text="主队关键球员（门将/中卫/组织核心/主力射手）缺阵已被官方或主帅确认", cap_until="r2"))
_add(Item("F_absence_away", "fact", "noul", effect="down:away", cap_pp=6, source_required=True,
          tier="official", kind="absence_official",
          text="客队关键球员缺阵已被官方或主帅确认", cap_until="r2"))
_add(Item("F_suspension", "fact", "choice", options=("home", "away", "both", "none", UNKNOWN),
          effect="down:side", cap_pp=4, source_required=True, tier="official", kind="suspension",
          text="哪一侧有核实的停赛（累积黄牌/红牌）", effect_options=("home", "away", "both"),
          cap_until="r3"))
_add(Item("F_rotation", "fact", "choice", options=("home", "away", "both", "none", UNKNOWN),
          effect="down:side", cap_pp=3, source_required=True, tier="official",
          kind="rotation_confirmed",
          text="哪一侧由主帅/官方确认本场轮换主力", effect_options=("home", "away", "both"),
          cap_until="r2"))
_add(Item("F_goalkeeper", "fact", "choice", options=("home", "away", "none", UNKNOWN),
          effect="down:side", cap_pp=3, source_required=True, tier="official",
          kind="goalkeeper_change",
          text="哪一侧确认更换首发门将", effect_options=("home", "away"), cap_until="r2"))
_add(Item("F_venue", "fact", "choice", options=("home", "away", "none", UNKNOWN),
          effect="down:side", cap_pp=2, source_required=True, tier="official",
          kind="venue_anomaly",
          text="场地异常（中立场/无观众/场地条件）不利于哪一侧", effect_options=("home", "away"),
          cap_until="r2"))
_add(Item("O_other_event", "fact", "choice", options=("home", "away", "none", UNKNOWN),
          effect="down:side", cap_pp=2, source_required=True, tier="inferred",
          kind="squad_depth",
          text="其他已核实的本场利空落在哪一侧（一句话写进 note）",
          effect_options=("home", "away"), cap_until="r2"))

# ── 结构层 ──────────────────────────────────────────────────────────────────
_add(Item("S_anchor_side", "structure", "choice", options=("home", "away", "none", UNKNOWN),
          text="强弱天平的锚方（明显更强的一侧）；均势填 none，证据不够判就 unknown"))
_add(Item("S_spine_intact", "structure", "noul", effect="down:anchor:no", cap_pp=3,
          source_required=True, tier="confirmed_structural", kind="anchor_integrity_fail",
          text="锚方中轴（门将/中卫/组织核心）本场完整", cap_until="r2"))
_add(Item("S_underdog_path", "structure", "noul", effect="up:underdog", cap_pp=2,
          tier="state", kind="underdog_path",
          text="弱方有真实存在的取胜/取分路径（不是故事）", cap_until="r2"))
_add(Item("S_draw_mode", "structure", "noul", effect="up:draw", cap_pp=2,
          tier="state", kind="style_matchup",
          text="双方进攻都低效，低比分平局是本场模态之一", cap_until="r2"))
_add(Item("S_crash_candidate", "structure", "noul", effect="down:anchor", cap_pp=2,
          tier="state", kind="form_state",
          text="锚方是翻车候选（近期带洞、密集赛程、动机不足中至少两条）", cap_until="r2"))
_add(Item("S_dead_face", "structure", "choice", options=("3", "1", "0", "none", UNKNOWN),
          text="三证齐全可判死的面（没有就 none）；只记录，不进 pp"))

# ── 价格层 ──────────────────────────────────────────────────────────────────
_add(Item("M_market_read", "price", "choice",
          options=("agree", "overpriced_fav", "underpriced_fav", "underpriced_draw", UNKNOWN),
          text="市场对这场的定价（只记录）"))
_add(Item("M_facts_priced", "price", "noul",
          text="事实层的事件已经被开盘→当前的位移吸收（是 → 事实层 pp 减半）"))

def cap_at(item: Item, version: str = RUBRIC_VERSION) -> int:
    """某版本下这一项的拨动上限：上限已退役（cap_until ≤ version）→ 0。"""
    return 0 if item.cap_until and item.cap_until <= version else item.cap_pp


def directional_items(version: str = RUBRIC_VERSION) -> tuple[str, ...]:
    """某版本下会拨动 belief 的项（聚合用）。"""
    return tuple(i.id for i in ITEMS.values() if cap_at(i, version) > 0)


DIRECTIONAL_ITEMS = directional_items()
EFFECT_ITEMS = tuple(i.id for i in ITEMS.values() if i.effect)
"""有效应方向的项（T13 逐项结账用）：上限退役后照测，留着以后的证据。"""
FACT_ITEMS = tuple(i.id for i in ITEMS.values() if i.phase == "fact")
MAX_ABS_SHIFT_PP = 15


def active_items(version: str = RUBRIC_VERSION) -> dict[str, Item]:
    """某版本在用的项（since ≤ version < until，按版本号字符串比较 r1 < r2 …）。"""
    return {k: v for k, v in ITEMS.items()
            if v.since <= version and (v.until is None or version < v.until)}


def question_table(version: str = RUBRIC_VERSION) -> str:
    """读者 B 提示词用的问题表（id · 类型 · 选项 · 问题）。"""
    lines = []
    for item in active_items(version).values():
        opts = "/".join(item.options) if item.options else ("p∈[0,1] 或 null" if item.type == "noul"
                                                              else "")
        src = ("（答是/有效选项必须带 source 与 captured_at；可选 source_tier："
               + "/".join(SOURCE_TIERS) + "）") if item.source_required else ""
        lines.append(f"- {item.id} [{item.phase}/{item.type}] {opts}：{item.text}{src}")
    return "\n".join(lines)


def items_markdown(version: str = RUBRIC_VERSION) -> str:
    """`nutmeg rubric items` 与 RULEBOOK「九」用的表。"""
    rows = ["| id | 阶段 | 类型 | 选项 | 效应 | 上限 pp | 来源 | 派生 tier | 版本 |",
            "|---|---|---|---|---|---|---|---|---|"]
    for it in active_items(version).values():
        opts = "/".join(it.options) if it.options else "p∈[0,1]/null"
        cap = cap_at(it, version)
        cap_text = (str(cap) if cap else
                    f"0（{it.cap_until} 退役，原 {it.cap_pp}）" if it.cap_pp else "—")
        rows.append(f"| `{it.id}` | {it.phase} | {it.type} | {opts} | {it.effect or '只记录'} "
                    f"| {cap_text} | {'必填' if it.source_required else '—'} "
                    f"| {it.tier if cap else '—'} "
                    f"| {it.since}{'→' + it.until if it.until else ''} |")
    return "\n".join(rows)
