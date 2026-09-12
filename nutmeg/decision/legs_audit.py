"""出票前结构校验 —— 把「反复用新理由撤掉结构保险」这件事变成非零退出码。

**为什么是校验器而不是规则条文。** 同一个动作（在带方向性旗的场次上裸单）已经杀死过四次票：
26098（"20:00 会出首发，届时再定"= 免费期权）→ 8/9 断；
26101（"证据已公开、盘口已定价"）→ 两条 2:2 双死，−¥972；
26102（"旗的幅度被 8 情景扫描实测过"）→ 8/9 断，−¥1,408；
26103（"不过度追求盖率" 被误用成撤保险的授权）→ 出票前自查拦下。

四次的理由各不相同且一次比一次讲究，**这说明散文规则挡不住它**——我总能为下一次找到
第五个更好的理由。所以判据必须离开我的叙述、进到代码里：`audit_legs` 只看
「这条腿有没有方向性旗」和「面集合有几个面」，不听任何论证。

⚠️本模块**不产生判断**，只检查已成型的票面结构是否与已落库的教训冲突。
每条检查都带 `since` 字段指向它是哪一次亏损换来的。
"""
from __future__ import annotations

from dataclasses import dataclass

DIRECTIONAL_LEXICON = frozenset({
    "weak_home_draw_trap", "league_draw_regime", "suspension_breaker_out",
    "self_made_tail", "anchor_shield_out",
})
"""封闭词典（`.claude/agents/jczq-match-analyst.md` 本体）。**只有词典内的方向性旗能阻断单选。**

⚠️为什么要封闭：agent 现场自命名一个旗（26103 出现过 `away_side_draw_utility` /
`leader_draw_sufficient` / `chaser_creator_out` 三个）如果也能阻断出票，那任何 agent 都能
凭空造一个名字把单选堵死——那不是纪律，是瘫痪。新因子须先过双轴检验才进词典（上限 12）。
另：「领先方可接受平」这一机理，26097 判读层已裁定**是机理不是旗**，不得当旗用。"""

CRASH_MARKER_LEXICON = frozenset({
    "opening_promoted_vs_paper",   # 开季窗(前3轮):升班马对阵纸面强队
    "opening_new_coach_debut",     # 开季窗(前3轮):换帅首秀(任一侧为锚方时)
})

TRACKING_TAG_LEXICON = frozenset({
    "promoted_side",            # 升班马(任一方,不限对纸面强队)
    "new_spine_pairing",        # 正路中轴新组合(门将/中卫对/后腰)正赛合练≤2场
    "midfield_pivot_absent",    # 后腰/屏障实名缺阵(≥1主力)
    "post_window_integration",  # 窗口关后≤5天到队的新援进首发/名单
    "pre_european_rotation",    # 欧战前一轮(≤4天)且轮换未证实/已证实
})
"""追踪标签(2026-09-07 立):只入记分牌 tags 组,不改变任何审计动作。
用途=把'升班马/中轴新组合/后腰缺/新援磨合/欧战前轮换'从散文里拿出来,按期累计
正路不胜率与非模态开出率。词典封闭,未知标签只报 WARN 不静默生效。"""

TEAM_TAG_LEXICON = frozenset({
    # 攻端
    "no_natural_striker",      # 无正印中锋/独苗(实名离队+替代者不首发)
    "finishing_broken",        # 终结载体被拆(实名卖出/伤缺≥2名进球载体)
    "set_piece_strong",        # 定位球强(角球/高点/主罚手,结构级)
    "fast_start",              # 开场早破门习惯(≥2场开场15'内)
    "transition_attack",       # 转换/直接进攻型
    "low_block_breaker_weak",  # 破低位块弱(同型失败样本+无穿透型中场)
    # 守端/出球
    "new_gk",                  # 新门将正赛≤3场
    "new_cb_pairing",          # 中卫对新组合正赛≤2场
    "pivot_absent",            # 后腰/屏障实名缺阵
    "makeshift_fullback",      # 临时边卫(客串/改造)
    "high_line_exposed",       # 高位线身后已被打穿(本季样本)
    "set_piece_weak",          # 定位球失球(结构级:高点缺/新组合)
    "buildup_fragile",         # 后场出球脆(主帅自承/门将中卫新)
    "late_collapse",           # 末段崩盘样本(领先被追/补时失球)
    "low_block_home",          # 中低位块+让球权(控球<45%)
    # 风格/情境
    "man_marking_press",       # 人盯人高压(Juric/Amorim型)
    "squad_in_flux",           # 窗口大换血或≤5天新援进首发
    "coach_first_games",       # 新帅≤3场正赛
    "promoted",                # 升班马
    "rotation_risk",           # 欧战前≤4天(到期自动失效)
    "dressing_room_noise",     # 更衣室/转会风波(实名)
    "home_opener",             # 本季首个主场
})
"""球队影响因子标签(2026-09-07 立):挂在队伍上,legs `team_tags` = {"home":[...],"away":[...]}。
不改变审计动作;只做两件事:①按 TEAM_TAG_PAIRINGS 打印对位机制(INFO),喂牌照四问的②③;
②B10 按标签累计入 scoreboard `tags` 组。
权重带由 l-权重表决定(官宣4-8/确证结构3-6/推断0-2),标签本身不带 pp。"""

# 对位机制:攻端标签(一方) × 守端标签(另一方) → 该方有破门机制;
# 反向对位:攻端弱点 × 对方防守风格 → 该方破门机制缺席。
TEAM_TAG_PAIRINGS = (
    ("set_piece_strong", ("new_cb_pairing", "set_piece_weak", "new_gk"),
     "定位球打新组合/高点缺(奥格斯堡1-4法兰型)"),
    ("transition_attack", ("pivot_absent", "high_line_exposed", "makeshift_fullback"),
     "转换打屏障缺/高位线身后(埃弗顿2-2曼联型)"),
    ("fast_start", ("new_cb_pairing", "new_gk"), "快启撞新中卫前15分钟(切尔西型)"),
    ("man_marking_press", ("buildup_fragile", "new_gk", "new_cb_pairing"),
     "高压打新后场出球(蒙扎/萨索洛型)"),
)
TEAM_TAG_COUNTERS = (
    ("low_block_breaker_weak", ("low_block_home",),
     "破低位块弱撞中低位块(曼联0-2赫尔型)→该方破门机制缺席"),
)
"""开季翻车 regime 标记（2026-08-30 立法,probation）。判断"是否属开季窗/是否升班马刀"
仍在主循环判读层；本词典只锁死标记名,防 agent 自命名膨胀。样本:26112 波鸿 0:1 奥斯纳
布吕克 + 26113 场2(赫尔客胜)/场5(埃弗斯贝格 3:2 勒沃)/场10(弗洛西诺内 0:3)——四刀全部
穿透双选。"""

_C3_FLAT_GAP = 0.01
"""C3 模态标签噪音带：top1−top2 < 1pp 时「模态面」只是浮点排序的产物，不是市场判断。

26122 场4 纽伦堡 37.0 / 汉诺威 37.8（差 0.8pp）被判 `modal_face_dropped` ERROR——
但深研本身的结论是「两者差 0.8pp，任何自称能分辨的叙事都是在讲故事」。
在这个带里把某一面叫作「模态」再据此阻断出票，是让代码假装市场给了方向。
→ 该带内降为 WARN（仍然记账，但不阻断），并在消息里点明这是平带不是弃模态。"""

_C11_GAP_LO = 0.05
_C11_GAP_HI = 0.10
"""C11 虚假方向带：top1−top2 落在 [5pp,10pp) 时模态命中率仅 27.8%(n=18)——
低于三面近均分(<5pp)的 47.4%(n=19)。市场给出一个微弱方向，比它完全给不出方向更危险：
三面接近时作者知道自己在抛硬币，5-10pp 会产生虚假信心。2026-08-30 立法，154 场实证。"""

_C12_DRAW_LO = 0.29
_C12_DRAW_HI = 0.32
_C14_EXCLUSION_P = 0.20
_C15_SHARED_EXCLUSION_P = 0.20
"""C15 共享排除：多张票同时排掉同一个 >20% 的面 → 一场杀全部票（组合 WARN）。

26118 三票共享不来梅主胜 23.2%，该面开出，三票同死；26122 四票共享达姆施塔特主胜 34.9%
与 AZ 裸单。**分散注金不等于分散死点**——票面不同但被排面相同时，组合的真实自由度是 1。"""

_EXCLUSION_TAIL_P = 0.15
"""独立面效率表的分级线：≤15% 才算「省钱」，15-20% 是灰带，>20% 是买方差（C14）。
被排面若是 top1（模态面）则不是「排面」而是「翻面」——翻面实证 0/42，另按 C3 处理。"""
"""C14 昂贵排除：被排面 fair>20% 且死亡三证不齐（锚方 PASS + 该面先例 dead）→ WARN。
26117/26118 六处开出的被排面 fair = 14.8/12.1/23.2/15.5/27.4/(拜仁不胜 17.9)。"""
"""C12 平局低估带：平局 fair 落在 [29%,32%) 时，实开平率 35.7% vs 预期 30.1%(n=14)，
市场系统性低估 +5.6pp；对照 <22% 带市场高估 −5.3pp(n=37)。2026-08-30 立法，154 场实证。"""

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
FACE_ZH = {"3": "主胜", "1": "平", "0": "客胜"}
STRONG_ADJUSTMENT_EVIDENCE_TIERS = frozenset({"official", "confirmed_structural"})
_C17_INCONSISTENCY_N = 4
"""C17 读判-票面不一致：单票里「读判判为全包或丢、票面却降成双选」的场次数上限。
26123 F 票六个双选全部落在自判「全包或丢」的场次上（C10×5 + C6×3 共 17 WARN，
被当成可接受成本照出），两处开出。8/08 铁律说预算压缩唯一合法动作是丢整场——
达到本阈值即 ERROR，帽内凑不出可盖的九场时空仓是唯一出口。"""

_READ_CONTRADICTION_MARKS = ("机制缺席", "机制相消", "相消", "无破门机制")
"""I4 读判自相矛盾标记：读判 note 里写了这些词，票面却仍排掉面 → 回读该场（WARN）。
26123 场13 读判原文「米兰 low_block_breaker_weak × 拉齐奥 low_block_home ＝机制缺席」，
构票仍排掉拉齐奥主胜 29.1%，赛中 2-0 落后。答案在手里，构票时没回头看。"""

_C8_THRESHOLD = 0.05
_PROBABILITY_TOLERANCE = 1e-9
DEVIATION_RULE_IDS = frozenset({
    "k",
    "m-单选",
    "conf",
    "h-硬币",
    "打穿共振",
    "l-权重表",
    "l-归零",
    "先例≠form",
    "已定价≠免疫",
    "禁嘴算",
    "伪精确锚定",
    "旗-方向性",
    "旗-无方向",
    "旗-方向纪律",
    "r5-牙口",
    "o-夹心",
    "p-翻车场",
    "r2-废腿",
    "r3-双证",
    "r4-点名",
    "处方优先",
    "排面记录",
    "偏离登记",
    "q-两阶段",
    "8/08铁律",
    "命中率优先",
    "分流",
    "保险≠期权",
    "部署门",
    "j-传导",
    "g-scope",
    "f-结构化",
    "零售信息",
})

DEVIATION_RULE_ALIASES = {
    # 2026-09-06 之后 RULEBOOK 新增/改名的条目 → 既有 canonical ID。
    # 出生事故:26122 构票时按 RULEBOOK 现行条名登记偏离(砍腿序/独立面效率表/死亡三证/
    # m-四问/旗-响应改革),审计因名字不在 frozenset 里判为"无名偏离"WARN——
    # **条文改了名字,判据就静默失效了**。别名表让登记按人读的条名写,校验按 canonical 走。
    "m-四问": "m-单选",
    "旗-响应改革": "旗-方向性",
    "死亡三证": "先例≠form",
    "砍腿序": "8/08铁律",
    "独立面效率表": "已定价≠免疫",
    "临场只加面": "已定价≠免疫",
    "已定价≠可反转": "已定价≠免疫",
    "崩塌双列": "先例≠form",
    "四表共振": "处方优先",
    "四表共振核对": "处方优先",
    "开季翻车regime": "q-两阶段",
    "开季翻车 regime": "q-两阶段",
    "虚假方向带": "k",
    "平局分层错价": "k",
    "H2H-拆分布": "先例≠form",
    "追踪标签": "排面记录",
    "球队影响因子标签": "排面记录",
    "conf": "conf",
}
"""条名别名 → canonical ID。RULEBOOK 条文改名时只加一行，不动 frozenset。"""


def canonical_rule_id(rule_id: str) -> str | None:
    """把人读的条名规约成 canonical ID；无法规约 → None（仍按无名偏离处理）。"""
    key = (rule_id or "").strip()
    if key in DEVIATION_RULE_IDS:
        return key
    mapped = DEVIATION_RULE_ALIASES.get(key)
    if mapped in DEVIATION_RULE_IDS:
        return mapped
    squeezed = key.replace(" ", "")
    mapped = DEVIATION_RULE_ALIASES.get(squeezed)
    return mapped if mapped in DEVIATION_RULE_IDS else None


@dataclass(frozen=True)
class Leg:
    """一条腿的结构描述。fair 用去水概率，faces 用体彩口径字符串（3/1/0 的组合）。"""

    match_no: int
    name: str
    faces: str
    fair: dict            # {"home":..,"draw":..,"away":..}
    confidence: int
    prior: dict | None = None  # 偏移前市场基线；历史票缺失时不追溯触发 C8
    adjustment_evidence_tiers: tuple = ()
    directional_flags: tuple = ()      # 指向具体一面的旗；元素形如 ("self_made_tail", "1")
    nondirectional_flags: tuple = ()   # 只指向"不可测"的旗（确证结构事实级以上才计）
    anchor_integrity: str = "unknown"  # pass | fail | symmetric_damage | unknown
    # 同场地同型先例；元素形如 ("0", "2023-04-27 圣马梅斯 0:1", "alive"|"dead")
    precedents: tuple = ()
    # 开季翻车 regime 标记（CRASH_MARKER_LEXICON 封闭词典;判定在主循环）
    crash_markers: tuple = ()
    # 追踪标签(TRACKING_TAG_LEXICON 封闭词典);不影响审计动作,只作记分牌累计
    tracking_tags: tuple = ()
    # 球队影响因子标签:元素形如 ("home","new_gk");词典 TEAM_TAG_LEXICON;只产 INFO 对位机制
    team_tags: tuple = ()
    # 牌照四问(2026-09-11 拆③):{"q1_spine":bool,"q2_route":bool,
    #   "q3a_opponent_scores":bool,"q3b_opponent_takes_points":bool,"q4_no_context_flag":bool}
    # 缺字段=未答(None),不产 finding;只有显式答 False 才判失分。
    license_questions: dict | None = None
    # 体彩 ttg 形状锚是否存在(法乙等无体彩板面的场次为 False → DC 只有固定 ρ,进球带精度下降)
    ttg_shape_anchor: bool | None = None
    # 该场读判 note 原文；只作 I4 自相矛盾扫描，不参与任何概率计算
    note: str = ""

    @property
    def modal(self) -> str:
        return max(FACE_KEYS, key=lambda f: self.fair[FACE_KEYS[f]])

    @property
    def coverage(self) -> float:
        return sum(self.fair[FACE_KEYS[f]] for f in self.faces)

    @property
    def modal_p(self) -> float:
        return self.fair[FACE_KEYS[self.modal]]

    @property
    def top_gap(self) -> float:
        """top1 − top2。落 [5pp,10pp) 是虚假方向带（C11）。"""
        ranked = sorted(self.fair.values(), reverse=True)
        return ranked[0] - ranked[1]


@dataclass
class Finding:
    level: str        # ERROR | WARN | INFO
    code: str
    match_no: int | None
    message: str
    since: str        # 这条判据是哪一次亏损换来的


@dataclass(frozen=True)
class DeviationRegistration:
    match_no: int
    rule_ids: tuple[str, ...]
    reason: str
    user_override: bool = False

    @property
    def known_rule_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for rule_id in self.rule_ids:
            canonical = canonical_rule_id(rule_id)
            if canonical and canonical not in seen:
                seen.append(canonical)
        return tuple(seen)


def deviation_registrations(payload: dict) -> dict[int, tuple[DeviationRegistration, ...]]:
    raw = payload.get("deviation_registry", [])
    if not isinstance(raw, list):
        raise ValueError("deviation_registry must be a list")
    grouped: dict[int, list[DeviationRegistration]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("deviation_registry entries must be objects")
        rule_ids = item.get("rule_ids", [])
        if not isinstance(rule_ids, list):
            raise ValueError("deviation_registry rule_ids must be a list")
        registration = DeviationRegistration(
            match_no=int(item["match_no"]),
            rule_ids=tuple(str(rule_id) for rule_id in rule_ids),
            reason=str(item.get("reason", "")).strip(),
            user_override=item.get("user_override") is True,
        )
        grouped.setdefault(registration.match_no, []).append(registration)
    return {match_no: tuple(items) for match_no, items in grouped.items()}


def _faces(value: object, *, field: str) -> str:
    faces = str(value) if value is not None else ""
    if len(set(faces)) != len(faces) or not set(faces) <= set(FACE_KEYS):
        raise ValueError(f"{field} faces must contain unique 3/1/0 values")
    return faces


def audit_prescription_deviations(payload: dict) -> list[Finding]:
    """Compare authored prescription and ticket faces; never infer deviation reasons."""
    if "prescription" not in payload:
        return []
    prescription = payload["prescription"]
    legs = payload.get("legs", {})
    if not isinstance(prescription, dict) or not isinstance(legs, dict):
        raise ValueError("prescription and legs must be objects")
    registry = deviation_registrations(payload)
    findings: list[Finding] = []
    match_numbers = sorted({int(key) for key in prescription} | {int(key) for key in legs})
    for match_no in match_numbers:
        prescribed = _faces(prescription.get(str(match_no)), field="prescription")
        leg = legs.get(str(match_no))
        current = _faces(leg.get("faces") if isinstance(leg, dict) else None, field="ticket")
        if set(prescribed) == set(current):
            continue
        registrations = registry.get(match_no, ())
        if any(item.known_rule_ids for item in registrations):
            continue
        supplied = sorted({rule for item in registrations for rule in item.rule_ids})
        label = current or "丢整场"
        findings.append(Finding(
            "WARN",
            "unnamed_prescription_deviation",
            match_no,
            f"场{match_no}：票面 `{label}` 偏离处方 `{prescribed or '无'}`，"
            f"但未引用已登记规则 ID（现有：{','.join(supplied) or '无'}）。"
            f"偏离登记条——无名偏离是「第五个更好的理由」，须命名或撤回。",
            "26103 票8/9 / 26109 干预净差0(2026-08-26 立规则)",
        ))
    return findings


def _flag_faces(leg: Leg) -> set:
    return {f for _, f in leg.directional_flags if f}


def audit_legs(legs: list[Leg]) -> list[Finding]:
    """逐条腿 + 全票结构检查。返回按严重度排序的 findings（ERROR 优先）。"""
    out: list[Finding] = []

    for lg in legs:
        n, single = lg.match_no, len(set(lg.faces)) == 1

        in_lex = [f for f, _ in lg.directional_flags if f in DIRECTIONAL_LEXICON]
        off_lex = [f for f, _ in lg.directional_flags if f not in DIRECTIONAL_LEXICON]

        # C0 —— 词典外的自命名旗:记录待裁决,但**不阻断**
        if off_lex:
            out.append(Finding(
                "WARN", "flag_off_lexicon", n,
                f"场{n} {lg.name}：`{'/'.join(off_lex)}` 不在封闭词典内（agent 自命名）。"
                f"**不阻断单选**，但需判读层显式裁决是否接纳；"
                f"若其机理属「领先方可接受平」，26097 已裁定那是机理不是旗。",
                "26103:agent 自命名旗若能阻断出票,任何 agent 都能凭空堵死单选"))

        # C1 —— 四次亏损换来的那一条。不听任何论证。（只认词典内的旗）
        if single and in_lex:
            names = "/".join(in_lex)
            out.append(Finding(
                "ERROR", "flagged_naked_single", n,
                f"场{n} {lg.name}：带方向性旗（{names}）却裸单。"
                f"m 条——任何方向性旗（无论强弱）→ 至少双选，**fair 高低不得覆盖旗**。",
                "26098 / 26101(−¥972) / 26102(−¥1,408) / 26103 自查"))

        # C2 —— 旗面必须被盖住，否则双选等于没买保险
        missing = {f for fl, f in lg.directional_flags
                   if fl in DIRECTIONAL_LEXICON and f} - set(lg.faces)
        if in_lex and missing and not single:
            faces = "/".join(FACE_ZH[f] for f in sorted(missing))
            out.append(Finding(
                "ERROR", "flag_face_uncovered", n,
                f"场{n} {lg.name}：方向性旗指向 {faces}，但面集合 `{lg.faces}` 没盖住它。"
                f"双选的定义是「模态面 + 旗面」，盖不住旗面的双选不是保险。",
                "26101 场6/场10 双双 2:2"))

        # C3 —— 弃模态面（=翻面）。⚠️2026-09-11 分级：top1−top2 < 1pp 的「模态」是
        # 浮点排序的产物不是市场判断，该带内降 WARN，不阻断（26122 场4 37.0/37.8）。
        if lg.modal not in lg.faces:
            if lg.top_gap < _C3_FLAT_GAP:
                out.append(Finding(
                    "WARN", "modal_face_dropped_flat", n,
                    f"场{n} {lg.name}：面集合 `{lg.faces}` 丢掉了名义模态面 "
                    f"{FACE_ZH[lg.modal]}（{lg.modal_p:.1%}），但 top1−top2 仅 "
                    f"{lg.top_gap * 100:.1f}pp < 1pp——这是**模态标签噪音带**，"
                    f"市场并未给出方向，不按弃模态阻断；仍记账以便复盘该带的排面命中率。",
                    "26122 场4 纽伦堡37.0/汉诺威37.8 差0.8pp(2026-09-11 分级)"))
            else:
                out.append(Finding(
                    "ERROR", "modal_face_dropped", n,
                    f"场{n} {lg.name}：模态面是 {FACE_ZH[lg.modal]}（{lg.modal_p:.1%}），"
                    f"但面集合 `{lg.faces}` 把它丢了（top1−top2 "
                    f"{lg.top_gap * 100:.1f}pp）。这是**翻面**不是排面——翻面三门槛实证 0/42。",
                    "7/29 实证:弃模态面两次全死(001 让负 / 006 受让胜)"))

        # 独立面效率表 —— 排面分级（INFO,不改动作）。把「排掉哪个面、多贵」摆成一行,
        # 免得复盘时才发现预算花在 30% 的面上而 20% 的面被整场丢掉(26122 T1)。
        if len(set(lg.faces)) < 3:
            ladder = []
            for f in sorted(set(FACE_KEYS) - set(lg.faces)):
                p = lg.fair.get(FACE_KEYS[f], 0.0)
                if f == lg.modal:
                    grade = "翻面" if lg.top_gap >= _C3_FLAT_GAP else "平带翻面"
                elif p > _C14_EXCLUSION_P:
                    grade = "买方差"
                elif p > _EXCLUSION_TAIL_P:
                    grade = "灰带"
                else:
                    grade = "省钱"
                ladder.append(f"{FACE_ZH[f]} {p * 100:.1f}%={grade}")
            tail = ""
            if len(set(lg.faces)) == 1:
                # I2 —— 裸单排的是**两个**面，不能用单面 fair 分级。
                exposure = 1.0 - lg.coverage
                grade = ("买方差" if exposure > _C14_EXCLUSION_P
                         else "灰带" if exposure > _EXCLUSION_TAIL_P else "省钱")
                tail = (f" ｜ **裸单总暴露 {exposure * 100:.1f}%={grade}**"
                        f"（裸单按 1−top1 分级：26122 AZ 平 11.1% 被判「省钱」，"
                        f"实际暴露 11.1+6.2=17.3%，一场杀四票）")
            out.append(Finding(
                "INFO", "exclusion_ladder", n,
                f"场{n} {lg.name}：排面分级 " + "、".join(ladder)
                + f"（≤{_EXCLUSION_TAIL_P * 100:.0f}%省钱 / "
                  f"≤{_C14_EXCLUSION_P * 100:.0f}%灰带 / 更高=买方差 / 模态面=翻面）。"
                + tail,
                "2026-09-11 独立面效率表分级(排面≠翻面);2026-09-13 裸单改按总暴露(I2)"))

            # I4 —— 读判自相矛盾。优先用**机器算出来的**对位结论：TEAM_TAG_COUNTERS 判出
            # 某方破门机制缺席时，受益的是对方的取胜面；把那一面排掉即与自己的读判相反。
            # 26123 场13 的「机制缺席」只写在对话里、没进 note，靠扫 note 抓不到——
            # 所以主触发器必须是 team_tags，note 关键词只作兜底。
            absent = set()
            tags_by_side = {
                side: {t for s_, t in lg.team_tags if s_ == side}
                for side in ("home", "away")
            }
            for atk_side, def_side in (("home", "away"), ("away", "home")):
                for weak, styles, _label in TEAM_TAG_COUNTERS:
                    if weak in tags_by_side[atk_side] and any(
                            st in tags_by_side[def_side] for st in styles):
                        absent.add(atk_side)
            beneficiary = {"home": "0", "away": "3"}   # 主队机制缺席 → 客胜受益，反之亦然
            contradicted = sorted(
                beneficiary[side] for side in absent
                if beneficiary[side] not in lg.faces)
            hits = [m for m in _READ_CONTRADICTION_MARKS if m in lg.note]
            if contradicted:
                out.append(Finding(
                    "WARN", "excluded_face_contradicts_read", n,
                    f"场{n} {lg.name}：对位机制判出 "
                    f"{'/'.join('主队' if x == 'home' else '客队' for x in sorted(absent))}"
                    f"破门机制缺席，受益面是 "
                    f"{'、'.join(FACE_ZH[f] for f in contradicted)}，票面却把它排掉了。"
                    f"排面与本场读判相反——回读该场对位机制再定。",
                    "26123 场13:米兰破低位块机制缺席,构票仍排拉齐奥主胜 29.1%(2-0 落后)"))
            elif hits:
                dropped = "、".join(
                    FACE_ZH[f] for f in sorted(set(FACE_KEYS) - set(lg.faces)))
                out.append(Finding(
                    "WARN", "excluded_face_contradicts_read", n,
                    f"场{n} {lg.name}：读判 note 含「{'/'.join(hits)}」，"
                    f"票面仍排掉 {dropped}。"
                    f"请回读该场 note 确认被排面不是那条「机制缺席」指向的面。",
                    "26123 场13:读判写了米兰破低位块机制缺席,构票仍排拉齐奥主胜 29.1%"))

        # C4 —— conf3 是"有理由但不够硬"的自我说服黑洞
        if single and lg.confidence <= 3:
            out.append(Finding(
                "ERROR", "low_conf_single", n,
                f"场{n} {lg.name}：conf{lg.confidence} 裸单。"
                f"实证 conf4 69% > conf2 50% > **conf3 32%**。",
                "判决表 m 条"))

        # C5 —— 锚方结构 FAIL 还裸单，就是 26102 本菲卡
        if single and lg.anchor_integrity == "fail":
            out.append(Finding(
                "ERROR", "broken_anchor_single", n,
                f"场{n} {lg.name}：锚方结构完整度 FAIL 却裸单。"
                f"锚越强、未定价的结构漏洞越值钱——fair 高是加倍重视的理由，不是忽略的理由。",
                "26102 本菲卡 fair 85.8% → 2:2"))

        # 牌照四问③拆分（2026-09-11 入码, probation）：
        # 「对手有破门机制」与「对手有取分机制」是两件事。26121 巴萨/巴黎/拜仁三条牌照裸单
        # 的③全部失分在"对手会进球"（三场对手合计进 2 球）却 3/3 兑现；26122 场13 AZ 同型。
        # → q3a(对手会进球) 只封**零封/让胜**类表达，不封胜负负腿；
        #   只有 q3b(对手会取分:能拿平或赢) 成立时，裸单才真正被封。
        lq = lg.license_questions or {}
        q3a = lq.get("q3a_opponent_scores")
        q3b = lq.get("q3b_opponent_takes_points")
        if single and q3b is True:
            out.append(Finding(
                "WARN", "license_q3b_opponent_takes_points", n,
                f"场{n} {lg.name}：牌照四问③b「对手有取分机制」成立却裸单。"
                f"③b 是真正封牌照的那一半（对手能拿平或赢），不是③a（对手会进球）。",
                "2026-09-11 四问③拆分(26121 三牌照③a失分仍3/3)"))
        if single and q3a is True and q3b is False:
            out.append(Finding(
                "INFO", "license_q3a_only", n,
                f"场{n} {lg.name}：四问③仅③a成立（对手会进球、但无取分机制）——"
                f"该失分只杀**零封/让胜/大胜**类表达，不杀胜负负腿，裸单不因此降级。",
                "26121 巴萨/巴黎/拜仁 3/3 + 26122 场13 AZ(2026-09-11 入码)"))

        # ttg 形状锚缺失（法乙等无体彩板面场次）：DC 只有固定 ρ 拟合，进球带精度下降。
        # 不改动作,只在票面上标出来——免得把这些场的进球轴判读当成与其他场同精度。
        if lg.ttg_shape_anchor is False:
            out.append(Finding(
                "INFO", "ttg_shape_degraded", n,
                f"场{n} {lg.name}：无体彩 ttg 形状锚（板面未对齐），DC 仅固定 ρ 拟合，"
                f"进球带与让球三路精度下降；该场进球轴结论不与有锚场同权。",
                "26122 法乙五场无体彩对齐(2026-09-11 标注)"))

        # C6 —— 确证级无方向性旗 = "我判不动往哪碎" → 该全包
        if lg.nondirectional_flags and len(set(lg.faces)) < 3:
            names = "/".join(lg.nondirectional_flags)
            out.append(Finding(
                "WARN", "undecidable_not_full", n,
                f"场{n} {lg.name}：带无方向性旗（{names}）= 判不动往哪碎，但只买了 "
                f"{len(set(lg.faces))} 面。降格场的第 3 面开出频率高（26101 实测 7 场中 5 场）。",
                "8/08:全包场只能保留或整场丢掉,不许降档"))

        # C11 —— 虚假方向带:top1−top2 落 [5pp,10pp) 且未全包（2026-08-30 立法,probation）
        if _C11_GAP_LO <= lg.top_gap < _C11_GAP_HI and len(set(lg.faces)) < 3:
            out.append(Finding(
                "WARN", "false_direction_band", n,
                f"场{n} {lg.name}：top1−top2 = {lg.top_gap * 100:.1f}pp 落在虚假方向带"
                f"（5-10pp），该带模态命中率仅 27.8%(n=18)，**低于三面近均分带的 47.4%**。"
                f"市场给出微弱方向比给不出方向更危险——三面接近时你知道在抛硬币，"
                f"5-10pp 会产生虚假信心。合法响应=全包或丢整场。",
                "2026-08-30 立法:154 场实证,gap12 分层最低命中带"))

        # C12 —— 平局低估带:平局 fair ∈ [29%,32%) 却未买平（2026-08-30 立法,probation）
        draw_p = lg.fair[FACE_KEYS["1"]]
        if _C12_DRAW_LO <= draw_p < _C12_DRAW_HI and "1" not in lg.faces:
            out.append(Finding(
                "WARN", "draw_underpriced_band", n,
                f"场{n} {lg.name}：平局 fair {draw_p * 100:.1f}% 落在市场低估带"
                f"（29-32%：实开 35.7% vs 预期 30.1%，n=14，低估 +5.6pp），但面集合 "
                f"`{lg.faces}` 未买平。对照 <22% 带市场反而高估 −5.3pp——平局的错价是分层的，"
                f"不是全局的。",
                "2026-08-30 立法:154 场实证,平局 fair 分层偏差"))

        # 追踪标签词典封闭:未知名只报 WARN,不静默生效(2026-09-07 立)
        unknown_tags = [t for t in lg.tracking_tags if t not in TRACKING_TAG_LEXICON]
        if unknown_tags:
            out.append(Finding(
                "WARN", "tracking_tag_off_lexicon", n,
                f"场{n} {lg.name}：tracking_tags 含未注册标签 {unknown_tags}。"
                f"追踪标签只接受 TRACKING_TAG_LEXICON；未知名不入记分牌。",
                "2026-09-07 追踪标签立法"))

        # 球队影响因子标签:词典封闭 + 对位机制 INFO(2026-09-07 立;不改审计动作)
        bad_team_tags = [t for _side, t in lg.team_tags if t not in TEAM_TAG_LEXICON]
        if bad_team_tags:
            out.append(Finding(
                "WARN", "team_tag_off_lexicon", n,
                f"场{n} {lg.name}：team_tags 含未注册标签 {bad_team_tags}。"
                f"只接受 TEAM_TAG_LEXICON；未知名不入记分牌。",
                "2026-09-07 球队标签立法"))
        if lg.team_tags:
            side_zh = {"home": "主队", "away": "客队"}
            tags_of = {
                side: {t for s_, t in lg.team_tags if s_ == side}
                for side in ("home", "away")
            }
            hits = []
            for atk_side, def_side in (("home", "away"), ("away", "home")):
                for atk, defs, label in TEAM_TAG_PAIRINGS:
                    if atk in tags_of[atk_side]:
                        matched = [d for d in defs if d in tags_of[def_side]]
                        if matched:
                            hits.append(
                                f"{side_zh[atk_side]} {atk} → {side_zh[def_side]} "
                                f"{'/'.join(matched)}：{label}")
                for weak, styles, label in TEAM_TAG_COUNTERS:
                    if weak in tags_of[atk_side] and any(st in tags_of[def_side] for st in styles):
                        hits.append(
                            f"{side_zh[atk_side]} {weak} × {side_zh[def_side]} 风格：{label}")
            if hits:
                out.append(Finding(
                    "INFO", "pairing_mechanism", n,
                    f"场{n} {lg.name}：对位机制 " + "；".join(hits) + "。喂牌照四问②③,不改动作。",
                    "2026-09-07 球队标签立法"))

        # C9 —— 开季翻车 regime:升班马刀/换帅首秀,表达只许全包或丢场（2026-08-30 立法,probation）
        known_markers = [m for m in lg.crash_markers if m in CRASH_MARKER_LEXICON]
        unknown_markers = [m for m in lg.crash_markers if m not in CRASH_MARKER_LEXICON]
        if unknown_markers:
            out.append(Finding(
                "WARN", "crash_marker_off_lexicon", n,
                f"场{n} {lg.name}：开季翻车标记不在封闭词典：{'/'.join(unknown_markers)}。",
                "C9 crash_markers 只接受注册词典；未知名不得静默生效"))
        if known_markers and len(set(lg.faces)) < 3:
            out.append(Finding(
                "WARN", "opening_upset_double", n,
                f"场{n} {lg.name}：带开季翻车标记（{'/'.join(known_markers)}）却只买了 "
                f"{len(set(lg.faces))} 面。开季窗结构未成型是赛前可识别的 regime——"
                f"升班马/换帅刀的合法表达只有全包或丢整场。",
                "26112 波鸿+26113 场2/5/10:四把开季刀全部穿透双选(2026-08-30 立法)"))

        # C10 —— 旗只报脆不报方向:方向性旗场的双选(含盖旗面)降为 WARN（2026-08-30 立法,probation）
        if in_lex and len(set(lg.faces)) == 2:
            out.append(Finding(
                "WARN", "flagged_double_not_full", n,
                f"场{n} {lg.name}：带方向性旗（{'/'.join(in_lex)}）以双选表达。"
                f"旗的实证是只会报『脆』不会报方向（shield 方向 0/8、26113 四旗指平场零平、"
                f"保险面 10/50≈公允价无增益）——盖旗面买不到方向增益。合法响应=全包或丢整场；"
                f"C1 裸单仍是 ERROR 底线。",
                "26113 P3 四旗零平+断腿全开第三面(2026-08-30 立法)"))

        # C7 —— 被排面上有同场地同型的**活**先例:r3 双证的机械化。
        # 26105 场3(西布罗上季卡罗路 0:1 客胜先例被当 form 归零→客面开出杀全部票版)与
        # 26109 场10(塞维 2023-04-27 圣马梅斯 0:1 先例躺在深研笔记里、因排面来自处方双选
        # 而非"主动砍腿"未触发 r3→塞维 1:3)是同一死法:**先例是机制样本不是 form,
        # 不适用 0pp 归零;而检查若只靠散文触发,就会在"默认形状"里静默失效。**
        if len(set(lg.faces)) < 3 and lg.precedents:
            excluded = set(FACE_KEYS) - set(lg.faces)
            hits = [(f, s) for f, s, status in lg.precedents
                    if f in excluded and status == "alive"]
            for f, s in hits:
                out.append(Finding(
                    "WARN", "excluded_face_live_precedent", n,
                    f"场{n} {lg.name}：被排面 {FACE_ZH[f]} 存在同场地同型**活先例**（{s}）。"
                    f"r 条 3——先例是机制样本，砍带先例的面需「先例+钱流」双证；"
                    f"双证不齐 → 盖住该面或整场丢掉。",
                    "26105 场3 西布罗 / 26109 场10 塞维(2026-08-23 立规则,WARN 级)"))

        # C13 —— 锚方完整度 FAIL 却排掉一面（死亡三证(c)的机械化, 2026-09-06 立法, probation）。
        # 26118 场8:莱比锡中场四缺+锋线全新=完整度 fail 已写在读判里,主循环仍以"不来梅 14 战不胜"
        # 把主胜判死→3:1。裸单层早有 C5,双选层此前无码,判死面靠人工先例字段,garbage-in 静默失效。
        if len(set(lg.faces)) == 2 and lg.anchor_integrity == "fail":
            excluded = sorted(set(FACE_KEYS) - set(lg.faces))
            ex = excluded[0] if excluded else ""
            out.append(Finding(
                "WARN", "broken_anchor_double", n,
                f"场{n} {lg.name}：锚方结构完整度 FAIL 却以双选排掉 {FACE_ZH.get(ex, ex)}"
                f"（{lg.fair.get(FACE_KEYS.get(ex, ''), 0.0) * 100:.1f}%）。"
                f"死亡三证(c)——判一个面死,锚方必须完整;锚方有洞的场只许全包或丢整场。",
                "26118 场8 不来梅 3:1 莱比锡(2026-09-06 立法,WARN 级)"))

        # C14 —— 昂贵排除:被排面 fair>20% 且死亡三证不齐（2026-09-06 立法, probation）。
        # 三证=机制缺席/先例载体不在(precedents 该面 dead)/锚方完整度 PASS;代码只能核后两证。
        # 26117 开出的被排面是 14.8/12.1,26118 是 23.2/15.5/27.4——>20% 的排除是买方差不是省钱。
        if len(set(lg.faces)) < 3:
            excluded = set(FACE_KEYS) - set(lg.faces)
            dead_faces = {f for f, _s, status in lg.precedents if status == "dead"}
            costly = [
                f for f in sorted(excluded)
                if lg.fair.get(FACE_KEYS[f], 0.0) > _C14_EXCLUSION_P
                and not (lg.anchor_integrity == "pass" and f in dead_faces)
            ]
            if costly:
                desc = "、".join(
                    f"{FACE_ZH[f]} {lg.fair.get(FACE_KEYS[f], 0.0) * 100:.1f}%" for f in costly)
                out.append(Finding(
                    "WARN", "expensive_exclusion", n,
                    f"场{n} {lg.name}：被排面 {desc} 超过 {_C14_EXCLUSION_P * 100:.0f}% "
                    f"且死亡三证不齐"
                    f"（需锚方完整度 PASS 且该面先例记 dead）。"
                    f"独立面效率表——>20% 的排除是买方差不是省钱;合法响应=盖住该面或整场丢掉。",
                    "26118 场8/14/2 三处被排面 23.2/15.5/27.4 全开(2026-09-06 立法,WARN 级)"))

        # C8 —— 净偏移达到 5pp 时，必须由作者显式声明官宣或确证结构级证据锚。
        # 只检查结构化等级，不从 URL、quote 或自然语言猜权威性。
        if lg.prior is not None:
            offset = sum(
                abs(lg.fair.get(key, 0.0) - lg.prior.get(key, 0.0))
                for key in FACE_KEYS.values()
            ) / 2
            has_strong_anchor = bool(
                STRONG_ADJUSTMENT_EVIDENCE_TIERS
                & set(lg.adjustment_evidence_tiers)
            )
            if offset + _PROBABILITY_TOLERANCE >= _C8_THRESHOLD and not has_strong_anchor:
                tiers = "/".join(lg.adjustment_evidence_tiers) or "未登记"
                out.append(Finding(
                    "WARN", "pseudo_precision_anchor", n,
                    f"场{n} {lg.name}：belief 相对 prior 净偏移 {offset * 100:.1f}pp，"
                    f"但证据等级仅为 `{tiers}`，没有 official 或 confirmed_structural 锚。"
                    f"l 条——纯推断/战意不得堆叠成伪精确偏移；由主循环复核证据等级或归零。",
                    "2026-08-26:用模糊代替精确(C8 WARN)"))

    # ── 全票级：模态组合错配 ────────────────────────────────────────────
    singles = [lg for lg in legs if len(set(lg.faces)) == 1]
    if singles:
        exp = sum(lg.modal_p for lg in singles if lg.faces == lg.modal)
        n_modal = sum(1 for lg in singles if lg.faces == lg.modal)
        if n_modal >= 3 and exp < n_modal - 1.0:
            out.append(Finding(
                "WARN", "modal_stack_mismatch", None,
                f"模态组合错配：{n_modal} 条模态裸单，但它们的**期望命中合计只有 {exp:.2f} 条**"
                f"（平均 {n_modal - exp:.2f} 条模态不开）。"
                f"「每条腿各自最可能」≠「它们同时发生也最可能」——"
                f"全模态是一个特定的联合情景，"
                f"在领先方乐于不输的板面上，恰恰是结构反对的那一个。",
                "26103 自查:9 条模态期望仅中 5.13"))

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    return sorted(out, key=lambda f: (order[f.level], f.match_no or 0))


def audit_read_ticket_consistency(findings: list[Finding]) -> list[Finding]:
    """C17 —— 读判说「全包或丢」、票面却降双选的场次达阈值即 ERROR（2026-09-13 入码）。

    C10(flagged_double_not_full) 与 C6(undecidable_not_full) 各自只是 WARN，单看都能被
    「这一处可以接受」说服；**26123 F 票把六个双选全放在自判「全包或丢」的场次上**，
    审计报了 17 个 WARN 照样出票，两处开出。8/08 铁律：预算压缩唯一合法动作是丢整场。
    """
    marks = [f for f in findings
             if f.code in ("flagged_double_not_full", "undecidable_not_full")]
    if len(marks) < _C17_INCONSISTENCY_N:
        return []
    seen: list[int] = []
    for f in marks:
        if f.match_no is not None and f.match_no not in seen:
            seen.append(f.match_no)
    return [Finding(
        "ERROR", "read_ticket_inconsistency", None,
        f"本票 {len(marks)} 处「读判判全包或丢、票面降双选」"
        f"（场{'/'.join(str(x) for x in sorted(seen))}），达阈值 {_C17_INCONSISTENCY_N}。"
        f"8/08 铁律——预算压缩唯一合法动作是**丢整场**，不是降双选；"
        f"帽内凑不出可盖的九场时，空仓是合法且唯一出口。",
        "26123 F 票六双选全落在自判全包或丢的场次上(17 WARN 照出),场4/场13 开出")]


def audit_shared_exclusions(tickets: dict[str, list[Leg]]) -> list[Finding]:
    """C15 —— 多票共享同一个 >20% 被排面（组合 WARN, 2026-09-11 入码, probation）。

    tickets = {票名: [Leg, ...]}。**分散注金不等于分散死点**：票面不同但被排面相同时，
    组合的真实自由度是 1，一场开出杀全部票。26118 三票共享不来梅主胜 23.2%（开出，三票同死）；
    26122 四票共享达姆施塔特主胜 34.9% 与 AZ 裸单。
    """
    if len(tickets) < 2:
        return []
    shared: dict[tuple[int, str], list[str]] = {}
    meta: dict[tuple[int, str], tuple[str, float]] = {}
    for name, legs in tickets.items():
        for lg in legs:
            if len(set(lg.faces)) >= 3:
                continue
            for f in set(FACE_KEYS) - set(lg.faces):
                p = lg.fair.get(FACE_KEYS[f], 0.0)
                if p <= _C15_SHARED_EXCLUSION_P:
                    continue
                key = (lg.match_no, f)
                shared.setdefault(key, []).append(name)
                meta.setdefault(key, (lg.name, p))
    out: list[Finding] = []
    for (match_no, face), names in sorted(shared.items()):
        if len(names) < 2:
            continue
        leg_name, p = meta[(match_no, face)]
        out.append(Finding(
            "WARN", "shared_exclusion", match_no,
            f"场{match_no} {leg_name}：{len(names)} 张票共享同一个 >"
            f"{_C15_SHARED_EXCLUSION_P * 100:.0f}% 被排面 {FACE_ZH[face]} "
            f"（{p * 100:.1f}%，票：{'/'.join(names)}）。"
            f"该面开出即同时杀死全部这些票——分散注金不等于分散死点。",
            "26118 三票共享不来梅23.2%全灭 / 26122 四票共享(2026-09-11 入码)"))

    # C15b —— 共享裸单（不看 P）。26122 四张票在场13 AZ 上是同一条裸单：一场平局
    # (11.1%) 同时杀四票。裸单被排掉的是两个面,合计 P 常常 <20%,C15 的价格门槛看不见它;
    # 但"四张票押在同一件 82% 的事上"意味着全日资金只有一件事的自由度——
    # 该报的不是"这个面贵不贵",而是"全部票同时死于此的概率是多少"。
    naked: dict[int, list[str]] = {}
    naked_meta: dict[int, tuple[str, float]] = {}
    for name, legs in tickets.items():
        for lg in legs:
            if len(set(lg.faces)) != 1:
                continue
            naked.setdefault(lg.match_no, []).append(name)
            naked_meta.setdefault(lg.match_no, (lg.name, 1.0 - lg.coverage))
    for match_no, names in sorted(naked.items()):
        if len(names) < 2:
            continue
        leg_name, p_dead = naked_meta[match_no]
        out.append(Finding(
            "WARN", "shared_naked_single", match_no,
            f"场{match_no} {leg_name}：{len(names)} 张票共享同一条裸单"
            f"（票：{'/'.join(names)}）。该场非正路概率 {p_dead * 100:.1f}% = "
            f"这些票**同时**死于此的概率；票数再多，在这一场上只有一件事的自由度。",
            "26122 场13 AZ 82.7 平:四票共享裸单一场全灭(2026-09-12 入码)"))
    return out


def format_findings(findings: list[Finding], *, issue: str = "") -> str:
    # INFO 不是发现,是随票打印的参考表(对位机制/排面分级/ttg 锚)。只有 INFO 时仍算通过,
    # 否则"排面分级"这类纯报告会把干净票面渲染成有问题——校验器的输出必须与它的语义一致。
    blocking_or_warn = [f for f in findings if f.level != "INFO"]
    if not blocking_or_warn:
        tag = f"（{issue}）" if issue else ""
        head = f"✅ 出票前结构校验通过{tag}：未发现与已落库教训冲突的结构。"
        infos = [f"ℹ️ [{f.code}] {f.message}" for f in findings]
        return "\n".join([head, *infos]) if infos else head
    lines = [f"出票前结构校验{'（' + issue + '）' if issue else ''}："
             f"{sum(1 for f in findings if f.level == 'ERROR')} 个 ERROR / "
             f"{sum(1 for f in findings if f.level == 'WARN')} 个 WARN", ""]
    for f in findings:
        icon = {"ERROR": "❌", "WARN": "⚠️", "INFO": "ℹ️"}[f.level]
        lines.append(f"{icon} [{f.code}] {f.message}")
        lines.append(f"    ← {f.since}")
    return "\n".join(lines)


def has_blocking(findings: list[Finding]) -> bool:
    return any(f.level == "ERROR" for f in findings)


def _directional_flags(raw: object) -> tuple[tuple[str, str], ...]:
    """规约方向性旗入口。

    接受三种写法：`"self_made_tail"`（裸名）/ `["self_made_tail","1"]` / `{"flag":..,"face":..}`。
    裸名默认指向**平**（"1"）——封闭词典里五面旗有四面机理指平，另一面 shield 也指平，
    所以默认值不是猜测而是词典本身的形状；要指别的面必须显式写。
    出生事故：26122 把旗写成裸字符串导致 `audit_legs` 抛 `too many values to unpack`，
    整个审计门静默退出码 1 却零 findings——**校验器自己崩掉比不校验更危险**。
    """
    items: list[tuple[str, str]] = []
    for x in raw or ():
        if isinstance(x, str):
            items.append((x, "1"))
        elif isinstance(x, dict):
            items.append((str(x.get("flag") or x.get("name") or ""),
                          str(x.get("face") or "1")))
        else:
            seq = list(x)
            if len(seq) == 1:
                items.append((str(seq[0]), "1"))
            elif len(seq) >= 2:
                items.append((str(seq[0]), str(seq[1])))
    return tuple(items)


def legs_from_dict(payload: dict) -> list[Leg]:
    """从 JSON 载入。legs 是 {场次号: {...}} 映射。"""
    out = []
    for k, v in (payload.get("legs") or {}).items():
        out.append(Leg(
            match_no=int(k), name=v.get("name", ""), faces=str(v["faces"]),
            fair=v["fair"], confidence=int(v.get("confidence", 0)),
            prior=v.get("prior"),
            adjustment_evidence_tiers=tuple(v.get("adjustment_evidence_tiers", [])),
            directional_flags=_directional_flags(v.get("directional_flags")),
            license_questions=v.get("license_questions"),
            ttg_shape_anchor=v.get("ttg_shape_anchor"),
            note=str(v.get("note", "") or ""),
            nondirectional_flags=tuple(v.get("nondirectional_flags", [])),
            anchor_integrity=v.get("anchor_integrity", "unknown"),
            precedents=tuple(tuple(x) for x in v.get("precedents", [])),
            crash_markers=tuple(v.get("crash_markers", [])),
            tracking_tags=tuple(v.get("tracking_tags", [])),
            team_tags=tuple(
                (side, tag)
                for side in ("home", "away")
                for tag in (v.get("team_tags") or {}).get(side, [])
            ),
        ))
    return sorted(out, key=lambda lg: lg.match_no)
