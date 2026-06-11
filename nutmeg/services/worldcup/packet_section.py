"""§E 世界杯赛事预测渲染 + 淘汰赛裁量问题(spec §4)。

数字全部来自 sim 落盘对象 — 禁嘴算红线在渲染层延续。
"""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import BoldMatch
from nutmeg.services.jczq_today import JudgmentQuestion

from .sim import SimOutput
from .tournament import Tournament

TOP_N = 10


def _zh(t: Tournament, team: str) -> str:
    rec = t.teams.get(team)
    return rec.zh if rec else team


def render_wc_section(
    tournament: Tournament,
    *,
    sim_today: SimOutput,
    sim_yesterday: SimOutput | None,
    todays_matches: list[dict],
    calibration_note: str | None,
) -> str:
    lines = ["## E. 世界杯赛事预测(蒙特卡洛,seed 可复现)", ""]
    if calibration_note:
        lines += [f"> {calibration_note}", ""]
    lines += [
        f"- 模拟:N={sim_today.n_sims:,} · seed={sim_today.seed} · "
        f"市场锚定 {len(sim_today.anchored)} 场",
        "",
        "### E1 夺冠概率 Top 10",
        "",
        "| 队伍 | 夺冠 | 对昨日 |",
        "|---|---|---|",
    ]
    ranked = sorted(
        sim_today.probs.items(), key=lambda kv: kv[1]["champion"], reverse=True
    )[:TOP_N]
    for team, p in ranked:
        if sim_yesterday and team in sim_yesterday.probs:
            delta = p["champion"] - sim_yesterday.probs[team]["champion"]
            delta_str = f"{delta * 100:+.1f}pp"
        else:
            delta_str = "—"
        lines.append(f"| {_zh(tournament, team)} | {p['champion']:.1%} | {delta_str} |")
    if todays_matches:
        lines += ["", "### E2 今日参赛队出线/晋级形势", "",
                  "| 对阵 | 出线 | 16强 | 夺冠 |", "|---|---|---|---|"]
        for row in todays_matches:
            lines.append(
                f"| {row['label']} | {row['qualify']} | {row['r16']} | {row['champion']} |"
            )
    lines.append("")
    return "\n".join(lines)


def wc_judgment_questions(
    matches: list[BoldMatch], tournament: Tournament, *, run_date: str
) -> list[JudgmentQuestion]:
    """淘汰赛在售场次 → Q_WC_KNOCKOUT(spec §4.1)。

    用日期判档:run_date 落在任何淘汰赛 date_utc(±1 天,跨时区)即视为淘汰赛日。
    """
    from datetime import date, timedelta

    try:
        d = date.fromisoformat(run_date)
    except ValueError:
        return []
    ko_dates: set[date] = set()
    for m in tournament.matches:
        if m.stage == "group":
            continue
        md = date.fromisoformat(m.date_utc)
        ko_dates |= {md, md + timedelta(days=1)}
    if d not in ko_dates:
        return []
    zh_to_team = {t.zh: t.id for t in tournament.teams.values()}
    qs: list[JudgmentQuestion] = []
    for bm in matches:
        if bm.home not in zh_to_team or bm.away not in zh_to_team:
            continue
        qs.append(JudgmentQuestion(
            q_id=f"Q_WC_KNOCKOUT_{bm.match_no}",
            kind="WC_KNOCKOUT",
            match_no=bm.match_no,
            prompt=(
                f"{bm.home} vs {bm.away} 是淘汰赛:竞彩盘口=90 分钟,平局是有效"
                "结果。引擎票面对这场的腿是否需要平局保护(改双选/剔除)?"
            ),
            default="维持引擎票面",
        ))
    return qs
