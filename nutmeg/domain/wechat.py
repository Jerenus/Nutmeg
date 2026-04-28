from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from nutmeg.domain.content import ComplianceAssessment


@dataclass(slots=True, frozen=True)
class WeChatArticleSelection:
    match_no: str
    match_date: str
    match_time: str
    league: str
    home_team: str
    away_team: str
    score: float
    selection_reason: str
    observed_picks: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)

    @property
    def match_name(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["match_name"] = self.match_name
        return payload


@dataclass(slots=True, frozen=True)
class WeChatDraftPayload:
    title: str
    author: str
    digest: str
    content_html: str
    thumb_media_id: str
    source_url: str | None = None
    need_open_comment: int = 0
    only_fans_can_comment: int = 0

    def to_wechat_dict(self) -> dict[str, Any]:
        article: dict[str, Any] = {
            "title": self.title,
            "author": self.author,
            "digest": self.digest,
            "content": self.content_html,
            "thumb_media_id": self.thumb_media_id,
            "need_open_comment": self.need_open_comment,
            "only_fans_can_comment": self.only_fans_can_comment,
        }
        if self.source_url:
            article["content_source_url"] = self.source_url
        return {"articles": [article]}

    def to_dict(self) -> dict[str, Any]:
        return self.to_wechat_dict()


@dataclass(slots=True, frozen=True)
class WeChatDraftResult:
    status: str
    media_id: str | None = None
    created_at: str | None = None
    error_code: int | None = None
    error_message: str | None = None
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class WeChatArtifacts:
    article_markdown_path: str | None = None
    article_html_path: str | None = None
    draft_payload_path: str | None = None
    compliance_path: str | None = None
    selected_matches_path: str | None = None
    cover_prompt_path: str | None = None
    publish_checklist_path: str | None = None
    draft_result_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class WeChatArticlePack:
    generated_at: str
    source_report_path: str
    title: str
    digest: str
    author: str
    article_markdown: str
    article_html: str
    selections: list[WeChatArticleSelection]
    compliance: ComplianceAssessment
    draft_payload: WeChatDraftPayload
    artifacts: WeChatArtifacts = field(default_factory=WeChatArtifacts)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "source_report_path": self.source_report_path,
            "title": self.title,
            "digest": self.digest,
            "author": self.author,
            "article_markdown": self.article_markdown,
            "article_html": self.article_html,
            "selections": [selection.to_dict() for selection in self.selections],
            "compliance": self.compliance.to_dict(),
            "draft_payload": self.draft_payload.to_dict(),
            "artifacts": self.artifacts.to_dict(),
            "warnings": self.warnings,
        }
