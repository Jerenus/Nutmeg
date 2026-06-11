"""§E 世界杯节渲染 + 淘汰赛裁量问题 + 决策包接缝。"""
from __future__ import annotations

from nutmeg.services.jczq_bold_combos import BoldMatch
from nutmeg.services.jczq_today import JudgmentQuestion
from nutmeg.services.worldcup.packet_section import (
    render_wc_section,
    wc_judgment_questions,
)
from nutmeg.services.worldcup.sim import SimOutput
from nutmeg.services.worldcup.tournament import Tournament

from tests.test_wc_tournament import _mini_tournament_dict


def _sim(champ_mex: float, run_date: str = "2026-06-12") -> SimOutput:
    probs = {
        t: dict.fromkeys(
            ("qualify", "r32", "r16", "qf", "sf", "final", "champion"), 0.1
        )
        for t in ("Mexico", "Poland", "Senegal", "Jordan")
    }
    probs["Mexico"]["champion"] = champ_mex
    return SimOutput(run_date=run_date, seed=1, n_sims=100, probs=probs)


def test_render_section_contains_top10_and_delta() -> None:
    t = Tournament.from_dict(_mini_tournament_dict())
    md = render_wc_section(
        t, sim_today=_sim(0.4), sim_yesterday=_sim(0.3),
        todays_matches=[], calibration_note=None,
    )
    assert "## E. 世界杯赛事预测" in md
    assert "墨西哥" in md
    assert "+10.0pp" in md  # 0.3→0.4 的变动展示


def test_render_section_shows_calibration_alert() -> None:
    t = Tournament.from_dict(_mini_tournament_dict())
    md = render_wc_section(t, sim_today=_sim(0.4), sim_yesterday=None,
                           todays_matches=[], calibration_note="🟨 校准警示:测试")
    assert "🟨 校准警示" in md


def _bold(match_no: str, home: str, away: str) -> BoldMatch:
    return BoldMatch(match_no=match_no, league="世界杯", home=home, away=away,
                     tc_odds={"home": 2.0, "draw": 3.2, "away": 3.4})


def test_knockout_question_only_for_knockout_sale_matches() -> None:
    raw = _mini_tournament_dict()
    raw["matches"].append({
        "match_id": "M74", "stage": "r16", "date_utc": "2026-07-04",
        "home_slot": "W73", "away_slot": "1A", "venue_country": "USA"})
    t = Tournament.from_dict(raw)
    matches = [_bold("周六001", "墨西哥", "波兰")]
    # 6/12 = 小组赛日期 → 无问题;7/4 = 淘汰赛日 → 出 Q_WC_KNOCKOUT
    assert wc_judgment_questions(matches, t, run_date="2026-06-12") == []
    qs = wc_judgment_questions(matches, t, run_date="2026-07-04")
    assert len(qs) == 1
    assert qs[0].q_id == "Q_WC_KNOCKOUT_周六001"
    assert isinstance(qs[0], JudgmentQuestion)
    assert "90" in qs[0].prompt


def test_render_today_packet_accepts_wc_extension() -> None:
    """决策包接缝:wc_section 追加在末尾,extra_questions 进 §C。"""
    from nutmeg.services.jczq_tiered import TieredPlan
    from nutmeg.services.jczq_today import render_today_packet

    # TieredPlan 以实际签名构造:recommended_single 为必填(无默认),
    # 与 tests/test_jczq_today.py 的 _plan 工厂一致地传 None。
    plan = TieredPlan(run_date="2026-06-12", day_chaos=50, chaos_band="正常",
                      tiers=[None, None, None, None], recommended_single=None)
    extra = [JudgmentQuestion(q_id="Q_WC_KNOCKOUT_X", kind="WC_KNOCKOUT",
                              prompt="90 分钟口径", default="维持")]
    md = render_today_packet(plan, [], {}, wc_section="## E. 世界杯赛事预测\nX",
                             extra_questions=extra)
    assert "## E. 世界杯赛事预测" in md
    assert "Q_WC_KNOCKOUT_X" in md
