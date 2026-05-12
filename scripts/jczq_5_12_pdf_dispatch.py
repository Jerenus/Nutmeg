"""5/12 one-shot: render 5/12 final-plan.json (new 6-ticket schema) to PDF
and dispatch via Nutmeg Telegram bot. Adapter on top of
`jczq_final_plan_pdf_dispatch.render_pdf` which expects the 5/11 schema.

Usage:
    set -a; source .env; set +a
    uv run python scripts/jczq_5_12_pdf_dispatch.py --dispatch
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Reuse the existing renderer + bot client.
from scripts.jczq_final_plan_pdf_dispatch import render_pdf
from nutmeg.interfaces.bot.telegram import TelegramBotClient


def adapt_5_12_plan(plan_5_12: dict) -> dict:
    """Transform the 5/12 final-plan.json schema into the legacy
    schema expected by jczq_final_plan_pdf_dispatch.render_pdf."""

    matchup_parts = {}
    for t in plan_5_12["tickets"]:
        for L in t["legs"]:
            m = L.get("matchup", "")
            if " vs " in m:
                home, away = m.split(" vs ", 1)
                matchup_parts[L["match_no"]] = (home.strip(), away.strip())

    tickets_legacy = []
    favorite_ticket_id = plan_5_12.get("top_pick_ranking", [{}])[0].get("ticket", "C")
    for t in plan_5_12["tickets"]:
        legs_legacy = []
        for L in t["legs"]:
            home, away = matchup_parts.get(L["match_no"], ("", ""))
            legs_legacy.append({
                "match_no": L["match_no"],
                "league": L.get("league", ""),
                "home": home,
                "away": away,
                "pool": L["pool"],
                "pick": L["pick"],
                "odds": L["odds"],
                "poisson_edge": L.get("poisson_edge"),
                "goal_line": L.get("goal_line"),
                "logic": "",
            })
        joint_p = t.get("joint_true_prob")
        if joint_p is None:
            single_p = t["legs"][0].get("true_prob") if len(t["legs"]) == 1 else None
            if single_p is None:
                # Estimate from stake / odds / ev_estimate.
                stake = float(t["stake"])
                payout = float(t["total_odds"]) * stake
                if payout > 0:
                    joint_p = (float(t.get("ev_estimate", 0.0)) + stake) / payout
                else:
                    joint_p = 0.0
            else:
                joint_p = single_p
        payout = float(t["total_odds"]) * float(t["stake"])
        tickets_legacy.append({
            "id": t["id"],
            "name": t["name"],
            "stake": t["stake"],
            "total_odds": t["total_odds"],
            "theoretical_payout": payout,
            "hit_probability": joint_p,
            "expected_value": t.get("ev_estimate", 0.0),
            "favorite": (t["id"] == favorite_ticket_id),
            "favorite_reason": (
                next((r["reason"] for r in plan_5_12.get("top_pick_ranking", [])
                      if r.get("ticket") == t["id"] and r.get("rank") == 1), "")
                if t["id"] == favorite_ticket_id else ""
            ),
            "variant_note": (
                t.get("rationale", "") if t["id"] == "C"
                else t.get("override_rationale", "")
                or t.get("replacement_rationale", "")
                or t.get("source", "")
            ),
            "legs": legs_legacy,
        })

    total_stake = sum(t["stake"] for t in plan_5_12["tickets"])
    total_ev = sum(t.get("ev_estimate", 0.0) for t in plan_5_12["tickets"])
    pf = plan_5_12.get("portfolio", {})

    legacy = {
        "run_date": plan_5_12["run_date"],
        "budget_total": plan_5_12["budget_total"],
        "rule_environment": [
            "Rule A-O",
            "R1-R20 (含 5/12 落库 R17-R20)",
            "R17 override on C ticket (single-day experiment)",
        ],
        "config_variant": plan_5_12.get("verdict_stance", "bold"),
        "config_variant_note": (
            "人工融裁决・大胆版：采纳 Codex C 双 alpha (override R17) + "
            "加 F micro 兑现 001 0:0 alpha；预算 25/25/28/12/8/2"
        ),
        "portfolio_metrics": {
            "total_stake": total_stake,
            "total_expected_value_known": round(total_ev, 2),
            "comparison": {
                "sop_default_variant_ev": pf.get("claude_version_ev", "-5"),
                "experimental_blended_variant_ev": pf.get("final_ruling_ev", round(total_ev, 2)),
                "ev_uplift_vs_sop": (
                    pf.get("final_ruling_ev", 0) - pf.get("claude_version_ev", 0)
                ),
            },
        },
        "tickets": tickets_legacy,
        "excluded_matches": [],
        "concentration_audit": {
            "shared_matches": [
                {
                    "match_no": "周二006",
                    "tickets": ["A", "B", "C"],
                    "stake_at_risk": 78,
                    "narrative_diversification": "三方向独立（A 让负 / B had 平 / C crs 0:0），但 78 元集中较高",
                },
                {
                    "match_no": "周二004",
                    "tickets": ["A", "B", "E"],
                    "stake_at_risk": 58,
                    "narrative_diversification": "三方向独立（A 让负 / B had 平 / E crs 0:0）",
                },
            ],
            "rule_o_violations": "0 (同票同场不同 pool 已检验通过)",
            "rule_b_floor_violations": "0 (had legs 全 > 1.50)",
            "rule_r9_extreme_crs_quality_gate": "N/A (E 单 crs 腿)",
            "rule_r10_hivol_ttg_low_in_main_violations": "0 (B main 内无 hi-vol ttg ≤ 2 球)",
            "rule_r13_poisson_solo_expected_goals_consistency": "C ticket 人工 override R17 (单日实验)",
        },
    }
    return legacy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-12")
    parser.add_argument("--dispatch", action="store_true")
    args = parser.parse_args()

    base = Path(".nutmeg-data/jczq/daily") / args.date
    plan_json = base / "debate" / "final-plan.json"
    pdf_out = base / f"final-value-plan-{args.date.replace('-', '')}.pdf"

    plan_5_12 = json.loads(plan_json.read_text(encoding="utf-8"))
    legacy = adapt_5_12_plan(plan_5_12)
    render_pdf(legacy, pdf_out)
    print(f"Wrote PDF: {pdf_out} ({pdf_out.stat().st_size} bytes)")

    if not args.dispatch:
        print("(--dispatch not set; skip telegram)")
        return

    token = os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
    chat_ids = os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS")
    if not token or not chat_ids:
        raise SystemExit("Missing NUTMEG_TELEGRAM_BOT_TOKEN / NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS")

    client = TelegramBotClient(token=token)
    favorite = next((t for t in legacy["tickets"] if t.get("favorite")), None)
    cap_lines = [
        f"JCZQ Final Plan — {legacy['run_date']} (大胆融裁决)",
        f"6 张票 / 预算 {legacy['budget_total']} 元 / Portfolio EV ≈ {legacy['portfolio_metrics']['total_expected_value_known']:+.2f} 元",
    ]
    if favorite:
        cap_lines.append(
            f"主推：{favorite['id']} {favorite['name']} {favorite['stake']} 元 / {favorite['total_odds']}x"
        )
    cap_lines.append("（C 票 R17 override + 4 条 alpha 全兑现 + F micro）")
    caption = "\n".join(cap_lines)

    for chat_id_str in chat_ids.split(","):
        chat_id_str = chat_id_str.strip()
        if not chat_id_str:
            continue
        chat_id = int(chat_id_str)
        client.send_document(chat_id=chat_id, document_path=pdf_out, caption=caption)
        print(f"Dispatched PDF to chat_id={chat_id}")


if __name__ == "__main__":
    main()
