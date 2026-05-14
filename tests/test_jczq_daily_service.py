from __future__ import annotations

import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.services.jczq_daily import JczqDailyAdvisorService
from nutmeg.storage.betting_plan_repository import DuckDbBettingPlanRepository
from nutmeg.storage.bootstrap import create_analytics_schema


def _pool(**kwargs):
    return kwargs


def _match(num, league, home, away, had, hhad, ttg, hafu, crs):
    return {
        "matchNumStr": num,
        "matchDate": "2026-05-02",
        "matchTime": "03:00:00",
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


def fake_daily_payload():
    return {
        "lastUpdateTime": "2026-04-30 18:10:23",
        "matchInfoList": [
            {
                "businessDate": "2026-05-01",
                "subMatchList": [
                    _match(
                        "周五001",
                        "挪超",
                        "维京",
                        "罗森博格",
                        _pool(
                            h="1.28",
                            d="4.90",
                            a="7.00",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            h="1.95",
                            d="3.60",
                            a="2.95",
                            goalLine="-1",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            s3="3.45",
                            s4="4.40",
                            s5="6.50",
                            updateDate="2026-04-30",
                            updateTime="13:25:14",
                        ),
                        _pool(
                            hh="1.76",
                            dh="3.95",
                            dd="8.25",
                            da="16.50",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            s02s00="7.25",
                            s02s01="6.75",
                            s01s01="9.00",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                    ),
                    _match(
                        "周五003",
                        "意甲",
                        "比萨",
                        "莱切",
                        _pool(
                            h="2.76",
                            d="2.77",
                            a="2.46",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            h="1.41",
                            d="3.80",
                            a="6.35",
                            goalLine="+1",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            s2="3.00",
                            s3="4.05",
                            s4="7.35",
                            updateDate="2026-04-30",
                            updateTime="13:25:14",
                        ),
                        _pool(
                            aa="4.30",
                            dd="3.95",
                            da="5.35",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            s00s01="6.25",
                            s01s01="5.35",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                    ),
                    _match(
                        "周五004",
                        "英超",
                        "利兹联",
                        "伯恩利",
                        _pool(
                            h="1.27",
                            d="4.70",
                            a="7.75",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            h="1.93",
                            d="3.60",
                            a="3.00",
                            goalLine="-1",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            s3="3.40",
                            s4="4.80",
                            s5="7.65",
                            updateDate="2026-04-30",
                            updateTime="13:25:14",
                        ),
                        _pool(
                            hh="1.85",
                            dh="3.75",
                            dd="7.00",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                        _pool(
                            s02s00="6.50",
                            s02s01="7.00",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                    ),
                    _match(
                        "周五005",
                        "西甲",
                        "赫罗纳",
                        "马洛卡",
                        _pool(
                            h="1.85",
                            d="3.35",
                            a="3.45",
                            updateDate="2026-04-30",
                            updateTime="18:09:29",
                        ),
                        _pool(
                            h="3.57",
                            d="3.60",
                            a="1.75",
                            goalLine="-1",
                            updateDate="2026-04-30",
                            updateTime="18:09:34",
                        ),
                        _pool(
                            s2="3.55",
                            s3="3.45",
                            s4="5.10",
                            updateDate="2026-04-30",
                            updateTime="13:25:14",
                        ),
                        _pool(
                            hh="2.95",
                            dh="4.60",
                            dd="5.25",
                            updateDate="2026-04-30",
                            updateTime="18:10:23",
                        ),
                        _pool(
                            s01s00="7.50",
                            s01s01="6.75",
                            updateDate="2026-04-30",
                            updateTime="13:25:09",
                        ),
                    ),
                ],
            }
        ],
    }


class FakeProvider:
    source_api = "fake://jczq-daily"
    source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

    def fetch(self):
        return fake_daily_payload()


class FakeSender:
    def __init__(self) -> None:
        self.messages = []

    def send_message(self, *, chat_id: int, text: str):
        self.messages.append((chat_id, text))
        return {"ok": True, "result": {"message_id": 77}}


def test_daily_advisor_generates_dynamic_multi_pool_plans_and_artifacts(tmp_path: Path) -> None:
    report = JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    assert report.official_last_update == "2026-04-30 18:10:23"
    assert [match.match_no for match in report.matches] == [
        "周五001",
        "周五003",
        "周五004",
        "周五005",
    ]
    assert {plan.kind for plan in report.plans} >= {"main", "inspiration", "contrarian", "extreme"}
    assert all(len({leg.match_no for leg in plan.legs}) == len(plan.legs) for plan in report.plans)
    inspiration = next(plan for plan in report.plans if plan.kind == "inspiration")
    assert len(inspiration.legs) == 4
    # Rule H: hafu is locked to the extreme ticket (4-day backtest 0/9 hit-rate).
    # Rule I scrub may swap some ttg/crs picks out when Poisson strongly
    # opposes them — so we just require ≥ 2 distinct pools and no hafu. The
    # exact pool spread depends on Poisson coverage of the fixture.
    assert len({leg.pool for leg in inspiration.legs}) >= 2
    assert all(leg.pool != "hafu" for leg in inspiration.legs)
    multiplied = 1.0
    for leg in inspiration.legs:
        multiplied *= leg.odds
    assert inspiration.total_odds == round(multiplied, 2)
    assert inspiration.two_yuan_return == round(inspiration.total_odds * 2, 2)
    assert "周日020" not in json.dumps(report.to_dict(), ensure_ascii=False)
    assert Path(report.artifacts["context_path"]).exists()
    assert Path(report.artifacts["markdown_path"]).exists()
    assert "高赔率灵感票" in Path(report.artifacts["markdown_path"]).read_text(encoding="utf-8")


def test_daily_advisor_flags_comfortable_favorite_and_adds_protection(tmp_path: Path) -> None:
    report = JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    girona = next(match for match in report.matches if match.match_no == "周五005")
    assert "舒服盘需防平防冷" in girona.confidence_note

    protected_legs = [
        leg
        for plan in report.plans
        for leg in plan.legs
        if leg.match_no == "周五005" and (leg.pick in {"平", "负"} or leg.pool in {"hafu", "crs"})
    ]
    assert protected_legs

    girona_had_picks = [
        leg.pick
        for plan in report.plans
        for leg in plan.legs
        if leg.match_no == "周五005" and leg.pool == "had"
    ]
    assert "胜" not in girona_had_picks
    assert {"平", "负"}.issubset(set(girona_had_picks))
    assert "舒服盘审问" in report.summary


def test_daily_advisor_includes_stable_base_before_bold_opportunity(tmp_path: Path) -> None:
    report = JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    stable = report.plans[0]

    assert stable.kind == "stable_base"
    assert "稳健底仓" in stable.name
    assert 0 < stable.total_odds <= 35
    assert all(leg.odds <= 2.05 for leg in stable.legs)
    assert "稳健底仓" in report.summary
    assert any(plan.kind in {"inspiration", "contrarian", "false_signal"} for plan in report.plans)


def test_daily_advisor_adds_false_signal_scoring_layer(tmp_path: Path) -> None:
    report = JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    false_signal = next(plan for plan in report.plans if plan.kind == "false_signal")

    assert "假信号" in false_signal.name
    assert "不机械反热门" in false_signal.risk_note
    assert any(
        leg.match_no == "周五001" and leg.pool == "hhad" and leg.pick == "让胜"
        for leg in false_signal.legs
    )
    assert any(
        leg.match_no == "周五005" and leg.pool == "hhad" and leg.pick == "让负"
        for leg in false_signal.legs
    )
    # R12 (5/10) may filter all ttg/hafu legs in this synthetic fixture (their
    # edges are all worse than -10%). The "scoring layer" guarantee is that
    # false_signal is not a single-pool plan when it has ≥ 2 legs; relax to
    # allow hhad-only sources when R12 trims the model-opposed alternatives.
    if len(false_signal.legs) >= 2:
        assert {leg.pool for leg in false_signal.legs} - {"had"}, (
            "false_signal must surface non-had layers (hhad / ttg / hafu)"
        )
    assert all(
        not (leg.match_no == "周五005" and leg.pool == "had" and leg.pick == "胜")
        for leg in false_signal.legs
    )
    assert "假信号审问" in report.summary


def test_daily_advisor_reads_strategy_memory_and_promotes_learned_inspiration(
    tmp_path: Path,
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "strategy-memory.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sample_count": 3,
                "last_review_date": "2026-05-01",
                "patterns": {
                    "user_revision_hafu_draw_away": {
                        "label": "用户修正-半全场平/负",
                        "hits": 2,
                        "misses": 0,
                    },
                    "comfort_risk_draw_or_cold": {
                        "label": "舒服盘防平防冷",
                        "hits": 2,
                        "misses": 1,
                    },
                },
                "insights": [
                    "003类客胜低赔的谨慎盘，半全场平/负需要升权。",
                    "1.75-2.05舒服盘延续防平防冷。",
                ],
                "recent_inspirations": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    main = next(plan for plan in report.plans if plan.kind == "main")
    # Rule H rewrites the memory-promoted hafu pick into a non-hafu equivalent
    # (ttg or hhad cover) — the leg from 周五003 still appears in main, just
    # not as hafu 平/负.
    promoted = [leg for leg in main.legs if leg.match_no == "周五003"]
    assert promoted, "memory promotion should still inject a 周五003 leg into main"
    assert all(leg.pool != "hafu" for leg in promoted)
    assert "历史记忆提示" in report.summary
    assert "半全场平/负" in report.summary


def test_daily_advisor_applies_executable_decision_policy(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "strategy-memory.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sample_count": 4,
                "patterns": {},
                "insights": [],
                "recent_inspirations": [],
                "decision_policy": {
                    "version": 1,
                    "last_review_date": "2026-05-03",
                    "rules": {
                        "stable_base": {
                            "active": True,
                            "action": "downgrade_low_price_bankers",
                        },
                        "total_goals": {
                            "active": True,
                            "action": "promote_total_goals_two_ball",
                            "preferred_picks": ["2球", "1球", "0球"],
                        },
                        "hafu": {
                            "active": True,
                            "action": "downgrade_half_full_non_extreme",
                        },
                        "reuse_guard": {
                            "active": True,
                            "action": "avoid_reusing_missed_match_story",
                        },
                    },
                    "notes": [
                        "强胆低赔近期失真，底仓必须降权并寻找让球/总进球支撑。",
                        "2球结果近期集中，分歧盘优先检查总进球2球和小比分路径。",
                        "半全场近期命中差，非极限票降权，优先改用总进球/让球。",
                        "同场错误剧本复用风险升高，单场不要拖累多张串。",
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = JczqDailyAdvisorService(provider=FakeProvider()).build_report(
        run_date="2026-05-01", output_dir=tmp_path
    )

    stable = next(plan for plan in report.plans if plan.kind == "stable_base")
    assert all(
        not (leg.match_no in {"周五001", "周五004"} and leg.pool == "had" and leg.pick == "胜")
        for leg in stable.legs
    )
    non_extreme_legs = [
        leg for plan in report.plans if plan.kind != "extreme" for leg in plan.legs
    ]
    assert any(leg.pool == "ttg" and leg.pick == "2球" for leg in non_extreme_legs)
    assert all(leg.pool != "hafu" for leg in non_extreme_legs)
    exact_stories = [(leg.match_no, leg.pool, leg.pick) for leg in non_extreme_legs]
    assert len(exact_stories) == len(set(exact_stories))
    assert "策略迭代执行" in report.summary
    assert "2球" in report.summary
    assert "半全场" in report.summary


def test_daily_advisor_dispatches_text_to_telegram_and_records_status(tmp_path: Path) -> None:
    sender = FakeSender()
    report = JczqDailyAdvisorService(
        provider=FakeProvider(), telegram_sender=sender, telegram_chat_ids=[7627818415]
    ).build_report(
        run_date="2026-05-01",
        output_dir=tmp_path,
        dispatch_telegram=True,
        dry_run=False,
    )

    assert report.dispatch["status"] == "sent"
    assert sender.messages and sender.messages[0][0] == 7627818415
    assert "最终主方案" in sender.messages[0][1]


def test_daily_advisor_records_final_plans_to_betting_db(tmp_path: Path) -> None:
    settings = AppSettings(data_dir=tmp_path / "data")
    create_analytics_schema(settings)
    repository = DuckDbBettingPlanRepository(settings)

    JczqDailyAdvisorService(provider=FakeProvider(), betting_repository=repository).build_report(
        run_date="2026-05-01",
        output_dir=tmp_path / "jczq",
        record_final=True,
    )

    stored = repository.get_run("jczq:2026-05-01:final")

    assert stored is not None
    assert stored["game_type"] == "jczq"
    assert len(stored["plans"]) >= 4
    assert stored["plans"][0]["role"] == "stable_base"
    assert stored["plans"][0]["legs"]


def test_daily_advisor_revises_saved_context_with_instruction(tmp_path: Path) -> None:
    service = JczqDailyAdvisorService(provider=FakeProvider())
    original = service.build_report(run_date="2026-05-01", output_dir=tmp_path)

    revised = service.revise(
        run_date="2026-05-01",
        output_dir=tmp_path,
        instruction="不要比分，提高到100倍，规避大众盘口",
    )

    assert revised.revision["instruction"] == "不要比分，提高到100倍，规避大众盘口"
    assert revised.revision["version"] == original.revision["version"] + 1
    inspiration = next(plan for plan in revised.plans if plan.kind == "inspiration")
    assert inspiration.total_odds >= 100
    assert all(leg.pool != "crs" for leg in inspiration.legs)
    assert "不要比分" in revised.summary


def test_daily_advisor_promotes_user_half_full_revision(tmp_path: Path) -> None:
    service = JczqDailyAdvisorService(provider=FakeProvider())
    service.build_report(run_date="2026-05-01", output_dir=tmp_path)

    revised = service.revise(
        run_date="2026-05-01",
        output_dir=tmp_path,
        instruction="003最后修正为平负，005要防平防冷",
    )

    main = next(plan for plan in revised.plans if plan.kind == "main")
    # Rule H: user's "半全场平/负" revision is rewritten as a non-hafu leg in
    # main (extreme keeps the original hafu pick). Verify 周五003 still owns
    # a slot in main and that no hafu sneaks past Rule H.
    promoted = [leg for leg in main.legs if leg.match_no == "周五003"]
    assert promoted, "user revision should still surface 周五003 in main"
    assert all(leg.pool != "hafu" for leg in promoted)
    assert "003最后修正为平负" in revised.summary


def test_daily_advisor_revises_from_saved_context_without_refetch(tmp_path: Path) -> None:
    class OneShotProvider:
        source_api = "fake://one-shot"
        source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("revision should use saved context")
            return fake_daily_payload()

    provider = OneShotProvider()
    service = JczqDailyAdvisorService(provider=provider)
    service.build_report(run_date="2026-05-01", output_dir=tmp_path)
    revised = service.revise(
        run_date="2026-05-01",
        output_dir=tmp_path,
        instruction="规避大众盘口",
    )

    assert provider.calls == 1
    assert revised.revision["version"] == 2
    assert "规避大众盘口" in revised.summary


def test_jczq_daily_review_8am_launchd_template_runs_real_dispatch() -> None:
    template = Path("scripts/launchd/com.nutmeg.jczq.daily-review-8am.plist").read_text(
        encoding="utf-8"
    )

    assert "<integer>8</integer>" in template
    assert "<integer>0</integer>" in template
    assert "jczq-daily-review" in template
    assert "--date yesterday" in template
    assert "--dispatch-telegram" in template
    assert "--no-dry-run" in template
