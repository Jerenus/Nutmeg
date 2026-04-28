from __future__ import annotations

from pathlib import Path

from nutmeg.services.jczq import JczqMixedReportService


def _match(num, date, time, league, home, away, pools):
    pool_list = []
    for pool in pools:
        pool_list.append(
            {"poolCode": pool.upper(), "poolStatus": "Selling", "single": 1, "allUp": 1}
        )
    return {
        "matchNumStr": num,
        "matchDate": date,
        "matchTime": time,
        "leagueAbbName": league,
        "homeTeamAbbName": home,
        "awayTeamAbbName": away,
        "matchStatus": "Selling",
        "poolList": pool_list,
        **pools,
    }


def _pool(**kwargs):
    return kwargs


def fake_calculator_payload():
    return {
        "lastUpdateTime": "2026-04-26 18:33:24",
        "matchInfoList": [
            {
                "businessDate": "2026-04-26",
                "subMatchList": [
                    _match(
                        "周日020",
                        "2026-04-27",
                        "00:00:00",
                        "意甲",
                        "都灵",
                        "国际米兰",
                        {
                            "hafu": _pool(
                                da="3.70", updateDate="2026-04-26", updateTime="17:51:47"
                            )
                        },
                    ),
                    _match(
                        "周日023",
                        "2026-04-27",
                        "01:00:00",
                        "葡超",
                        "阿马多拉",
                        "波尔图",
                        {
                            "crs": _pool(
                                s00s02="5.00",
                                updateDate="2026-04-24",
                                updateTime="09:58:44",
                            )
                        },
                    ),
                    _match(
                        "周日025",
                        "2026-04-27",
                        "02:45:00",
                        "意甲",
                        "AC米兰",
                        "尤文图斯",
                        {
                            "crs": _pool(
                                s01s01="5.80",
                                updateDate="2026-04-26",
                                updateTime="15:22:44",
                            )
                        },
                    ),
                    _match(
                        "周日028",
                        "2026-04-27",
                        "03:30:00",
                        "葡超",
                        "阿维SAD",
                        "里斯本",
                        {
                            "hhad": _pool(
                                d="4.10",
                                goalLine="+2",
                                updateDate="2026-04-26",
                                updateTime="16:48:06",
                            )
                        },
                    ),
                    _match(
                        "周日012",
                        "2026-04-26",
                        "21:30:00",
                        "德甲",
                        "斯图加特",
                        "不来梅",
                        {
                            "ttg": _pool(
                                s4="4.10", updateDate="2026-04-26", updateTime="15:42:14"
                            )
                        },
                    ),
                    _match(
                        "周日019",
                        "2026-04-26",
                        "23:30:00",
                        "德甲",
                        "多特蒙德",
                        "弗赖堡",
                        {
                            "ttg": _pool(
                                s4="4.25", updateDate="2026-04-26", updateTime="18:33:24"
                            )
                        },
                    ),
                    _match(
                        "周日024",
                        "2026-04-27",
                        "01:15:00",
                        "挪超",
                        "利勒斯特",
                        "博德闪耀",
                        {
                            "ttg": _pool(
                                s5="5.90", updateDate="2026-04-26", updateTime="17:47:58"
                            )
                        },
                    ),
                    _match(
                        "周日029",
                        "2026-04-27",
                        "07:00:00",
                        "美职",
                        "洛城银河",
                        "盐湖城",
                        {
                            "hafu": _pool(
                                dd="6.25", updateDate="2026-04-25", updateTime="09:37:59"
                            )
                        },
                    ),
                ],
            }
        ],
    }


class FakeProvider:
    source_api = "fake://sporttery"
    source_page = "https://www.sporttery.cn/jc/jsq/zqspf/"

    def fetch(self):
        return fake_calculator_payload()


class FakeSender:
    def __init__(self) -> None:
        self.sent = []

    def send_document(self, *, chat_id: int, document_path: Path, caption: str):
        self.sent.append((chat_id, Path(document_path), caption))
        return {"ok": True, "result": {"message_id": 99}}


def test_jczq_service_builds_two_four_leg_high_odds_combinations() -> None:
    report = JczqMixedReportService(provider=FakeProvider()).build_report()

    assert report.official_last_update == "2026-04-26 18:33:24"
    assert len(report.combinations) == 2
    assert all(len(combo.legs) == 4 for combo in report.combinations)
    assert report.combinations[0].total_odds == 439.93
    assert report.combinations[1].total_odds == 642.55
    assert report.combinations[0].legs[0].match_no == "周日020"
    assert report.combinations[0].legs[3].goal_line == "+2"
    assert report.combinations[1].legs[3].pick == "平/平"


def test_jczq_service_writes_markdown_pdf_json_and_dry_run_dispatch(tmp_path) -> None:
    sender = FakeSender()
    report = JczqMixedReportService(
        provider=FakeProvider(), telegram_sender=sender, telegram_chat_ids=[7627818415]
    ).build_report(output_dir=tmp_path, render_pdf=True, dispatch_telegram=True, dry_run=True)

    assert report.artifacts.markdown_path.endswith(".md")
    assert report.artifacts.pdf_path.endswith(".pdf")
    assert report.artifacts.report_json_path.endswith(".json")
    assert Path(report.artifacts.pdf_path).read_bytes().startswith(b"%PDF")
    assert "仅供小注娱乐参考" in Path(report.artifacts.markdown_path).read_text(encoding="utf-8")
    assert report.dispatch.status == "dry_run"
    assert sender.sent == []
