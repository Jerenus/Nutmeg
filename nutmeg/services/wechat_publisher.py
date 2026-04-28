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
from nutmeg.services.content import LONG_FORM_DISCLAIMER, ContentComplianceChecker

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
    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...


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

    def select_matches(
        self,
        report: dict[str, Any],
        *,
        limit: int = 2,
    ) -> list[WeChatArticleSelection]:
        legs_by_match: dict[str, list[dict[str, Any]]] = {}
        for combo in report.get("combinations") or []:
            for leg in combo.get("legs") or []:
                if isinstance(leg, dict) and leg.get("match_no"):
                    legs_by_match.setdefault(str(leg["match_no"]), []).append(leg)
        if len(legs_by_match) < limit:
            raise WeChatPublisherValidationError(
                "WeChat article pack requires at least two distinct matches."
            )
        selections = [
            self._selection_from_legs(match_no, legs)
            for match_no, legs in legs_by_match.items()
        ]
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
                    (
                        f"{selection.league} {selection.match_date} {selection.match_time}，"
                        f"{selection.home_team} 对阵 {selection.away_team}。这场的阅读重点"
                        "不是单一结论，而是双方状态、赛程压力和主客场环境如何共同影响比赛节奏。"
                    ),
                    "",
                    "### 变量二：公开赔率结构",
                    (
                        f"当前可观察样本包括：{pick_text}。赔率只能反映市场预期变化，"
                        "不能把比赛结果提前确定。"
                    ),
                    "",
                    "### 变量三：阵容与临场信息",
                    "赛前首发、轮换和关键位置缺口会改变比赛结构。临场名单公布前，任何判断都需要保留弹性。",
                    "",
                    "### 变量四：战术对位与节奏",
                    "需要观察控球方能否稳定推进，以及防守方在转换、定位球和落后后的节奏调整。",
                    "",
                    "### 变量五：主要不确定性",
                    (
                        f"这场的主要风险来自{risk_text}。如果早段进球、红黄牌或"
                        "临场阵容出现变化，赛前观察框架需要重新评估。"
                    ),
                    "",
                ]
            )
        lines.extend(
            [
                "## 组合观察：只讨论风险叠加",
                "",
                (
                    "如果把两场放在同一观察框架里，重点不是寻找所谓确定方向，而是理解"
                    "风险如何叠加：热门热度、赔率波动、临场阵容和比赛节奏可能同时影响"
                    "最终阅读。组合视角只用于风险管理和赛前研究，不构成任何投注建议。"
                ),
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
            raise WeChatPublisherValidationError(
                f"report file is not valid JSON: {report_file}"
            ) from exc
        if not isinstance(payload, dict):
            raise WeChatPublisherValidationError("report file must contain a JSON object.")
        if not isinstance(payload.get("combinations"), list):
            raise WeChatPublisherValidationError("report file missing combinations list.")
        return payload

    def _selection_from_legs(
        self,
        match_no: str,
        legs: list[dict[str, Any]],
    ) -> WeChatArticleSelection:
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
        popular_teams = [
            "AC米兰",
            "尤文",
            "国际米兰",
            "多特",
            "皇马",
            "巴萨",
            "曼联",
            "曼城",
            "阿森纳",
            "拜仁",
        ]
        if any(team in f"{home}{away}" for team in popular_teams):
            score += 16
        reason = self._selection_reason(
            league=league,
            home=home,
            away=away,
            logic_parts=logic_parts,
        )
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
