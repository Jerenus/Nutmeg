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
 "anchor_integrity": "pass|fail|symmetric_damage", "hole_location": {...},
 "license_questions": {"q1_spine": bool, "q2_route": bool, "q3a_opponent_scores": bool,
                       "q3b_opponent_takes_points": bool, "q4_no_context_flag": bool},
 "death_three_proofs": {"home"|"draw"|"away": {"a_no_scoring_mechanism": bool,
     "b_precedent_carrier_gone": bool, "c_anchor_pass": bool, "proof_count": "n/3",
     "verdict": "alive|dead", "detail": str}},
 "directional_flags": [[flag, "3|1|0"]], "nondirectional_flags": [str],
 "crash_markers": [str], "precedents": [["3|1|0", str, "alive|dead|none"]],
 "schedule": {...}, "market_snapshot": {...}}
宣告 dead 必须三证 3/3；查无先例记 none，不得当 dead。数字只许引用简报给你的或你查到的实盘。
""".strip()


def system_prompt() -> str:
    body = _AGENT_MD.read_text(encoding="utf-8").split("---", 2)[-1]
    return f"{body.strip()}\n\n{RESEARCH_JSON_CONTRACT}"


def render_brief(*, code: str, leg: dict, profile_notes: dict) -> str:
    fair = leg["fair"]
    line = leg.get("hhad_line")
    lines = [
        f"# 竞彩 {code} · {leg['name']}（{leg.get('competition')}）",
        f"开球（北京）{leg['kickoff_bj']}",
        (
            "去水 fair 主/平/客 = "
            f"{fair['home'] * 100:.1f}% / {fair['draw'] * 100:.1f}% / "
            f"{fair['away'] * 100:.1f}%"
        ),
        f"让球线 {line}" if line is not None else "让球线 无",
        f"主队画像：{profile_notes.get('home') or '（无）'}",
        f"客队画像：{profile_notes.get('away') or '（无）'}",
        "只研究这一场；按输出契约只回 JSON。",
    ]
    return "\n".join(lines)
