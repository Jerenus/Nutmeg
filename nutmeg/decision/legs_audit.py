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
"""开季翻车 regime 标记（2026-08-30 立法,probation）。判断"是否属开季窗/是否升班马刀"
仍在主循环判读层；本词典只锁死标记名,防 agent 自命名膨胀。样本:26112 波鸿 0:1 奥斯纳
布吕克 + 26113 场2(赫尔客胜)/场5(埃弗斯贝格 3:2 勒沃)/场10(弗洛西诺内 0:3)——四刀全部
穿透双选。"""

_C11_GAP_LO = 0.05
_C11_GAP_HI = 0.10
"""C11 虚假方向带：top1−top2 落在 [5pp,10pp) 时模态命中率仅 27.8%(n=18)——
低于三面近均分(<5pp)的 47.4%(n=19)。市场给出一个微弱方向，比它完全给不出方向更危险：
三面接近时作者知道自己在抛硬币，5-10pp 会产生虚假信心。2026-08-30 立法，154 场实证。"""

_C12_DRAW_LO = 0.29
_C12_DRAW_HI = 0.32
_C14_EXCLUSION_P = 0.20
"""C14 昂贵排除：被排面 fair>20% 且死亡三证不齐（锚方 PASS + 该面先例 dead）→ WARN。
26117/26118 六处开出的被排面 fair = 14.8/12.1/23.2/15.5/27.4/(拜仁不胜 17.9)。"""
"""C12 平局低估带：平局 fair 落在 [29%,32%) 时，实开平率 35.7% vs 预期 30.1%(n=14)，
市场系统性低估 +5.6pp；对照 <22% 带市场高估 −5.3pp(n=37)。2026-08-30 立法，154 场实证。"""

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
FACE_ZH = {"3": "主胜", "1": "平", "0": "客胜"}
STRONG_ADJUSTMENT_EVIDENCE_TIERS = frozenset({"official", "confirmed_structural"})
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
        return tuple(rule_id for rule_id in self.rule_ids if rule_id in DEVIATION_RULE_IDS)


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

        # C3 —— 弃模态面
        if lg.modal not in lg.faces:
            out.append(Finding(
                "ERROR", "modal_face_dropped", n,
                f"场{n} {lg.name}：模态面是 {FACE_ZH[lg.modal]}（{lg.modal_p:.1%}），"
                f"但面集合 `{lg.faces}` 把它丢了。",
                "7/29 实证:弃模态面两次全死(001 让负 / 006 受让胜)"))

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


def format_findings(findings: list[Finding], *, issue: str = "") -> str:
    if not findings:
        tag = f"（{issue}）" if issue else ""
        return f"✅ 出票前结构校验通过{tag}：未发现与已落库教训冲突的结构。"
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


def legs_from_dict(payload: dict) -> list[Leg]:
    """从 JSON 载入。legs 是 {场次号: {...}} 映射。"""
    out = []
    for k, v in (payload.get("legs") or {}).items():
        out.append(Leg(
            match_no=int(k), name=v.get("name", ""), faces=str(v["faces"]),
            fair=v["fair"], confidence=int(v.get("confidence", 0)),
            prior=v.get("prior"),
            adjustment_evidence_tiers=tuple(v.get("adjustment_evidence_tiers", [])),
            directional_flags=tuple(tuple(x) for x in v.get("directional_flags", [])),
            nondirectional_flags=tuple(v.get("nondirectional_flags", [])),
            anchor_integrity=v.get("anchor_integrity", "unknown"),
            precedents=tuple(tuple(x) for x in v.get("precedents", [])),
            crash_markers=tuple(v.get("crash_markers", [])),
            tracking_tags=tuple(v.get("tracking_tags", [])),
        ))
    return sorted(out, key=lambda lg: lg.match_no)
