"""研究/判读的封闭词典（旗、崩塌标记、先例状态、追踪与球队标签）。

2026-10-13 起本模块**只剩词典**。此前它是出票审计门（`decision-audit-legs` / 裁决单 /
面集展开 / C 码检查，约 1,400 行）：2026-09-27 规则瘦身后判断类码全部降为记录、ERROR
通道为空，10-03 / 10-08 两轮审计都建议删除但被自动模式拦下，10-13 经 Jun 授权删除
（`docs/superpowers/evidence/2026-10-13-audit-gate-removal.md`）。出票前唯一的机器否决
是 `betslip preview` 的 V1/V2（RUNBOOK B9c）。

词典仍由 `research_intake`（入库桥剥离词典外标签并留痕）与 `read_builder` 引用；
词典封闭，未知标签只报 WARN 不静默生效。
"""
from __future__ import annotations

PRECEDENT_STATUSES = frozenset({"alive", "dead", "none"})
"""先例状态词典。`none` = **查无先例**，与 `dead`（有先例、载体已不在阵）是两回事。

出生事故 2026-09-17：C14 的豁免写成「锚方 PASS ∧ 该面先例 dead」，而深研 agent
把"这个面根本没有同型先例"也记成 `dead` —— 26128 场14 原文就是
`["1", "无——马拉卡纳同型对独立谷不存在 90' 平局先例", "dead"]`，agent 自己还在
detail 里警告过「这是『无先例可载』而非『载体死亡』，请勿当作强证据使用」。
于是"查无先例"与"先例载体已死"拿到同一个豁免，**举证责任被反过来了**：
死亡三证(b) 要的是"载体已不在阵"这个**积极证据**，而"没查到"是证据的缺席。

26127 场3 / 场7 因此被报成干净，而研究说平局才是机制最顺的一面；场7 实开 0-0。"""

NONDIRECTIONAL_LEXICON = frozenset({
    "undecided_second_leg", "source_disagreement", "venue_anomaly",
    "two_way_instability", "dressing_room_turmoil",
    "information_asymmetry",
})
"""无方向旗封闭词典。命中且票面非全包 → C6（`undecidable_not_full`）。

`information_asymmetry` 由 Jun 于 2026-09-17 裁定入词典。它与 C6 的语义天然同构：
**一侧信息充分而另一侧近乎零覆盖时，分布更宽而不是均值更低**——它不报方向，
只报"判不动"，合法响应因此是降格全包或丢整场。出生事故：26125-26128 深研 agent
连续四期照写此名（26128 场1 申花四人实名缺阵而淡滨尼伤停零覆盖、场3 史上首次交手、
场8 托伦斯官网不发伤情且欧战注册阵容≠联赛阵容），词典不收 → **证据每期都在产生
却每期都被丢掉**。

⚠️词典的家在本模块（审计门才是执行方），`read_builder` 再导出。
2026-09-17 之前它只住在 `read_builder` 里，而**审计对无方向旗根本不查词典**——
任何自命名的字符串都能触发 C6、逼出全包，与「agent 自命名的旗不得堵死出票」
这条封闭词典的立法意图正好相反。C0 现已对称覆盖两组旗。"""

V2 = "【strength-v2 降为提示】"
"""2026-09-26 Jun 批准的 strength-v2：立论已被闭环证伪的码降为 WARN，只作提示不阻断。"""

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
用途:喂牌照四问的②③;B10 按标签累计入 scoreboard `tags` 组。
权重带由 l-权重表决定(官宣4-8/确证结构3-6/推断0-2),标签本身不带 pp。"""
