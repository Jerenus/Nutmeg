from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutmeg.domain.content import ComplianceAssessment, ComplianceChecklistItem
from nutmeg.domain.wechat import (
    WeChatArticlePack,
    WeChatArticleSelection,
    WeChatArtifacts,
    WeChatDraftPayload,
)
from nutmeg.services.wechat_publisher import WeChatPublisherService, WeChatPublisherValidationError


def test_wechat_domain_models_serialize_nested_payloads() -> None:
    selection = WeChatArticleSelection(
        match_no="周日025",
        match_date="2026-04-27",
        match_time="02:45:00",
        league="意甲",
        home_team="AC米兰",
        away_team="尤文图斯",
        score=96.0,
        selection_reason="传统强强对话，赔率与基本面都有解释空间",
        observed_picks=["比分 1:1 @ 5.80"],
        risk_notes=["热门热度", "临场阵容"],
    )
    compliance = ComplianceAssessment(
        risk_level="MEDIUM",
        risk_reasons=["包含赔率和市场预期，需要人工审核"],
        checklist=[ComplianceChecklistItem("是否给出了明确投注动作？", "passed", "")],
        publish_recommendation="review",
    )
    payload = WeChatDraftPayload(
        title="今晚两场焦点战：公开赔率背后的五个变量",
        author="Nutmeg",
        digest="两场比赛的数据分析与风险观察。",
        content_html="<h1>今晚两场焦点战</h1>",
        thumb_media_id="media123",
        source_url="https://example.test/article",
    )
    pack = WeChatArticlePack(
        generated_at="2026-04-28T10:00:00+00:00",
        source_report_path=".nutmeg-data/jczq/report.json",
        title=payload.title,
        digest=payload.digest,
        author=payload.author,
        article_markdown="# 今晚两场焦点战",
        article_html=payload.content_html,
        selections=[selection],
        compliance=compliance,
        draft_payload=payload,
        artifacts=WeChatArtifacts(article_markdown_path="article.md"),
        warnings=["sample warning"],
    )

    data = pack.to_dict()

    assert data["title"] == "今晚两场焦点战：公开赔率背后的五个变量"
    assert data["selections"][0]["match_no"] == "周日025"
    assert data["compliance"]["risk_level"] == "MEDIUM"
    assert data["draft_payload"]["articles"][0]["thumb_media_id"] == "media123"
    assert data["artifacts"]["article_markdown_path"] == "article.md"



def _jczq_report_payload() -> dict:
    return {
        "generated_at": "2026-04-26T10:00:00+00:00",
        "official_last_update": "2026-04-26 18:33:24",
        "source_page": "https://www.sporttery.cn/jc/jsq/zqspf/",
        "source_api": "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry",
        "combinations": [
            {
                "name": "组合A",
                "risk": "高赔进取型",
                "total_odds": 439.93,
                "two_yuan_return": 879.86,
                "legs": [
                    {
                        "match_no": "周日020",
                        "match_date": "2026-04-27",
                        "match_time": "00:00:00",
                        "league": "意甲",
                        "home_team": "都灵",
                        "away_team": "国际米兰",
                        "play": "半全场",
                        "pick": "平/负",
                        "odds": 3.70,
                        "logic": "国米客胜热，但都灵主场抗压。",
                        "goal_line": "",
                        "odds_update": "2026-04-26 17:51:47",
                    },
                    {
                        "match_no": "周日025",
                        "match_date": "2026-04-27",
                        "match_time": "02:45:00",
                        "league": "意甲",
                        "home_team": "AC米兰",
                        "away_team": "尤文图斯",
                        "play": "比分",
                        "pick": "1:1",
                        "odds": 5.80,
                        "logic": "AC米兰 vs 尤文三项赔率接近，低比分平局是高关注样本。",
                        "goal_line": "",
                        "odds_update": "2026-04-26 15:22:44",
                    },
                ],
            },
            {
                "name": "组合B",
                "risk": "更激进",
                "total_odds": 642.55,
                "two_yuan_return": 1285.10,
                "legs": [
                    {
                        "match_no": "周日019",
                        "match_date": "2026-04-26",
                        "match_time": "23:30:00",
                        "league": "德甲",
                        "home_team": "多特蒙德",
                        "away_team": "弗赖堡",
                        "play": "总进球数",
                        "pick": "4球",
                        "odds": 4.25,
                        "logic": "多特主场进攻强，弗赖堡也有进球能力。",
                        "goal_line": "",
                        "odds_update": "2026-04-26 18:33:24",
                    }
                ],
            },
        ],
        "warnings": [],
    }


def _write_report(tmp_path: Path, payload: dict | None = None) -> Path:
    report_file = tmp_path / "jczq-report.json"
    report_file.write_text(
        json.dumps(payload or _jczq_report_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_file


def test_wechat_article_pack_selects_two_focus_matches_and_writes_artifacts(tmp_path: Path) -> None:
    report_file = _write_report(tmp_path)
    service = WeChatPublisherService()

    pack = service.generate_article_pack(
        report_file=report_file,
        output_dir=tmp_path / "wechat",
        thumb_media_id="cover-media",
        author="Nutmeg",
    )

    assert len(pack.selections) == 2
    assert pack.selections[0].match_no == "周日025"
    assert pack.selections[1].match_no == "周日019"
    assert "今晚两场焦点战" in pack.title
    assert "焦点战 1" in pack.article_markdown
    assert "焦点战 2" in pack.article_markdown
    assert "组合观察" in pack.article_markdown
    assert "不构成任何投注建议" in pack.article_markdown
    assert pack.compliance.risk_level == "MEDIUM"
    assert pack.compliance.publish_recommendation == "review"
    assert pack.draft_payload.to_dict()["articles"][0]["thumb_media_id"] == "cover-media"
    assert Path(pack.artifacts.article_markdown_path or "").exists()
    assert Path(pack.artifacts.article_html_path or "").exists()
    assert Path(pack.artifacts.draft_payload_path or "").exists()
    assert Path(pack.artifacts.compliance_path or "").exists()
    assert Path(pack.artifacts.selected_matches_path or "").exists()
    assert Path(pack.artifacts.cover_prompt_path or "").exists()
    assert Path(pack.artifacts.publish_checklist_path or "").exists()


def test_wechat_article_pack_rejects_report_without_two_matches(tmp_path: Path) -> None:
    payload = _jczq_report_payload()
    payload["combinations"] = [
        {**payload["combinations"][0], "legs": [payload["combinations"][0]["legs"][0]]}
    ]
    report_file = _write_report(tmp_path, payload)

    with pytest.raises(WeChatPublisherValidationError, match="at least two distinct matches"):
        WeChatPublisherService().generate_article_pack(
            report_file=report_file,
            output_dir=tmp_path / "wechat",
            thumb_media_id="cover-media",
        )
