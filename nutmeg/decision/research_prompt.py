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
                       "q3b_opponent_takes_points": bool, "q4_no_context_flag": bool},
 "death_three_proofs": {"home"|"draw"|"away": {"a_no_scoring_mechanism": bool,
     "b_precedent_carrier_gone": bool, "c_anchor_pass": bool, "proof_count": "n/3",
     "verdict": "alive|dead", "detail": str}},
 "directional_flags": [[flag, "3|1|0"]], "nondirectional_flags": [str],
 "crash_markers": [str], "precedents": [["3|1|0", str, "alive|dead|none"]],
 "schedule": {...}, "market_snapshot": {...},
 "stance": {"face": "3|1|0", "structure": "single|double|full", "cover": "3|1|0|null",
     "confidence": 1-5, "falsifier": "一句赛后可核验的作废条件",
     "why_not_market": "none|tilt_evidence|structure",
     "tilt": null | {"face": "3|1|0", "expires_if": str,
         "evidence": [{"tier": "official|confirmed_structural|inferred|will",
                       "kind": "absence_official|suspension|goalkeeper_change|"
                               "anchor_integrity_fail|lineup_confirmed|venue_anomaly|"
                               "precedent_carrier|rotation_confirmed|"
                               "schedule_congestion|motivation_dead_rubber",
                       "pp": 0-8, "source": str, "captured_at": "ISO"}]},
     "alt_face": "3|1|0|null", "market_read": "agree|overpriced|underpriced|null"}}
"strength_balance": {"verdict": "home_clear|home_edge|even|away_edge|away_clear",
  "home_state": str, "away_state": str, "style_matchup": str, "tactical_scenarios": [str],
  "underdog_path": {"side": "home|away", "exists": bool, "routes": [str],
                    "strength": "none|weak|real|strong"},
  "events": [{"event": str, "side": "home|away", "direction": "up|down",
              "grade": "minor|moderate|major", "pp": int, "priced_in": bool, "source": str}]}
强弱天平必答（strength-v2）：判断目标是两队本场最终强度对比；赔率只作噪声识别与情绪参考，
已被位移吸收的事件不重复计。
underdog_path 的强度用 tilt/shift 落到概率上（认为被低估几 pp 就拨几 pp）；
stance.structure 只是建议，票面结构由下游按判断概率在预算内决定（规则瘦身 2026-09-27）。
tilt 可用多面 shift {"3":pp,"1":pp,"0":pp}（和为 0）；tier 另有 state（本场状态 0–3pp）。
表态块必答：每场押一个面 + 一个表达档 + 一句作废条件；跟市场也要填（why_not_market=none）。
结构优先（2026-10-01）：先把表态面集合（single/double/full）、三证、完整度、弱方路径判清——
这是下游唯一按票面结账的判断（F14）。
**stance.tilt 不用写（写 null）**：拨动由下面的 rubric 逐项派生（2026-10-02 判断 rubric r1），
你给的是"这件事成立的概率 + 来源"，几个 pp 由代码按项目上限算、按结账调。
stance.confidence 必须等于顶层 confidence。
宣告 dead 必须三证 3/3；查无先例记 none，不得当 dead。数字只许引用简报给你的或你查到的实盘。
hole_location 语义绑定：attack = 破门端（中锋/射手）缺；creation = 组织端（前腰/组织核）缺；
spine = 后腰屏障格缺；defense = 中卫对缺；goalkeeper = 门将缺；
both = 攻防两端同时缺（对称崩塌）；none = 无结构性洞。
""".strip()


def rubric_contract() -> str:
    """判断 rubric r1（2026-10-02）：问题表从注册表生成，契约与代码不会漂移。"""
    from nutmeg.decision.rubric_items import RUBRIC_VERSION, question_table

    return f"""
## ★判断 rubric（必答，version "{RUBRIC_VERSION}"）——Jev 形状：类型化问题、概率、可弃权、不解释
顶层字段 "rubric": {{"version": "{RUBRIC_VERSION}", "items": {{<id>: 答案}},
                "belief": {{"3": p, "1": p, "0": p}}}}
答案格式：noul → {{"p": 0–1 或 null, "source": str, "captured_at": "ISO", "note": str}}；
choice → {{"answer": 选项, "p": 该选项的概率, "source": str, "captured_at": "ISO", "note": str}}。
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
        # 前提核实（2026-09-30）：09-28 研究把巴雷拉写成「可用」、伊萨克写成「齐整」，
        # 两条都能一次检索证伪——画像和名气都不是事实，主帅/名单/级别位次/欧战路径必须独立核实
        "必须独立核实（画像未提供或与你查到的事实相悖时以你查到的为准）："
        "现任主帅、本窗实际名单与官宣缺阵、联赛级别与位次、欧战/杯赛路径；"
        "不要按球队名气默认主力齐整。画像里被你证伪的前提，在 summary 首句写「前提纠正：…」。",
        "只研究这一场；按输出契约只回 JSON。",
    ]
    return "\n".join(lines)
