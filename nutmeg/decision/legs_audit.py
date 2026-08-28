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

FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}
FACE_ZH = {"3": "主胜", "1": "平", "0": "客胜"}
STRONG_ADJUSTMENT_EVIDENCE_TIERS = frozenset({"official", "confirmed_structural"})
_C8_THRESHOLD = 0.05
_PROBABILITY_TOLERANCE = 1e-9


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

    @property
    def modal(self) -> str:
        return max(FACE_KEYS, key=lambda f: self.fair[FACE_KEYS[f]])

    @property
    def coverage(self) -> float:
        return sum(self.fair[FACE_KEYS[f]] for f in self.faces)

    @property
    def modal_p(self) -> float:
        return self.fair[FACE_KEYS[self.modal]]


@dataclass
class Finding:
    level: str        # ERROR | WARN | INFO
    code: str
    match_no: int | None
    message: str
    since: str        # 这条判据是哪一次亏损换来的


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
        ))
    return sorted(out, key=lambda lg: lg.match_no)
