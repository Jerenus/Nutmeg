from __future__ import annotations

from nutmeg.domain.content import ComplianceAssessment, ComplianceChecklistItem
from nutmeg.domain.wechat import (
    WeChatArticlePack,
    WeChatArticleSelection,
    WeChatArtifacts,
    WeChatDraftPayload,
)


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
