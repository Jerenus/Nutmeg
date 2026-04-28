# WeChat Draft Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Nutmeg workflow that converts a JCZQ mixed report into a compliant two-match WeChat official-account article pack and optionally pushes it to the WeChat draft box.

**Architecture:** Add a dedicated WeChat content layer beside the existing content publisher. Domain dataclasses describe selected matches, article packs, draft payloads, and draft results; a service loads JCZQ report JSON, selects two focus matches, renders Markdown/HTML/draft JSON/checklists, enforces compliance, and calls a small WeChat HTTP client only after explicit confirmation.

**Tech Stack:** Python 3.12, dataclasses, Typer CLI, httpx, pytest, existing `ContentComplianceChecker`, existing JCZQ report JSON shape, OpenClaw safe router.

---

## File Structure

- Create `nutmeg/domain/wechat.py`: WeChat article/draft dataclasses with `to_dict()` helpers.
- Create `nutmeg/services/wechat_publisher.py`: report loading, match selection, article rendering, compliance, artifact writing, access token retrieval, and draft creation.
- Modify `nutmeg/interfaces/cli.py`: add `wechat-article-pack` and `wechat-draft-push` commands plus service builder.
- Modify `scripts/openclaw/nutmeg_command_router.py`: add safe router actions for local pack creation and confirmed draft push.
- Create `tests/test_wechat_publisher_service.py`: unit tests for selection, rendering, compliance blocking, artifacts, and mocked WeChat client behavior.
- Modify `tests/test_cli.py`: CLI coverage for article pack, dry-run draft push, and blocked missing pack behavior.
- Modify `tests/test_openclaw_router.py`: router coverage for new actions and confirmation requirements.
- Optional docs touch after implementation: update `docs/architecture/content-publisher.md` with the WeChat draft extension summary.

## Implementation Notes

The JCZQ report JSON contains combinations and legs, not full fixture intelligence. v1 should use legs as the input source and select two distinct matches from all combination legs. Selection should favor popular leagues/teams and high explanatory value, but remain deterministic and explainable.

The public article may contain `赔率`, `市场预期`, and `方向` language, so `MEDIUM` risk is acceptable for draft creation. `HIGH` and `BLOCKED` must be blocked from draft push.

Use the official WeChat draft API shape:

```json
{
  "articles": [
    {
      "title": "...",
      "author": "Nutmeg",
      "digest": "...",
      "content": "<p>...</p>",
      "thumb_media_id": "MEDIA_ID",
      "need_open_comment": 0,
      "only_fans_can_comment": 0
    }
  ]
}
```

The draft client should call:

- `GET https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=...&secret=...`
- `POST https://api.weixin.qq.com/cgi-bin/draft/add?access_token=...`

Do not implement or call the publish endpoint.

### Task 1: Domain Models

**Files:**
- Create: `nutmeg/domain/wechat.py`
- Test: `tests/test_wechat_publisher_service.py`

- [ ] **Step 1: Write failing domain serialization tests**

Add this new test file with imports and the first test:

```python
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
    WeChatDraftResult,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py::test_wechat_domain_models_serialize_nested_payloads -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.domain.wechat'`.

- [ ] **Step 3: Implement domain dataclasses**

Create `nutmeg/domain/wechat.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py::test_wechat_domain_models_serialize_nested_payloads -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/domain/wechat.py tests/test_wechat_publisher_service.py
git commit -m "feat: add wechat publisher domain models"
```

### Task 2: Article Pack Service

**Files:**
- Create: `nutmeg/services/wechat_publisher.py`
- Modify: `tests/test_wechat_publisher_service.py`

- [ ] **Step 1: Add failing service tests for selection, rendering, and artifacts**

Append these tests to `tests/test_wechat_publisher_service.py`:

```python
from nutmeg.services.wechat_publisher import WeChatPublisherService, WeChatPublisherValidationError


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
    payload["combinations"] = [{**payload["combinations"][0], "legs": [payload["combinations"][0]["legs"][0]]}]
    report_file = _write_report(tmp_path, payload)

    with pytest.raises(WeChatPublisherValidationError, match="at least two distinct matches"):
        WeChatPublisherService().generate_article_pack(
            report_file=report_file,
            output_dir=tmp_path / "wechat",
            thumb_media_id="cover-media",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.services.wechat_publisher'`.

- [ ] **Step 3: Implement the service**

Create `nutmeg/services/wechat_publisher.py`:

```python
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any, Protocol

import httpx

from nutmeg.domain.content import ComplianceAssessment
from nutmeg.domain.wechat import (
    WeChatArticlePack,
    WeChatArticleSelection,
    WeChatArtifacts,
    WeChatDraftPayload,
    WeChatDraftResult,
)
from nutmeg.services.content import ContentComplianceChecker, LONG_FORM_DISCLAIMER

WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_DRAFT_ADD_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"
DEFAULT_WECHAT_AUTHOR = "Nutmeg"
DEFAULT_WECHAT_TITLE = "今晚两场焦点战：公开赔率背后的五个变量"
DEFAULT_WECHAT_DIGEST = "从公开赛程、官方赔率变化和比赛变量出发，拆解两场焦点战的主要观察点与风险。"


class WeChatPublisherValidationError(ValueError):
    pass


class WeChatDraftError(RuntimeError):
    pass


class WeChatHttpClient(Protocol):
    def get(self, url: str, **kwargs): ...

    def post(self, url: str, **kwargs): ...


class WeChatPublisherService:
    def __init__(self, *, compliance_checker: ContentComplianceChecker | None = None) -> None:
        self._compliance_checker = compliance_checker or ContentComplianceChecker()

    def generate_article_pack(
        self,
        *,
        report_file: Path | str,
        output_dir: Path | str | None = None,
        thumb_media_id: str = "DRY_RUN_COVER_MEDIA_ID",
        author: str = DEFAULT_WECHAT_AUTHOR,
        source_url: str | None = None,
    ) -> WeChatArticlePack:
        report_path = Path(report_file)
        report = self._load_report(report_path)
        selections = self.select_matches(report, limit=2)
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        title = DEFAULT_WECHAT_TITLE
        digest = DEFAULT_WECHAT_DIGEST
        markdown = self.render_markdown(selections, report=report, generated_at=generated_at)
        html = self.render_html(markdown)
        compliance = self._assess_article(title=title, digest=digest, markdown=markdown)
        payload = WeChatDraftPayload(
            title=title,
            author=author,
            digest=digest,
            content_html=html,
            thumb_media_id=thumb_media_id,
            source_url=source_url,
        )
        pack = WeChatArticlePack(
            generated_at=generated_at,
            source_report_path=str(report_path),
            title=title,
            digest=digest,
            author=author,
            article_markdown=markdown,
            article_html=html,
            selections=selections,
            compliance=compliance,
            draft_payload=payload,
        )
        if output_dir is not None:
            artifacts = self.write_artifacts(pack, output_dir=Path(output_dir))
            pack = replace(pack, artifacts=artifacts)
            self._rewrite_artifact_json(pack)
        return pack

    def select_matches(self, report: dict[str, Any], *, limit: int = 2) -> list[WeChatArticleSelection]:
        legs_by_match: dict[str, list[dict[str, Any]]] = {}
        for combo in report.get("combinations") or []:
            for leg in combo.get("legs") or []:
                if isinstance(leg, dict) and leg.get("match_no"):
                    legs_by_match.setdefault(str(leg["match_no"]), []).append(leg)
        if len(legs_by_match) < limit:
            raise WeChatPublisherValidationError(
                "WeChat article pack requires at least two distinct matches."
            )
        selections = [self._selection_from_legs(match_no, legs) for match_no, legs in legs_by_match.items()]
        return sorted(selections, key=lambda item: item.score, reverse=True)[:limit]

    def render_markdown(
        self,
        selections: list[WeChatArticleSelection],
        *,
        report: dict[str, Any],
        generated_at: str,
    ) -> str:
        official_update = report.get("official_last_update") or "未知"
        source_page = report.get("source_page") or "中国竞彩网公开页面"
        lines = [
            f"# {DEFAULT_WECHAT_TITLE}",
            "",
            "本文基于公开赛程、竞彩足球官方赔率变化和赛前信息整理，定位是赛事数据观察，不是投注建议。",
            "",
            "## 今日观察问题",
            "",
            "热门方向是否已经被市场充分计入？两场比赛的主要风险是否会相互放大？",
            "",
            f"- 生成时间：{generated_at}",
            f"- 官方赔率更新时间：{official_update}",
            f"- 数据来源：{source_page}",
            "",
        ]
        for index, selection in enumerate(selections, start=1):
            pick_text = "；".join(selection.observed_picks) or "公开赔率样本"
            risk_text = "、".join(selection.risk_notes) or "临场信息"
            lines.extend(
                [
                    f"## 焦点战 {index}：{selection.match_name}",
                    "",
                    f"**核心问题：** {selection.selection_reason}",
                    "",
                    "### 变量一：基本面与赛程背景",
                    f"{selection.league} {selection.match_date} {selection.match_time}，{selection.home_team} 对阵 {selection.away_team}。这场的阅读重点不是单一结论，而是双方状态、赛程压力和主客场环境如何共同影响比赛节奏。",
                    "",
                    "### 变量二：公开赔率结构",
                    f"当前可观察样本包括：{pick_text}。赔率只能反映市场预期变化，不能把比赛结果提前确定。",
                    "",
                    "### 变量三：阵容与临场信息",
                    "赛前首发、轮换和关键位置缺口会改变比赛结构。临场名单公布前，任何判断都需要保留弹性。",
                    "",
                    "### 变量四：战术对位与节奏",
                    "需要观察控球方能否稳定推进，以及防守方在转换、定位球和落后后的节奏调整。",
                    "",
                    "### 变量五：主要不确定性",
                    f"这场的主要风险来自{risk_text}。如果早段进球、红黄牌或临场阵容出现变化，赛前观察框架需要重新评估。",
                    "",
                ]
            )
        lines.extend(
            [
                "## 组合观察：只讨论风险叠加",
                "",
                "如果把两场放在同一观察框架里，重点不是寻找所谓确定方向，而是理解风险如何叠加：热门热度、赔率波动、临场阵容和比赛节奏可能同时影响最终阅读。组合视角只用于风险管理和赛前研究，不构成任何投注建议。",
                "",
                "## 免责声明",
                "",
                LONG_FORM_DISCLAIMER,
            ]
        )
        return "\n".join(lines) + "\n"

    def render_html(self, markdown: str) -> str:
        html_lines: list[str] = []
        in_list = False
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                continue
            if line.startswith("- "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                html_lines.append(f"<li>{escape(line[2:])}</li>")
                continue
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if line.startswith("### "):
                html_lines.append(f"<h3>{escape(line[4:])}</h3>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{escape(line[3:])}</h2>")
            elif line.startswith("# "):
                html_lines.append(f"<h1>{escape(line[2:])}</h1>")
            else:
                html_lines.append(f"<p>{escape(line)}</p>")
        if in_list:
            html_lines.append("</ul>")
        return "\n".join(html_lines) + "\n"

    def write_artifacts(self, pack: WeChatArticlePack, *, output_dir: Path) -> WeChatArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        article_md = output_dir / "article.md"
        article_html = output_dir / "article.html"
        draft_payload = output_dir / "draft-payload.json"
        compliance = output_dir / "compliance.json"
        selected_matches = output_dir / "selected-matches.json"
        cover_prompt = output_dir / "cover-prompt.txt"
        checklist = output_dir / "publish-checklist.md"
        article_md.write_text(pack.article_markdown, encoding="utf-8")
        article_html.write_text(pack.article_html, encoding="utf-8")
        draft_payload.write_text(
            json.dumps(pack.draft_payload.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        compliance.write_text(
            json.dumps(pack.compliance.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        selected_matches.write_text(
            json.dumps([item.to_dict() for item in pack.selections], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cover_prompt.write_text(self.render_cover_prompt(pack), encoding="utf-8")
        checklist.write_text(self.render_publish_checklist(pack), encoding="utf-8")
        return WeChatArtifacts(
            article_markdown_path=str(article_md),
            article_html_path=str(article_html),
            draft_payload_path=str(draft_payload),
            compliance_path=str(compliance),
            selected_matches_path=str(selected_matches),
            cover_prompt_path=str(cover_prompt),
            publish_checklist_path=str(checklist),
        )

    def render_cover_prompt(self, pack: WeChatArticlePack) -> str:
        names = " / ".join(selection.match_name for selection in pack.selections)
        return (
            "公众号封面图提示词：深色足球数据专栏封面，标题区写“今晚两场焦点战”，"
            f"副标题体现“{names}”，画面避免彩票、金钱、收益符号，强调球场、数据线和战术板。\n"
        )

    def render_publish_checklist(self, pack: WeChatArticlePack) -> str:
        lines = [
            "# 公众号发布前检查清单",
            "",
            f"- 风险等级：{pack.compliance.risk_level}",
            f"- 发布建议：{pack.compliance.publish_recommendation}",
            "- [ ] 标题没有稳胆、必中、红单、收益等刺激词",
            "- [ ] 正文没有直接投注动作或跟单导流",
            "- [ ] 两场比赛都有五变量分析",
            "- [ ] 组合观察只讨论风险叠加",
            "- [ ] 免责声明保留在文末",
            "- [ ] 已在公众号后台人工预览",
        ]
        if pack.compliance.risk_reasons:
            lines.extend(["", "## 风险原因"])
            lines.extend([f"- {reason}" for reason in pack.compliance.risk_reasons])
        return "\n".join(lines) + "\n"

    def _load_report(self, report_file: Path) -> dict[str, Any]:
        if not report_file.exists():
            raise WeChatPublisherValidationError(f"report file not found: {report_file}")
        try:
            payload = json.loads(report_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WeChatPublisherValidationError(f"report file is not valid JSON: {report_file}") from exc
        if not isinstance(payload, dict):
            raise WeChatPublisherValidationError("report file must contain a JSON object.")
        if not isinstance(payload.get("combinations"), list):
            raise WeChatPublisherValidationError("report file missing combinations list.")
        return payload

    def _selection_from_legs(self, match_no: str, legs: list[dict[str, Any]]) -> WeChatArticleSelection:
        first = legs[0]
        league = str(first.get("league") or "未知赛事")
        home = str(first.get("home_team") or "主队")
        away = str(first.get("away_team") or "客队")
        observed = []
        odds_values = []
        logic_parts = []
        for leg in legs:
            play = str(leg.get("play") or "玩法")
            pick = str(leg.get("pick") or "观察项")
            odds = _float_or_zero(leg.get("odds"))
            if odds:
                odds_values.append(odds)
                observed.append(f"{play} {pick} @ {odds:.2f}")
            logic = str(leg.get("logic") or "").strip()
            if logic:
                logic_parts.append(logic)
        score = 40 + max(odds_values or [0]) * 4 + len(legs) * 8
        if league in {"英超", "欧冠", "意甲", "西甲", "德甲"}:
            score += 18
        if any(team in f"{home}{away}" for team in ["AC米兰", "尤文", "国际米兰", "多特", "皇马", "巴萨", "曼联", "曼城", "阿森纳", "拜仁"]):
            score += 16
        reason = self._selection_reason(league=league, home=home, away=away, logic_parts=logic_parts)
        risk_notes = ["赔率波动", "临场阵容"]
        if max(odds_values or [0]) >= 5:
            risk_notes.append("高赔率样本波动")
        if league in {"意甲", "德甲", "英超", "欧冠"}:
            risk_notes.append("热门关注度")
        return WeChatArticleSelection(
            match_no=match_no,
            match_date=str(first.get("match_date") or ""),
            match_time=str(first.get("match_time") or ""),
            league=league,
            home_team=home,
            away_team=away,
            score=round(score, 2),
            selection_reason=reason,
            observed_picks=observed,
            risk_notes=sorted(set(risk_notes)),
        )

    def _selection_reason(
        self,
        *,
        league: str,
        home: str,
        away: str,
        logic_parts: list[str],
    ) -> str:
        if logic_parts:
            return logic_parts[0]
        return f"{league} {home} vs {away} 具备公开赔率、基本面和临场变量的分析空间。"

    def _assess_article(self, *, title: str, digest: str, markdown: str) -> ComplianceAssessment:
        return self._compliance_checker.assess(
            titles=[title],
            short_video_script="以上只是赛前数据观察，不构成任何投注建议，理性看球。",
            long_article=f"{digest}\n\n{markdown}",
        )

    def _rewrite_artifact_json(self, pack: WeChatArticlePack) -> None:
        if pack.artifacts.draft_payload_path:
            Path(pack.artifacts.draft_payload_path).write_text(
                json.dumps(pack.draft_payload.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: Run service tests to verify they pass**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/wechat_publisher.py tests/test_wechat_publisher_service.py
git commit -m "feat: generate wechat article packs"
```

### Task 3: WeChat Draft Client and Push Gate

**Files:**
- Modify: `nutmeg/services/wechat_publisher.py`
- Modify: `tests/test_wechat_publisher_service.py`

- [ ] **Step 1: Add failing tests for draft push, dry-run, and compliance block**

Append to `tests/test_wechat_publisher_service.py`:

```python
class FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self) -> None:
        self.get_calls = []
        self.post_calls = []

    def get(self, url: str, **kwargs):
        self.get_calls.append((url, kwargs))
        return FakeResponse({"access_token": "token-123", "expires_in": 7200})

    def post(self, url: str, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeResponse({"errcode": 0, "errmsg": "ok", "media_id": "draft-media-123"})


def test_wechat_draft_push_dry_run_does_not_call_http(tmp_path: Path) -> None:
    report_file = _write_report(tmp_path)
    service = WeChatPublisherService()
    pack = service.generate_article_pack(
        report_file=report_file,
        output_dir=tmp_path / "wechat",
        thumb_media_id="cover-media",
    )
    fake_http = FakeHttpClient()

    result = service.push_draft(
        pack=pack,
        app_id="app-id",
        app_secret="secret",
        http_client=fake_http,
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.media_id is None
    assert fake_http.get_calls == []
    assert fake_http.post_calls == []


def test_wechat_draft_push_posts_payload_when_confirmed(tmp_path: Path) -> None:
    report_file = _write_report(tmp_path)
    service = WeChatPublisherService()
    pack = service.generate_article_pack(
        report_file=report_file,
        output_dir=tmp_path / "wechat",
        thumb_media_id="cover-media",
    )
    fake_http = FakeHttpClient()

    result = service.push_draft(
        pack=pack,
        app_id="app-id",
        app_secret="secret",
        http_client=fake_http,
        dry_run=False,
    )

    assert result.status == "created"
    assert result.media_id == "draft-media-123"
    assert fake_http.get_calls[0][1]["params"]["appid"] == "app-id"
    assert fake_http.post_calls[0][1]["json"]["articles"][0]["thumb_media_id"] == "cover-media"


def test_wechat_draft_push_blocks_high_risk_pack(tmp_path: Path) -> None:
    report_file = _write_report(tmp_path)
    service = WeChatPublisherService()
    pack = service.generate_article_pack(
        report_file=report_file,
        output_dir=tmp_path / "wechat",
        thumb_media_id="cover-media",
    )
    blocked = pack.__class__(
        generated_at=pack.generated_at,
        source_report_path=pack.source_report_path,
        title="稳胆必中方案",
        digest=pack.digest,
        author=pack.author,
        article_markdown=pack.article_markdown + "\n稳胆必中，直接买主胜。\n",
        article_html=pack.article_html,
        selections=pack.selections,
        compliance=service._assess_article(
            title="稳胆必中方案",
            digest=pack.digest,
            markdown=pack.article_markdown + "\n稳胆必中，直接买主胜。\n",
        ),
        draft_payload=pack.draft_payload,
        artifacts=pack.artifacts,
    )

    with pytest.raises(WeChatPublisherValidationError, match="risk level BLOCKED"):
        service.push_draft(
            pack=blocked,
            app_id="app-id",
            app_secret="secret",
            http_client=FakeHttpClient(),
            dry_run=False,
        )
```

Also add this import at the top of the test file:

```python
import httpx
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py -v
```

Expected: FAIL with `AttributeError: 'WeChatPublisherService' object has no attribute 'push_draft'`.

- [ ] **Step 3: Add draft client methods**

Patch `nutmeg/services/wechat_publisher.py` inside `WeChatPublisherService` after `write_artifacts()`:

```python
    def push_draft(
        self,
        *,
        pack: WeChatArticlePack,
        app_id: str,
        app_secret: str,
        http_client: WeChatHttpClient | None = None,
        dry_run: bool = True,
        timeout_seconds: float = 20.0,
        output_dir: Path | str | None = None,
    ) -> WeChatDraftResult:
        if pack.compliance.risk_level in {"HIGH", "BLOCKED"}:
            raise WeChatPublisherValidationError(
                f"WeChat draft push blocked for risk level {pack.compliance.risk_level}."
            )
        if not app_id.strip() or not app_secret.strip():
            raise WeChatPublisherValidationError("WeChat app id and app secret are required.")
        if dry_run:
            result = WeChatDraftResult(status="dry_run", dry_run=True)
            self._write_draft_result_if_requested(result, output_dir=output_dir)
            return result
        client = http_client or httpx.Client(timeout=timeout_seconds)
        token = self._fetch_access_token(client, app_id=app_id, app_secret=app_secret)
        response = client.post(
            WECHAT_DRAFT_ADD_URL,
            params={"access_token": token},
            json=pack.draft_payload.to_dict(),
        )
        response.raise_for_status()
        payload = response.json()
        errcode = int(payload.get("errcode") or 0)
        if errcode != 0:
            result = WeChatDraftResult(
                status="error",
                error_code=errcode,
                error_message=str(payload.get("errmsg") or "WeChat draft API error"),
                dry_run=False,
            )
            self._write_draft_result_if_requested(result, output_dir=output_dir)
            raise WeChatDraftError(f"WeChat draft API error {errcode}: {result.error_message}")
        result = WeChatDraftResult(
            status="created",
            media_id=str(payload.get("media_id") or ""),
            created_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            dry_run=False,
        )
        self._write_draft_result_if_requested(result, output_dir=output_dir)
        return result

    def _fetch_access_token(
        self,
        client: WeChatHttpClient,
        *,
        app_id: str,
        app_secret: str,
    ) -> str:
        response = client.get(
            WECHAT_TOKEN_URL,
            params={
                "grant_type": "client_credential",
                "appid": app_id,
                "secret": app_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if isinstance(token, str) and token:
            return token
        errcode = payload.get("errcode")
        errmsg = payload.get("errmsg") or "missing access_token"
        raise WeChatDraftError(f"WeChat access token error {errcode}: {errmsg}")

    def _write_draft_result_if_requested(
        self,
        result: WeChatDraftResult,
        *,
        output_dir: Path | str | None,
    ) -> None:
        if output_dir is None:
            return
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "draft-result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/wechat_publisher.py tests/test_wechat_publisher_service.py
git commit -m "feat: add wechat draft push gate"
```

### Task 4: CLI Commands

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Append these tests near the existing `content-pack` / `jczq-mixed-report` tests in `tests/test_cli.py`:

```python

def _write_cli_jczq_report(tmp_path: Path) -> Path:
    report = {
        "generated_at": "2026-04-26T10:00:00+00:00",
        "official_last_update": "2026-04-26 18:33:24",
        "source_page": "https://www.sporttery.cn/jc/jsq/zqspf/",
        "source_api": "sample://jczq",
        "combinations": [
            {
                "name": "组合A",
                "risk": "高赔进取型",
                "total_odds": 439.93,
                "two_yuan_return": 879.86,
                "legs": [
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
                        "logic": "强强对话，赔率结构接近。",
                    },
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
                        "logic": "双方节奏开放，进球变量多。",
                    },
                ],
            }
        ],
    }
    report_file = tmp_path / "jczq-report.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return report_file


def test_wechat_article_pack_command_generates_artifacts(tmp_path) -> None:
    report_file = _write_cli_jczq_report(tmp_path)

    result = runner.invoke(
        app,
        [
            "wechat-article-pack",
            "--report-file",
            str(report_file),
            "--output-dir",
            str(tmp_path / "wechat"),
            "--thumb-media-id",
            "cover-media",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["title"].startswith("今晚两场焦点战")
    assert len(payload["selections"]) == 2
    assert payload["compliance"]["risk_level"] == "MEDIUM"
    assert Path(payload["artifacts"]["article_markdown_path"]).exists()
    assert Path(payload["artifacts"]["draft_payload_path"]).exists()


def test_wechat_draft_push_command_dry_run_reads_pack_dir(tmp_path) -> None:
    report_file = _write_cli_jczq_report(tmp_path)
    pack_dir = tmp_path / "wechat"
    first = runner.invoke(
        app,
        [
            "wechat-article-pack",
            "--report-file",
            str(report_file),
            "--output-dir",
            str(pack_dir),
            "--thumb-media-id",
            "cover-media",
            "--format",
            "json",
        ],
    )
    assert first.exit_code == 0

    result = runner.invoke(
        app,
        [
            "wechat-draft-push",
            "--pack-dir",
            str(pack_dir),
            "--app-id",
            "app-id",
            "--app-secret",
            "secret",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["dry_run"] is True
    assert (pack_dir / "draft-result.json").exists()
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py::test_wechat_article_pack_command_generates_artifacts tests/test_cli.py::test_wechat_draft_push_command_dry_run_reads_pack_dir -v
```

Expected: FAIL with Typer no such command.

- [ ] **Step 3: Add imports and options to CLI**

Patch `nutmeg/interfaces/cli.py` imports:

```python
from nutmeg.domain.content import ComplianceAssessment, ComplianceChecklistItem
from nutmeg.domain.wechat import WeChatArticlePack, WeChatArticleSelection, WeChatArtifacts, WeChatDraftPayload
from nutmeg.services.wechat_publisher import (
    WeChatDraftError,
    WeChatPublisherService,
    WeChatPublisherValidationError,
)
```

If `ComplianceAssessment` or `ComplianceChecklistItem` already exists in the file, do not duplicate imports.

Add option constants near content options:

```python
WECHAT_OUTPUT_DIR_OPTION = typer.Option(Path(".nutmeg-data/wechat"), "--output-dir")
WECHAT_THUMB_MEDIA_ID_OPTION = typer.Option("DRY_RUN_COVER_MEDIA_ID", "--thumb-media-id")
WECHAT_AUTHOR_OPTION = typer.Option("Nutmeg", "--author")
WECHAT_SOURCE_URL_OPTION = typer.Option(None, "--source-url")
WECHAT_PACK_DIR_OPTION = typer.Option(..., "--pack-dir")
WECHAT_APP_ID_OPTION = typer.Option(None, "--app-id")
WECHAT_APP_SECRET_OPTION = typer.Option(None, "--app-secret")
```

Add helper functions near existing service builders:

```python
def build_wechat_publisher_service() -> WeChatPublisherService:
    return WeChatPublisherService()


def _load_wechat_pack(pack_dir: Path) -> WeChatArticlePack:
    draft_payload_file = pack_dir / "draft-payload.json"
    compliance_file = pack_dir / "compliance.json"
    selections_file = pack_dir / "selected-matches.json"
    article_md_file = pack_dir / "article.md"
    article_html_file = pack_dir / "article.html"
    if not draft_payload_file.exists():
        raise WeChatPublisherValidationError(f"draft payload not found: {draft_payload_file}")
    draft_data = json.loads(draft_payload_file.read_text(encoding="utf-8"))
    article = draft_data["articles"][0]
    compliance_data = json.loads(compliance_file.read_text(encoding="utf-8"))
    selections_data = json.loads(selections_file.read_text(encoding="utf-8"))
    checklist = [
        ComplianceChecklistItem(
            question=str(item.get("question") or ""),
            status=str(item.get("status") or ""),
            evidence=str(item.get("evidence") or ""),
        )
        for item in compliance_data.get("checklist") or []
    ]
    compliance = ComplianceAssessment(
        risk_level=str(compliance_data.get("risk_level") or "BLOCKED"),
        risk_reasons=[str(item) for item in compliance_data.get("risk_reasons") or []],
        checklist=checklist,
        publish_recommendation=str(compliance_data.get("publish_recommendation") or "skip"),
    )
    selections = [
        WeChatArticleSelection(
            match_no=str(item.get("match_no") or ""),
            match_date=str(item.get("match_date") or ""),
            match_time=str(item.get("match_time") or ""),
            league=str(item.get("league") or ""),
            home_team=str(item.get("home_team") or ""),
            away_team=str(item.get("away_team") or ""),
            score=float(item.get("score") or 0),
            selection_reason=str(item.get("selection_reason") or ""),
            observed_picks=[str(value) for value in item.get("observed_picks") or []],
            risk_notes=[str(value) for value in item.get("risk_notes") or []],
        )
        for item in selections_data
    ]
    payload = WeChatDraftPayload(
        title=str(article.get("title") or ""),
        author=str(article.get("author") or ""),
        digest=str(article.get("digest") or ""),
        content_html=str(article.get("content") or ""),
        thumb_media_id=str(article.get("thumb_media_id") or ""),
        source_url=article.get("content_source_url"),
        need_open_comment=int(article.get("need_open_comment") or 0),
        only_fans_can_comment=int(article.get("only_fans_can_comment") or 0),
    )
    return WeChatArticlePack(
        generated_at="",
        source_report_path="",
        title=payload.title,
        digest=payload.digest,
        author=payload.author,
        article_markdown=article_md_file.read_text(encoding="utf-8"),
        article_html=article_html_file.read_text(encoding="utf-8"),
        selections=selections,
        compliance=compliance,
        draft_payload=payload,
        artifacts=WeChatArtifacts(
            article_markdown_path=str(article_md_file),
            article_html_path=str(article_html_file),
            draft_payload_path=str(draft_payload_file),
            compliance_path=str(compliance_file),
            selected_matches_path=str(selections_file),
            cover_prompt_path=str(pack_dir / "cover-prompt.txt"),
            publish_checklist_path=str(pack_dir / "publish-checklist.md"),
        ),
    )
```

- [ ] **Step 4: Add CLI command implementations**

Add these commands after `content_pack()` and before `daily_content_pack()`:

```python
@app.command("wechat-article-pack")
def wechat_article_pack(
    report_file: Path = CONTENT_REPORT_FILE_OPTION,
    output_dir: Path = WECHAT_OUTPUT_DIR_OPTION,
    thumb_media_id: str = WECHAT_THUMB_MEDIA_ID_OPTION,
    author: str = WECHAT_AUTHOR_OPTION,
    source_url: str | None = WECHAT_SOURCE_URL_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        pack = build_wechat_publisher_service().generate_article_pack(
            report_file=report_file,
            output_dir=output_dir,
            thumb_media_id=thumb_media_id,
            author=author,
            source_url=source_url,
        )
    except WeChatPublisherValidationError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    payload = pack.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"wechat-article-pack selections={len(pack.selections)} "
        f"risk={pack.compliance.risk_level} recommendation={pack.compliance.publish_recommendation}"
    )
    console.print(f"markdown={pack.artifacts.article_markdown_path}")
    console.print(f"html={pack.artifacts.article_html_path}")
    console.print(f"draft_payload={pack.artifacts.draft_payload_path}")


@app.command("wechat-draft-push")
def wechat_draft_push(
    pack_dir: Path = WECHAT_PACK_DIR_OPTION,
    app_id: str | None = WECHAT_APP_ID_OPTION,
    app_secret: str | None = WECHAT_APP_SECRET_OPTION,
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    confirm: bool = typer.Option(False, "--confirm"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        if not dry_run and not confirm:
            raise WeChatPublisherValidationError("wechat-draft-push --no-dry-run requires --confirm.")
        pack = _load_wechat_pack(pack_dir)
        result = build_wechat_publisher_service().push_draft(
            pack=pack,
            app_id=app_id or "dry-run-app-id",
            app_secret=app_secret or "dry-run-secret",
            dry_run=dry_run,
            output_dir=pack_dir,
        )
    except (WeChatPublisherValidationError, WeChatDraftError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(f"wechat-draft-push status={result.status} media_id={result.media_id}")
```

- [ ] **Step 5: Run CLI tests to verify they pass**

Run:

```bash
uv run pytest tests/test_cli.py::test_wechat_article_pack_command_generates_artifacts tests/test_cli.py::test_wechat_draft_push_command_dry_run_reads_pack_dir -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/interfaces/cli.py tests/test_cli.py
git commit -m "feat: add wechat publisher cli commands"
```

### Task 5: OpenClaw Router Support

**Files:**
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `tests/test_openclaw_router.py`

- [ ] **Step 1: Add failing router tests**

Append to `tests/test_openclaw_router.py`:

```python

def test_router_builds_wechat_article_pack_command() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "wechat-article-pack",
            "--report-file",
            ".nutmeg-data/jczq/report.json",
            "--output-dir",
            ".nutmeg-data/wechat/2026-04-28",
            "--thumb-media-id",
            "cover-media",
        ]
    )

    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "wechat-article-pack",
        "--report-file",
        ".nutmeg-data/jczq/report.json",
        "--output-dir",
        ".nutmeg-data/wechat/2026-04-28",
        "--thumb-media-id",
        "cover-media",
        "--format",
        "json",
    ]


def test_router_builds_wechat_draft_push_command_and_requires_confirmation() -> None:
    router = _load_router()

    request = router.parse_request(
        [
            "wechat-draft-push",
            "--pack-dir",
            ".nutmeg-data/wechat/2026-04-28",
            "--app-id",
            "app-id",
            "--app-secret",
            "secret",
            "--dry-run",
        ]
    )
    assert router.build_command(request) == [
        "uv",
        "run",
        "nutmeg",
        "wechat-draft-push",
        "--pack-dir",
        ".nutmeg-data/wechat/2026-04-28",
        "--app-id",
        "app-id",
        "--app-secret",
        "secret",
        "--dry-run",
        "--format",
        "json",
    ]

    with pytest.raises(router.RouterError, match="--confirm-draft"):
        router.parse_request(
            [
                "wechat-draft-push",
                "--pack-dir",
                ".nutmeg-data/wechat/2026-04-28",
                "--app-id",
                "app-id",
                "--app-secret",
                "secret",
                "--no-dry-run",
            ]
        )
```

- [ ] **Step 2: Run router tests to verify they fail**

Run:

```bash
uv run pytest tests/test_openclaw_router.py::test_router_builds_wechat_article_pack_command tests/test_openclaw_router.py::test_router_builds_wechat_draft_push_command_and_requires_confirmation -v
```

Expected: FAIL with `Unsupported action`.

- [ ] **Step 3: Add router actions**

Patch `SUPPORTED_ACTIONS` in `scripts/openclaw/nutmeg_command_router.py`:

```python
    "wechat-article-pack",
    "wechat-draft-push",
```

Add to `build_command()` after the `content` action block:

```python
    if action == "wechat-article-pack":
        command = [
            *base,
            "wechat-article-pack",
            "--report-file",
            options.report_file,
            "--output-dir",
            options.output_dir,
            "--thumb-media-id",
            options.thumb_media_id,
        ]
        if options.author:
            command.extend(["--author", options.author])
        if options.source_url:
            command.extend(["--source-url", options.source_url])
        command.extend(["--format", "json"])
        return command
    if action == "wechat-draft-push":
        command = [
            *base,
            "wechat-draft-push",
            "--pack-dir",
            options.pack_dir,
            "--app-id",
            options.app_id,
            "--app-secret",
            options.app_secret,
        ]
        command.append("--dry-run" if options.dry_run else "--no-dry-run")
        if options.confirm_draft:
            command.append("--confirm")
        command.extend(["--format", "json"])
        return command
```

Patch `_build_parser()` after the `content` parser:

```python
    wechat_article = subparsers.add_parser("wechat-article-pack")
    wechat_article.add_argument("--report-file", required=True)
    wechat_article.add_argument("--output-dir", default=".nutmeg-data/wechat")
    wechat_article.add_argument("--thumb-media-id", default="DRY_RUN_COVER_MEDIA_ID")
    wechat_article.add_argument("--author")
    wechat_article.add_argument("--source-url")

    wechat_draft = subparsers.add_parser("wechat-draft-push")
    wechat_draft.add_argument("--pack-dir", required=True)
    wechat_draft.add_argument("--app-id", required=True)
    wechat_draft.add_argument("--app-secret", required=True)
    wechat_draft.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    wechat_draft.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    wechat_draft.add_argument("--confirm-draft", action="store_true")
```

Patch `_validate_options()` text validation attr list:

```python
        "thumb_media_id",
        "author",
        "source_url",
        "pack_dir",
        "app_id",
        "app_secret",
```

Patch `_validate_options()` confirmation rules:

```python
    if options.action == "wechat-draft-push" and not options.dry_run and not options.confirm_draft:
        raise RouterError("`wechat-draft-push --no-dry-run` requires --confirm-draft.")
```

- [ ] **Step 4: Run router tests to verify they pass**

Run:

```bash
uv run pytest tests/test_openclaw_router.py::test_router_builds_wechat_article_pack_command tests/test_openclaw_router.py::test_router_builds_wechat_draft_push_command_and_requires_confirmation -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/openclaw/nutmeg_command_router.py tests/test_openclaw_router.py
git commit -m "feat: route wechat publisher commands"
```

### Task 6: Documentation and Verification

**Files:**
- Modify: `docs/architecture/content-publisher.md`
- Test: full targeted and repository verification

- [ ] **Step 1: Update architecture docs**

Append this section to `docs/architecture/content-publisher.md`:

```markdown
## WeChat Draft Publisher Extension

`wechat-article-pack` turns a JCZQ mixed-report JSON artifact into a WeChat official-account article package. The public article uses a restrained two-match data-analysis format: each focus match gets five variables, and the combination section discusses only risk overlap.

`wechat-draft-push` can create a WeChat draft from the local package, but it requires explicit confirmation for real network use. v1 never calls the WeChat publish endpoint; final publish stays in the WeChat backend after human review.

The extension writes `.nutmeg-data/wechat/<date>/article.md`, `article.html`, `draft-payload.json`, `compliance.json`, `selected-matches.json`, `cover-prompt.txt`, and `publish-checklist.md`. Only LOW and MEDIUM compliance results may be pushed to draft; HIGH and BLOCKED packs remain local artifacts.
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run pytest tests/test_wechat_publisher_service.py tests/test_cli.py::test_wechat_article_pack_command_generates_artifacts tests/test_cli.py::test_wechat_draft_push_command_dry_run_reads_pack_dir tests/test_openclaw_router.py::test_router_builds_wechat_article_pack_command tests/test_openclaw_router.py::test_router_builds_wechat_draft_push_command_and_requires_confirmation -v
```

Expected: PASS.

- [ ] **Step 3: Run lint/compile/verify**

Run:

```bash
uv run ruff check nutmeg/domain/wechat.py nutmeg/services/wechat_publisher.py nutmeg/interfaces/cli.py tests/test_wechat_publisher_service.py tests/test_cli.py tests/test_openclaw_router.py scripts/openclaw/nutmeg_command_router.py
python -m compileall nutmeg scripts/openclaw
scripts/verify.sh
```

Expected: all commands exit 0. If `scripts/verify.sh` fails because of unrelated pre-existing failures, capture the failing test names and rerun the focused tests to preserve evidence for this feature.

- [ ] **Step 4: Manual smoke command**

Run:

```bash
uv run nutmeg jczq-mixed-report --provider sample --output-dir .nutmeg-data/jczq-smoke --format json > /tmp/jczq-smoke.json
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/jczq-smoke.json').read_text())
report_path = payload['artifacts']['report_json_path']
print(report_path)
PY
```

Then use the printed report path:

```bash
uv run nutmeg wechat-article-pack \
  --report-file PRINTED_REPORT_PATH \
  --output-dir .nutmeg-data/wechat-smoke \
  --thumb-media-id DRY_RUN_COVER_MEDIA_ID \
  --format json

uv run nutmeg wechat-draft-push \
  --pack-dir .nutmeg-data/wechat-smoke \
  --app-id dry-run-app \
  --app-secret dry-run-secret \
  --dry-run \
  --format json
```

Expected: article pack command returns two selections and artifact paths; draft push returns `status: dry_run` and writes `.nutmeg-data/wechat-smoke/draft-result.json`.

- [ ] **Step 5: Commit docs and verification-ready state**

```bash
git add docs/architecture/content-publisher.md
git commit -m "docs: document wechat draft publisher workflow"
```

## Self-Review

- Spec coverage: Tasks implement domain models, two-match article generation, combination-observation language, compliance gates, local artifacts, draft API client, explicit confirmation, CLI, OpenClaw router, docs, and verification.
- Scope boundary: No auto-publish endpoint is implemented. The only network action is `draft/add`, gated by `--no-dry-run --confirm` in CLI and `--confirm-draft` in router.
- Type consistency: `WeChatArticlePack`, `WeChatArticleSelection`, `WeChatDraftPayload`, `WeChatDraftResult`, and `WeChatArtifacts` are defined in Task 1 and used consistently in Tasks 2-4.
- Placeholder scan: The plan contains no TBD/TODO placeholders and every code-writing step includes concrete code or exact patch content.
