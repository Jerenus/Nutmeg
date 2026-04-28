from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from nutmeg.domain.content import (
    ComplianceAssessment,
    ComplianceChecklistItem,
    ContentArtifacts,
    ContentBatch,
    ContentCandidate,
    ContentPack,
)

SHORT_VIDEO_DISCLAIMER = "以上只是赛前数据观察，不构成任何投注建议，理性看球。"
LONG_FORM_DISCLAIMER = (
    "本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。"
    "比赛结果具有不确定性，请理性看待。"
)


class ContentValidationError(ValueError):
    pass


class ContentLlmError(RuntimeError):
    pass


class ContentLlmProvider(Protocol):
    provider_label: str

    def generate(self, prompt: str) -> str: ...


class OpenClawContentLlmProvider:
    def __init__(
        self,
        *,
        model: str = "nyu-openai-chat/gpt-5.5",
        timeout_seconds: int = 120,
        command: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._command = command or default_openclaw_command()
        self._runner = runner or subprocess.run

    @property
    def provider_label(self) -> str:
        return f"openclaw:{self._model}"

    def generate(self, prompt: str) -> str:
        cmd = [
            self._command,
            "infer",
            "model",
            "run",
            "--json",
            "--model",
            self._model,
            "--prompt",
            prompt,
        ]
        try:
            result = self._runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ContentLlmError(
                f"OpenClaw CLI not found for content generation: attempted {self._command}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ContentLlmError("OpenClaw content generation timed out.") from exc
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            raise ContentLlmError(f"OpenClaw content generation failed{detail}")
        return self._extract_text(result.stdout)

    def _extract_text(self, stdout: str) -> str:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ContentLlmError("OpenClaw did not return JSON output.") from exc
        if isinstance(payload, dict):
            direct = payload.get("output_text")
            if isinstance(direct, str) and direct.strip():
                return direct.strip()
            outputs = payload.get("outputs")
            if isinstance(outputs, list):
                parts = [
                    item.get("text", "").strip()
                    for item in outputs
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ]
                if any(parts):
                    return "\n".join(part for part in parts if part)
        raise ContentLlmError("OpenClaw did not return text content.")


class DeterministicContentLlmProvider:
    provider_label = "deterministic:content-template"

    def generate(self, prompt: str) -> str:
        match_name = _regex_value(prompt, "match_name") or "这场比赛"
        competition = _regex_value(prompt, "competition") or "赛事"
        payload = {
            "titles": [
                f"赛前观察：{match_name}真正的变量是什么？",
                f"{competition}这场比赛，别只看结论",
                f"从公开数据看，{match_name}有两个细节",
                "这场比赛为什么值得单独拆解？",
                f"赛前研究样本：{match_name}的风险和变量",
            ],
            "short_video_script": (
                f"{match_name}值得关注，不是因为结论简单，而是因为它有足够多的赛前变量。"
                "从已有信息看，双方的状态、赛程压力和风险点都需要拆开看。"
                "市场预期可以作为观察样本，但不能当成比赛答案。"
                "真正要关注的是开局节奏、阵容完整度，以及落后方会不会提前改变比赛结构。"
            ),
            "long_article": (
                f"# {match_name}赛前观察\n\n"
                "## 一、为什么值得关注\n"
                "这场更适合作为公开数据和比赛变量的研究样本，而不是简单给一个结果。\n\n"
                "## 二、关键变量\n"
                "需要关注双方近期状态、赛程密度、阵容完整度和临场节奏。\n\n"
                "## 三、市场预期观察\n"
                "赔率或盘口变化只能说明市场预期，不代表比赛已经确定。\n\n"
                "## 四、主要风险\n"
                "足球比赛受临场阵容、红黄牌、早段进球和节奏变化影响很大。"
            ),
            "key_observation_points": ["赛程与阵容完整度", "开局节奏和中场对抗", "市场预期变化"],
            "uncertainty_factors": ["临场首发", "早段进球", "防线稳定性"],
        }
        return json.dumps(payload, ensure_ascii=False)


def default_openclaw_command() -> str:
    configured = _openclaw_command_env("NUTMEG_OPENCLAW_CLI") or _openclaw_command_env(
        "OPENCLAW_CLI"
    )
    if configured:
        return configured
    candidates = [
        Path.home() / ".nvm" / "versions" / "node" / "v22.22.1" / "bin" / "openclaw",
        Path("/Users/jz71/.nvm/versions/node/v22.22.1/bin/openclaw"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("openclaw") or "openclaw"


def _openclaw_command_env(name: str) -> str | None:
    value = os.environ.get(name)
    if not value:
        return None
    stripped = value.strip()
    if stripped.casefold() in {"1", "true", "yes", "on"}:
        return None
    return stripped


class ContentComplianceChecker:
    blocked_terms = [
        "买主胜",
        "买平",
        "买让负",
        "比分单",
        "串关这样搭",
        "跟我买",
        "上车",
        "兄弟们跟上",
        "闭眼入",
        "稳赚",
        "包中",
        "回血",
        "吃肉",
        "翻倍",
        "收米",
        "必中",
        "私信拿单",
        "进群",
        "付费方案",
        "会员单",
        "包赔",
        "投注平台",
        "开户链接",
        "邀请码",
        "充值",
        "跟单",
        "带单",
        "梭哈",
        "倍投",
        "买这个",
    ]
    high_terms = [
        "稳胆",
        "硬胆",
        "博胆",
        "胆材",
        "红单",
        "黑单",
        "连红",
        "冲这个",
        "直接冲",
        "稳了",
        "没有悬念",
        "锁定",
        "确定性很强",
    ]
    profit_terms = ["稳赚", "包中", "回血", "吃肉", "翻倍", "收米", "命中率", "盈利", "连红"]
    lead_terms = ["私信", "进群", "付费", "拿单", "方案", "会员单"]
    platform_terms = ["投注平台", "开户链接", "邀请码", "充值", "博彩站", "私彩"]
    medium_terms = [
        "主胜",
        "客胜",
        "平局",
        "盘口",
        "赔率",
        "市场预期",
        "概率",
        "模型",
        "倾向",
        "方向",
        "让球",
        "指数",
    ]

    def assess(
        self,
        *,
        titles: list[str],
        short_video_script: str,
        long_article: str,
    ) -> ComplianceAssessment:
        surfaces = [*titles, short_video_script, long_article]
        combined = "\n".join(surfaces)
        title_text = "\n".join(titles)
        reasons: list[str] = []

        blocked_hits = _hits(combined, self.blocked_terms)
        high_hits = _hits(combined, self.high_terms)
        profit_hits = _hits(combined, self.profit_terms)
        lead_hits = _hits(combined, self.lead_terms)
        platform_hits = _hits(combined, self.platform_terms)
        medium_hits = _hits(combined, self.medium_terms)
        short_has_disclaimer = SHORT_VIDEO_DISCLAIMER in short_video_script
        long_has_disclaimer = LONG_FORM_DISCLAIMER in long_article

        risk_level = "LOW"
        if medium_hits:
            risk_level = "MEDIUM"
            reasons.append("包含赛前倾向、赔率/盘口、模型或市场观察，需要人工审核")
        if not short_has_disclaimer or not long_has_disclaimer:
            risk_level = _max_risk(risk_level, "HIGH" if medium_hits else "MEDIUM")
            reasons.append("缺少必要免责声明")
        if high_hits:
            risk_level = _max_risk(risk_level, "HIGH")
            reasons.append(f"命中高风险确定性或刺激词：{', '.join(high_hits)}")
        if blocked_hits or lead_hits or profit_hits or platform_hits:
            risk_level = "BLOCKED"
            all_hits = sorted(set(blocked_hits + lead_hits + profit_hits + platform_hits))
            reasons.append(f"命中禁止的下注、收益、导流或平台相关表达：{', '.join(all_hits)}")
        if not reasons:
            reasons.append("纯体育数据/变量分析，未发现投注导向表达")

        checklist = [
            ComplianceChecklistItem(
                "是否给出了明确投注动作？",
                "failed" if blocked_hits else "passed",
                ", ".join(blocked_hits),
            ),
            ComplianceChecklistItem(
                "是否使用了稳胆、必中、红单、回血、上车等刺激词？",
                "failed" if high_hits or profit_hits else "passed",
                ", ".join(sorted(set(high_hits + profit_hits))),
            ),
            ComplianceChecklistItem(
                "是否暗示收益、命中率、连红、盈利？",
                "failed" if profit_hits else "passed",
                ", ".join(profit_hits),
            ),
            ComplianceChecklistItem(
                "是否引导私信、进群、付费、拿方案？",
                "failed" if lead_hits else "passed",
                ", ".join(lead_hits),
            ),
            ComplianceChecklistItem(
                "是否出现投注平台、链接、邀请码、充值信息？",
                "failed" if platform_hits else "passed",
                ", ".join(platform_hits),
            ),
            ComplianceChecklistItem(
                "是否只给结论，没有解释变量和风险？",
                "passed" if _has_variable_language(combined) else "needs_review",
                "" if _has_variable_language(combined) else "未明显看到变量/风险/不确定性表达",
            ),
            ComplianceChecklistItem(
                "是否缺少“不构成投注建议”的免责声明？",
                "failed" if not short_has_disclaimer or not long_has_disclaimer else "passed",
                "" if short_has_disclaimer and long_has_disclaimer else "免责声明不完整",
            ),
            ComplianceChecklistItem(
                "标题是否像体育分析，而不是博彩推荐？",
                "failed"
                if _hits(title_text, self.blocked_terms + self.high_terms)
                else "needs_review"
                if _hits(title_text, self.medium_terms)
                else "passed",
                ", ".join(_hits(title_text, self.blocked_terms + self.high_terms)),
            ),
        ]
        return ComplianceAssessment(
            risk_level=risk_level,
            risk_reasons=reasons,
            checklist=checklist,
            publish_recommendation=_publish_recommendation(risk_level),
        )


class ContentPublisherService:
    def __init__(
        self,
        *,
        llm_provider: ContentLlmProvider,
        compliance_checker: ContentComplianceChecker | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._compliance_checker = compliance_checker or ContentComplianceChecker()

    def select_candidates_from_report(
        self,
        report_file: Path | str,
        *,
        limit: int = 3,
    ) -> list[ContentCandidate]:
        if limit < 1:
            raise ContentValidationError("limit must be at least 1.")
        report = self._load_report(Path(report_file))
        issue = report["issue"]
        issue_id = str(issue.get("issue_id") or "unknown")
        recommendations = {
            int(item.get("match_no")): item
            for item in report.get("recommendations") or []
            if _is_intlike(item.get("match_no"))
        }
        candidates: list[ContentCandidate] = []
        for match in issue.get("matches") or []:
            if not _is_intlike(match.get("match_no")):
                continue
            match_no = int(match["match_no"])
            recommendation = recommendations.get(match_no, {})
            candidates.append(self._score_candidate(issue_id, match, recommendation))
        return sorted(
            candidates,
            key=lambda item: item.final_content_priority,
            reverse=True,
        )[:limit]

    def generate_from_report(
        self,
        *,
        report_file: Path | str,
        limit: int = 3,
        output_dir: Path | str | None = None,
    ) -> ContentBatch:
        report_path = Path(report_file)
        candidates = self.select_candidates_from_report(report_path, limit=limit)
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        warnings: list[str] = []
        packs = [self._generate_pack(candidate) for candidate in candidates]
        batch = ContentBatch(
            source_report_path=str(report_path),
            generated_at=generated_at,
            llm_provider=self._llm_provider.provider_label,
            candidates=candidates,
            packs=packs,
            artifacts=ContentArtifacts(),
            warnings=warnings,
        )
        if output_dir is not None:
            artifacts = self.write_artifacts(batch, output_dir=Path(output_dir))
            batch = ContentBatch(
                source_report_path=batch.source_report_path,
                generated_at=batch.generated_at,
                llm_provider=batch.llm_provider,
                candidates=batch.candidates,
                packs=batch.packs,
                artifacts=artifacts,
                warnings=batch.warnings,
            )
            Path(artifacts.json_path or "").write_text(
                json.dumps(batch.to_dict(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        return batch

    def write_artifacts(self, batch: ContentBatch, *, output_dir: Path) -> ContentArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        issue_id = "unknown"
        if batch.candidates:
            parts = batch.candidates[0].match_id.split(":")
            if len(parts) >= 2:
                issue_id = parts[1]
        stamp = batch.generated_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
        stem = f"content-pack-{issue_id}-{stamp}"
        json_path = output_dir / f"{stem}.json"
        markdown_path = output_dir / f"{stem}.md"
        json_path.write_text(
            json.dumps(batch.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        markdown_path.write_text(self.render_markdown(batch), encoding="utf-8")
        return ContentArtifacts(json_path=str(json_path), markdown_path=str(markdown_path))

    def render_markdown(self, batch: ContentBatch) -> str:
        lines = [
            "# Nutmeg 内容发布审核包",
            "",
            f"- 来源报告：`{batch.source_report_path}`",
            f"- 生成时间：{batch.generated_at}",
            f"- LLM：{batch.llm_provider}",
            "",
            "## 候选比赛评分",
        ]
        for candidate in batch.candidates:
            lines.append(
                f"- {candidate.match_name}｜优先级 {candidate.final_content_priority:.1f}｜"
                f"{candidate.selection_reason}"
            )
        for pack in batch.packs:
            lines.extend(
                [
                    "",
                    f"## {pack.match_name}",
                    "",
                    f"- 风险等级：{pack.risk_level}",
                    f"- 发布建议：{pack.publish_recommendation}",
                    f"- 选择理由：{pack.selection_reason}",
                    "",
                    "## 标题候选 5 个",
                ]
            )
            lines.extend([f"{index}. {title}" for index, title in enumerate(pack.titles, start=1)])
            lines.extend(["", "## 抖音 60 秒口播稿", "", pack.short_video_script])
            lines.extend(["", "## 公众号/知乎长文版", "", pack.long_article])
            lines.extend(["", "## 合规风险检查清单"])
            for item in pack.compliance_checklist:
                evidence = f" - {item.evidence}" if item.evidence else ""
                lines.append(f"- [{item.status}] {item.question}{evidence}")
            if pack.risk_reasons:
                lines.extend(["", "## 风险原因"])
                lines.extend([f"- {reason}" for reason in pack.risk_reasons])
            if pack.warnings:
                lines.extend(["", "## 生成警告"])
                lines.extend([f"- {warning}" for warning in pack.warnings])
        return "\n".join(lines) + "\n"

    def _load_report(self, report_file: Path) -> dict[str, Any]:
        if not report_file.exists():
            raise ContentValidationError(f"report file not found: {report_file}")
        try:
            payload = json.loads(report_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ContentValidationError(f"report file is not valid JSON: {report_file}") from exc
        if not isinstance(payload, dict):
            raise ContentValidationError("report file must contain a JSON object.")
        issue = payload.get("issue")
        if not isinstance(issue, dict):
            raise ContentValidationError("report file missing issue object.")
        matches = issue.get("matches")
        recommendations = payload.get("recommendations")
        if not isinstance(matches, list) or not matches:
            raise ContentValidationError("report file missing issue matches.")
        if not isinstance(recommendations, list) or not recommendations:
            raise ContentValidationError("report file missing recommendations.")
        return payload

    def _score_candidate(
        self,
        issue_id: str,
        match: dict[str, Any],
        recommendation: dict[str, Any],
    ) -> ContentCandidate:
        match_no = int(match["match_no"])
        home = str(match.get("home_team") or "主队")
        away = str(match.get("away_team") or "客队")
        match_name = f"{home} vs {away}"
        competition = str(match.get("competition") or "未知赛事")
        flags = [str(item) for item in match.get("risk_flags") or []]
        notes = [str(item) for item in match.get("notes") or []]
        rationale = str(recommendation.get("rationale") or "")
        risk_tier = str(recommendation.get("risk_tier") or "")
        confidence = _float_or_zero(recommendation.get("confidence"))

        attention = 35
        if competition in {"英超", "欧冠", "英足总杯", "意甲", "西甲", "德甲"}:
            attention += 18
        if any(team in match_name for team in POPULAR_TEAMS):
            attention += 18
        if "big_match" in flags or "杯" in competition:
            attention += 12
        if "relegation_pressure" in flags:
            attention += 7

        content = 30 + min(len(" ".join(notes)) * 0.7, 22) + min(len(flags) * 7, 28)
        if rationale:
            content += min(len(rationale) * 0.3, 18)
        if any(flag in flags for flag in EXPLAINABLE_FLAGS):
            content += 8

        stability = confidence * 100
        if risk_tier == "banker":
            stability += 8
        elif risk_tier == "cover":
            stability -= 6
        elif risk_tier == "volatile":
            stability -= 16

        compliance = 84
        if risk_tier == "banker":
            compliance -= 10
        if _hits(rationale, ContentComplianceChecker.high_terms):
            compliance -= 18
        if _hits(rationale, ContentComplianceChecker.blocked_terms):
            compliance -= 25
        if len(str(recommendation.get("pick") or "")) == 1:
            compliance -= 4

        attention = _clamp(attention)
        content = _clamp(content)
        stability = _clamp(stability)
        compliance = _clamp(compliance)
        final = round(
            attention * 0.25 + content * 0.35 + stability * 0.20 + compliance * 0.20,
            2,
        )
        reasons = []
        if attention >= 70:
            reasons.append("关注度高")
        if content >= 70:
            reasons.append("可讲变量多")
        if stability >= 65:
            reasons.append("模型相对稳定")
        if compliance < 70:
            reasons.append("表达需降博彩化")
        if not reasons:
            reasons.append("具备基本赛前拆解素材")
        return ContentCandidate(
            match_id=f"zucai:{issue_id}:{match_no}",
            match_no=match_no,
            match_name=match_name,
            competition=competition,
            match_time=match.get("match_date"),
            attention_score=attention,
            content_score=content,
            model_stability_score=stability,
            compliance_score=compliance,
            final_content_priority=final,
            selection_reason="，".join(reasons),
            source_recommendation={
                "pick": recommendation.get("pick"),
                "primary": recommendation.get("primary"),
                "confidence": recommendation.get("confidence"),
                "risk_tier": recommendation.get("risk_tier"),
                "rationale": recommendation.get("rationale"),
                "warnings": recommendation.get("warnings") or [],
                "odds_average": recommendation.get("odds_average"),
                "match_notes": notes,
                "risk_flags": flags,
            },
        )

    def _generate_pack(self, candidate: ContentCandidate) -> ContentPack:
        warnings: list[str] = []
        try:
            raw_text = self._llm_provider.generate(self._build_prompt(candidate))
            draft = _parse_llm_json(raw_text)
            llm_status = "generated"
        except (ContentLlmError, ContentValidationError, json.JSONDecodeError, ValueError) as exc:
            warnings.append(f"LLM output invalid; used safe fallback draft: {exc}")
            draft = _fallback_draft(candidate)
            llm_status = "fallback"

        titles = _normalize_titles(draft.get("titles"), candidate)
        short_video_script = _ensure_suffix(
            _string_field(draft, "short_video_script"),
            SHORT_VIDEO_DISCLAIMER,
        )
        long_article = _ensure_suffix(_string_field(draft, "long_article"), LONG_FORM_DISCLAIMER)
        key_observation_points = _string_list(draft.get("key_observation_points")) or [
            "赛程与阵容完整度",
            "攻防节奏变化",
        ]
        uncertainty_factors = _string_list(draft.get("uncertainty_factors")) or [
            "临场首发",
            "早段进球或红黄牌",
        ]
        assessment = self._compliance_checker.assess(
            titles=titles,
            short_video_script=short_video_script,
            long_article=long_article,
        )
        return ContentPack(
            match_id=candidate.match_id,
            match_name=candidate.match_name,
            competition=candidate.competition,
            match_time=candidate.match_time,
            content_priority=candidate.final_content_priority,
            selection_reason=candidate.selection_reason,
            risk_level=assessment.risk_level,
            risk_reasons=assessment.risk_reasons,
            compliance_checklist=assessment.checklist,
            titles=titles,
            short_video_script=short_video_script,
            long_article=long_article,
            key_observation_points=key_observation_points,
            uncertainty_factors=uncertainty_factors,
            disclaimer=LONG_FORM_DISCLAIMER,
            publish_recommendation=assessment.publish_recommendation,
            llm_provider=self._llm_provider.provider_label,
            llm_status=llm_status,
            warnings=warnings,
        )

    def _build_prompt(self, candidate: ContentCandidate) -> str:
        payload = {
            "task": "为足球赛事生成合规体育分析内容，不要输出下注指令。",
            "required_outputs": {
                "titles": "exactly 5 safe Chinese title candidates",
                "short_video_script": "Douyin 60-second oral script",
                "long_article": "WeChat/Zhihu long-form article",
                "key_observation_points": "array",
                "uncertainty_factors": "array",
            },
            "compliance_rules": [
                "禁止投注指令、收益承诺、带单跟单、私信进群、投注平台导流。",
                "只能表达观察、变量、风险、概率和不确定性。",
                "赔率/盘口只能解释市场预期，不能引申为购买建议。",
                "输出 JSON 对象，不要 markdown。",
            ],
            "candidate": candidate.to_dict(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


POPULAR_TEAMS = [
    "切尔西",
    "利兹联",
    "曼联",
    "阿森纳",
    "利物浦",
    "曼城",
    "热刺",
    "AC米兰",
    "尤文图斯",
    "国际米兰",
    "多特蒙德",
    "马赛",
    "巴黎",
    "皇家马德里",
    "巴塞罗那",
    "拜仁",
]

EXPLAINABLE_FLAGS = {
    "manager_change",
    "injuries",
    "fixture_congestion",
    "balanced_odds",
    "draw_risk",
    "relegation_pressure",
    "odds_shift",
    "big_match",
}


def _parse_llm_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ContentValidationError("LLM JSON root must be an object.")
    required = ["titles", "short_video_script", "long_article"]
    missing = [field for field in required if field not in payload]
    if missing:
        raise ContentValidationError(f"LLM JSON missing required fields: {', '.join(missing)}")
    return payload


def _fallback_draft(candidate: ContentCandidate) -> dict[str, Any]:
    return {
        "titles": [
            f"赛前观察：{candidate.match_name}的两个关键变量",
            f"{candidate.competition}这场比赛为什么值得看？",
            f"从公开数据看，{candidate.match_name}不只看结论",
            "这场赛前研究，重点不是答案而是变量",
            f"传统足彩样本：{candidate.match_name}的风险拆解",
        ],
        "short_video_script": (
            f"{candidate.match_name}这场更适合作为赛前观察样本。"
            "已有信息里，真正值得看的不是单一结果，而是双方状态、赛程和阵容变量。"
            "如果只看市场预期，容易忽略比赛节奏和临场变化。"
            "所以这场重点看前30分钟的压迫质量，以及落后一方的调整速度。"
        ),
        "long_article": (
            f"# {candidate.match_name}赛前观察\n\n"
            "## 一、为什么值得关注\n"
            "这场有足够多可拆解变量，适合从公开信息角度做赛前研究。\n\n"
            "## 二、核心数据和基本面\n"
            "重点关注近期状态、赛程压力、主客场表现和阵容完整度。\n\n"
            "## 三、市场预期观察\n"
            "市场预期只能作为外部情绪样本，不能替代比赛本身的不确定性。\n\n"
            "## 四、风险点\n"
            "临场首发、早段进球、防线稳定性和比赛节奏都会改变赛前判断。"
        ),
        "key_observation_points": ["近期状态", "赛程压力", "市场预期变化"],
        "uncertainty_factors": ["临场首发", "比赛节奏", "防线稳定性"],
    }


def _normalize_titles(raw_titles: Any, candidate: ContentCandidate) -> list[str]:
    titles = _string_list(raw_titles)
    deduped: list[str] = []
    seen: set[str] = set()
    for title in titles:
        normalized = title.strip(" \n\t-")
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    fallback = _fallback_draft(candidate)["titles"]
    for title in fallback:
        if len(deduped) >= 5:
            break
        if title not in seen:
            deduped.append(title)
            seen.add(title)
    return deduped[:5]


def _string_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ContentValidationError(f"LLM JSON field `{key}` must be non-empty text.")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _ensure_suffix(text: str, suffix: str) -> str:
    stripped = text.strip()
    if suffix in stripped:
        return stripped
    separator = "\n\n" if len(stripped) > 80 else " "
    return f"{stripped}{separator}{suffix}"


def _hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term and term in text]


def _has_variable_language(text: str) -> bool:
    return any(term in text for term in ["变量", "风险", "不确定", "观察", "取决于"])


def _max_risk(current: str, candidate: str) -> str:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "BLOCKED": 3}
    return candidate if order[candidate] > order[current] else current


def _publish_recommendation(risk_level: str) -> str:
    if risk_level == "LOW":
        return "publish"
    if risk_level == "MEDIUM":
        return "review"
    return "skip"


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_intlike(value: Any) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _regex_value(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\\s*:\\s*"([^"]+)"', text)
    return match.group(1) if match else None
