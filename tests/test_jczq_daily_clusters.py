"""Cluster-plan + portfolio-decorrelation regression for JCZQ daily generator.

Uses a synthetic many-match payload that covers the conditions absent from the
existing 4-match fixture: enough comfort-risk matches to fire `draw_cluster`
and enough strong bankers to fire `upset_cluster`.
"""

from __future__ import annotations

from pathlib import Path

from nutmeg.services.jczq_daily import JczqDailyAdvisorService


def _pool(**kwargs):
    return kwargs


def _match(num, league, home, away, had, hhad, ttg, hafu, crs):
    return {
        "matchNumStr": num,
        "matchDate": "2026-05-04",
        "matchTime": "21:00:00",
        "leagueAbbName": league,
        "homeTeamAbbName": home,
        "awayTeamAbbName": away,
        "matchStatus": "Selling",
        "poolList": [
            {"poolCode": code, "poolStatus": "Selling", "single": 1, "allUp": 1}
            for code in ["HAD", "HHAD", "TTG", "HAFU", "CRS"]
        ],
        "had": had,
        "hhad": hhad,
        "ttg": ttg,
        "hafu": hafu,
        "crs": crs,
    }


def _comfort(num: str, league: str = "德乙") -> dict:
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="1.92", d="3.65", a="3.95"),
        _pool(h="2.50", d="3.20", a="2.40", goalLine="-1"),
        _pool(s2="3.40"),
        _pool(hh="3.20", dh="4.20", dd="5.30"),
        _pool(s01s00="7.50", s01s01="6.40"),
    )


def _strong(num: str, league: str = "西甲") -> dict:
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="1.18", d="6.50", a="14.00"),
        _pool(h="2.05", d="3.45", a="2.95", goalLine="-2"),
        _pool(s3="3.60"),
        _pool(hh="2.20", dh="6.20", dd="9.40"),
        _pool(s02s00="6.80", s03s01="9.50"),
    )


def _open(num: str, league: str = "英超") -> dict:
    return _match(
        num,
        league,
        f"H-{num}",
        f"A-{num}",
        _pool(h="2.80", d="3.30", a="2.50"),
        _pool(h="2.10", d="3.30", a="2.80", goalLine="0"),
        _pool(s3="3.20"),
        _pool(hh="3.30", dh="6.00", dd="6.20"),
        _pool(s02s01="8.50", s01s01="5.90"),
    )


def _payload(matches: list[dict]) -> dict:
    return {
        "lastUpdateTime": "2026-05-04 12:00:00",
        "matchInfoList": [
            {
                "businessDate": "2026-05-04",
                "subMatchList": matches,
            }
        ],
    }


class FakeProvider:
    source_api = "fake://jczq-daily-clusters"
    source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

    def __init__(self, matches: list[dict]) -> None:
        self._matches = matches

    def fetch(self) -> dict:
        return _payload(self._matches)


def test_draw_cluster_fires_when_comfort_risk_count_meets_threshold(tmp_path: Path) -> None:
    matches = [
        _comfort("周一001"),
        _comfort("周一002", league="法乙"),
        _comfort("周一003", league="比甲"),
        _open("周一010"),
    ]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-04", output_dir=tmp_path
    )

    draw = next((plan for plan in report.plans if plan.kind == "draw_cluster"), None)
    assert draw is not None and len(draw.legs) >= 3
    # Rule H: draw_cluster is non-extreme so hafu 平/平 is no longer eligible —
    # only had 平 picks remain.
    assert all(leg.pool == "had" and leg.pick == "平" for leg in draw.legs)
    main = next(plan for plan in report.plans if plan.kind == "main")
    main_match_nos = {leg.match_no for leg in main.legs}
    cluster_match_nos = {leg.match_no for leg in draw.legs}
    assert len(main_match_nos & cluster_match_nos) <= 2


def test_upset_cluster_fires_when_strong_count_meets_threshold(tmp_path: Path) -> None:
    matches = [
        _strong("周一004"),
        _strong("周一005", league="意甲"),
        _strong("周一006", league="德甲"),
        _open("周一020"),
    ]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-04", output_dir=tmp_path
    )

    upset = next((plan for plan in report.plans if plan.kind == "upset_cluster"), None)
    assert upset is not None and upset.legs
    favorite_pool_picks = [(leg.pool, leg.pick) for leg in upset.legs]
    # No leg should be the strong favorite (had 胜 with 1.18)
    assert all(not (pool == "had" and pick == "胜") for pool, pick in favorite_pool_picks)


def test_clusters_skipped_when_threshold_not_met(tmp_path: Path) -> None:
    matches = [_open("周一100"), _open("周一101"), _open("周一102")]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-04", output_dir=tmp_path
    )

    kinds = {plan.kind for plan in report.plans}
    assert "draw_cluster" not in kinds
    assert "upset_cluster" not in kinds


def test_portfolio_decorrelation_dedupes_across_opportunity_tickets(tmp_path: Path) -> None:
    # Decorrelation across 3 opportunity tickets × 4 legs needs ≥ 12 unique
    # matches; production days carry 20-30 so we use a realistic ~15 here.
    matches = [
        _comfort("周一200"),
        _comfort("周一201"),
        _comfort("周一202"),
        _strong("周一203"),
        _strong("周一204"),
        _open("周一205"),
        _open("周一206"),
        _open("周一207"),
        _open("周一208"),
        _open("周一209"),
        _open("周一210"),
        _open("周一211"),
        _open("周一212"),
        _open("周一213"),
        _open("周一214"),
    ]
    report = JczqDailyAdvisorService(provider=FakeProvider(matches)).build_report(
        run_date="2026-05-04", output_dir=tmp_path
    )

    opportunity_kinds = {"inspiration", "contrarian", "extreme"}
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str, str]] = []
    for plan in report.plans:
        if plan.kind not in opportunity_kinds:
            continue
        for leg in plan.legs:
            other = seen.get(leg.match_no)
            if other and other != plan.kind:
                duplicates.append((leg.match_no, other, plan.kind))
            else:
                seen[leg.match_no] = plan.kind
    assert duplicates == []
