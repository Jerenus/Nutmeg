"""Tests for the JCZQ final-plan PDF renderer.

Guards the fix for the hardcoded "5 张票" string — the renderer must reflect
the actual number of tickets in the plan (the daily plan is now 4-5 tickets).
"""

from nutmeg.services.jczq_final_plan_pdf import (
    _build_caption,
    _build_story,
    render_pdf,
)


def _story_text(story: list) -> str:
    """Concatenate the text of every Paragraph flowable in a story."""
    return "\n".join(
        text for f in story if (text := getattr(f, "text", None))
    )


def _ticket(idx: int, *, favorite: bool = False) -> dict:
    return {
        "id": f"T{idx}",
        "name": f"票{idx}",
        "stake": 100,
        "total_odds": 5.5,
        "theoretical_payout": 550.0,
        "hit_probability": 0.18,
        "expected_value": -3.5,
        "favorite": favorite,
        "legs": [
            {
                "match_no": f"周六00{idx}",
                "league": "英超",
                "home": "主队",
                "away": "客队",
                "pool": "had",
                "pick": "3",
                "odds": 2.1,
            }
        ],
    }


def _plan(n_tickets: int) -> dict:
    return {
        "run_date": "2026-05-17",
        "budget_total": 400,
        "rule_environment": ["R28"],
        "config_variant": "sop_default",
        "config_variant_note": "测试变体",
        "portfolio_metrics": {
            "total_stake": 100 * n_tickets,
            "total_expected_value_known": -10.5,
            "comparison": {
                "sop_default_variant_ev": -10.5,
                "experimental_blended_variant_ev": -8.0,
                "ev_uplift_vs_sop": 2.5,
            },
        },
        "tickets": [
            _ticket(i, favorite=(i == 1)) for i in range(1, n_tickets + 1)
        ],
        "concentration_audit": {},
    }


def test_build_caption_reflects_actual_ticket_count() -> None:
    caption = _build_caption(_plan(3))
    assert "3 张票" in caption
    assert "5 张票" not in caption


def test_build_story_header_reflects_actual_ticket_count() -> None:
    text = _story_text(_build_story(_plan(4)))
    assert "4 张票" in text
    assert "4 张票腿位明细" in text
    assert "5 张票" not in text


def test_render_pdf_with_non_five_tickets_succeeds(tmp_path) -> None:
    pdf_path = tmp_path / "plan.pdf"
    render_pdf(_plan(3), pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_build_story_omits_inapplicable_legacy_fields() -> None:
    # A conflict-engine plan has no SOP/experimental comparison and none of the
    # legacy Poisson rules — those must be omitted, not rendered as '?'.
    plan = _plan(3)
    plan["portfolio_metrics"]["comparison"] = {}
    plan["concentration_audit"] = {"shared_matches": [], "rule_o_violations": 0}

    text = _story_text(_build_story(plan))

    assert "Rule O" in text  # the one applicable rule still shows
    assert "SOP 默认版" not in text
    assert "Rule R13" not in text
    assert "Rule B had" not in text


def test_build_story_keeps_legacy_fields_when_present() -> None:
    # The legacy generator's plans still render their comparison + rule lines.
    text = _story_text(_build_story(_plan(3)))
    assert "SOP 默认版" in text
