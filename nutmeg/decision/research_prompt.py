"""Prompt and input brief for one headless JCZQ match investigation."""
from __future__ import annotations

from pathlib import Path

_AGENT_MD = (
    Path(__file__).resolve().parents[2] / ".claude" / "agents" / "jczq-match-analyst.md"
)

RESEARCH_JSON_CONTRACT = """
## 输出契约（硬约束）
只输出 JSON，不要任何前后缀文字。字段与足彩研究 JSON 完全一致：
{"name": str, "summary": str, "confidence": 1-5, "anchor_side": "home|away|none",
 "anchor_integrity": "pass|fail|symmetric_damage",
 "hole_location": {"unit": "attack|creation|spine|defense|goalkeeper|both|none",
     "side": "home|away|both|none", "priced_in": bool, "detail": str},
 "license_questions": {"q1_spine": bool, "q2_route": bool, "q3a_opponent_scores": bool,
                       "q3b_opponent_takes_points": bool, "q4_no_context_flag": bool,
                       "q5_no_rotation_window": bool|null},
 "death_three_proofs": {"home"|"draw"|"away": {"a_no_scoring_mechanism": bool,
     "b_precedent_carrier_gone": bool, "c_anchor_pass": bool, "proof_count": "n/3",
     "verdict": "alive|dead", "detail": str}},
 "directional_flags": [[flag, "3|1|0"]], "nondirectional_flags": [str],
 "crash_markers": [str], "precedents": [["3|1|0", str, "alive|dead|none"]],
 "schedule": {...}, "market_snapshot": {...},
 "stance": {"face": "3|1|0", "structure": "single|double|full", "cover": "3|1|0|null",
     "confidence": 1-5, "falsifier": "一句赛后可核验的作废条件",
     "why_not_market": "none|tilt_evidence|structure", "tilt": null,
     "alt_face": "3|1|0|null", "market_read": "agree|overpriced|underpriced|null"}}
"strength_balance": {"verdict": "home_clear|home_edge|even|away_edge|away_clear",
  "home_state": str, "away_state": str, "style_matchup": str, "tactical_scenarios": [str],
  "underdog_path": {"side": "home|away", "exists": bool, "routes": [str],
                    "strength": "none|weak|real|strong"},
  "events": [{"event": str, "side": "home|away", "direction": "up|down",
              "grade": "minor|moderate|major", "pp": int, "priced_in": bool, "source": str}]}
"sources_consulted": [{"url": "https://…", "site": str, "fetched_at": "ISO",
                       "used_for": ["F_absence_home", "events[0]", …]}],
"stop_rule": {"facts_covered": bool, "counter_searched": bool,
              "counter_note": "搜了什么反例/反方关键词、查到什么（一句）",
              "sources_verifiable": bool, "reason": "coverage|budget|dead_end"}
**研究引用制（2026-10-27）**：所有 `source` / `evidence` 一律写
**完整 URL（https://…）＋原句 ≤40 字**，格式 `URL ｜ 原句`；站点名、「据报道」、「官宣」不算来源
（赛后要能回到那一句）。`sources_consulted` 列你**实际打开过**的页面，每条事实的 URL 必须能在这里
找到；事后回抓失败只记录不拒收。
**停止规则（2026-10-27）**：三条都满足就**立即停止检索、输出 JSON**——
①事实层 7 题全部作答（弃权也是作答）
②针对你的表态**主动搜过一次反例**（反方关键词：对手复出/锚方伤情/上轮同类翻车），
结果写 `counter_note`
③来源可复核（≥3 个 URL、≥2 个站点）。
三条未满足而轮数将尽 → `reason="budget"`、查不到的写「未证实」；
确认查无可查 → `dead_end`。信息越厚不等于越准（26133、WorldCup Arena 2026），不要为凑字数多搜。
**stance.tilt 不用写（写 null）**：拨动由下面的 rubric 逐项派生，why_not_market 由代码改标。
stance.confidence 必须等于顶层 confidence。
宣告 dead 必须三证 3/3；查无先例记 none，不得当 dead。
旗、crash_markers、先例状态只写封闭词典里的短名；叙述写进 summary，不写进标签位。
license_questions.q5_no_rotation_window（2026-10-24，26148 斯图加特欧冠后 3 天六换）：
锚方上一场是**欧战或杯赛**且距本场 ≤4 天、而本场名单在足彩停售前看不到 → false（轮换窗开着）；
锚方近 4 天无欧战/杯赛，或名单已官宣且主力齐 → true；拿不准写 null。只答事实，不推概率。
hole_location 语义绑定：attack = 破门端（中锋/射手）缺；creation = 组织端（前腰/组织核）缺；
spine = 后腰屏障格缺；defense = 中卫对缺；goalkeeper = 门将缺；
both = 攻防两端同时缺（对称崩塌）；none = 无结构性洞。
"premise_corrections"（选填）：[{"subject": "<brief 给的 store id>", "subject_type": "team",
  "field": "<画像笔记 key>", "given": "画像原文（画像为空写空串）", "correct": "你查到的事实",
  "evidence": "来源（站点+标题/URL）", "as_of": "YYYY-MM-DD"}]
只收**持久的实体事实**（现任主帅、联赛级别与位次、欧战/杯赛路径、长期伤缺/报销）；
本场伤停、状态、战意不写这里。subject 只能用 brief 里给出的 store id（"store 无此队"的不写）；
field 纠正已有笔记就沿用它的 key，否则新建带日期的 key（如 coach_2026_10_08）；缺 evidence 的不收。
""".strip()


def rubric_contract() -> str:
    """判断 rubric r1（2026-10-02）：问题表从注册表生成，契约与代码不会漂移。"""
    from nutmeg.decision.rubric_items import RUBRIC_VERSION, question_table

    return f"""
## ★判断 rubric（必答，version "{RUBRIC_VERSION}"）——Jev 形状：类型化问题、概率、可弃权、不解释
顶层字段 "rubric": {{"version": "{RUBRIC_VERSION}", "items": {{<id>: 答案}},
                "belief": {{"3": p, "1": p, "0": p}}}}
答案格式：noul → {{"p": 0–1 或 null, "source": "URL ｜ 原句≤40字", "captured_at": "ISO",
                 "note": str}}；
choice → {{"answer": 选项, "p": 该选项的概率, "source": "URL ｜ 原句≤40字",
           "captured_at": "ISO", "note": str}}。
规则：①一项只答一件事，不要把两件事合在一个来源里；②不知道就弃权（p=null / answer=unknown），
弃权永远合法；③标"必须带来源"的项，答是/有效选项而没有 source+captured_at 会被**强制改为弃权**，
不要把推断写成已确认；④事实层没有任何一项成立 → 拨动预算为 0（跟市场），结构层再多也不补分；
S_anchor_side=none（均势）→ 不拨动；⑤belief 是你自己对 3/1/0 的整体概率，只记账不进 belief。
问题表：
{question_table()}
""".strip()


def system_prompt() -> str:
    body = _AGENT_MD.read_text(encoding="utf-8").split("---", 2)[-1]
    return f"{body.strip()}\n\n{RESEARCH_JSON_CONTRACT}\n\n{rubric_contract()}"


def render_brief(*, code: str, leg: dict, profile_notes: dict) -> str:
    fair = leg["fair"]
    line = leg.get("hhad_line")
    lines = [
        (f"# {code}" if code.startswith("足彩") else f"# 竞彩 {code}")
        + f" · {leg['name']}（{leg.get('competition')}）",
        f"开球（北京）{leg['kickoff_bj']}",
        (
            "去水 fair 主/平/客 = "
            f"{fair['home'] * 100:.1f}% / {fair['draw'] * 100:.1f}% / "
            f"{fair['away'] * 100:.1f}%"
        ),
        f"让球线 {line}" if line is not None else "让球线 无",
        f"主队画像：{profile_notes.get('home') or '（无）'}",
        f"客队画像：{profile_notes.get('away') or '（无）'}",
        # 纠正要能落库（2026-10-08）：26136 十四场查出的主帅更替全留在 summary 散文里，
        # `zucai-premise-corrections` 一条都收不到——subject 必须是 store 的 team_id
        f"主队 store id：{profile_notes.get('home_id') or '（store 无此队）'}｜"
        f"客队 store id：{profile_notes.get('away_id') or '（store 无此队）'}",
        # 前提核实（2026-09-30）：09-28 研究把巴雷拉写成「可用」、伊萨克写成「齐整」，
        # 两条都能一次检索证伪——画像和名气都不是事实，主帅/名单/级别位次/欧战路径必须独立核实
        "必须独立核实（画像未提供或与你查到的事实相悖时以你查到的为准）："
        "现任主帅、本窗实际名单与官宣缺阵、联赛级别与位次、欧战/杯赛路径；"
        "不要按球队名气默认主力齐整。画像里被你证伪的前提，在 summary 首句写「前提纠正：…」，"
        "持久事实同时写进 premise_corrections（subject 用上面的 store id）。",
        "只研究这一场；按输出契约只回 JSON。",
    ]
    return "\n".join(lines)
