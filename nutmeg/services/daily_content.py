from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any, Protocol

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from nutmeg.domain.daily_content import (
    DailyContentArtifacts,
    DailyContentRun,
    InternalAnalysis,
    MatchContentPack,
    PublicScript,
    SeedanceTaskSpec,
    VideoSegment,
    VideoStoryboard,
)
from nutmeg.services.content import SHORT_VIDEO_DISCLAIMER, ContentComplianceChecker

STYLE_PROFILE_ID = "retro-football-manga-v3.1"
SEEDANCE_MODEL = "doubao-seedance-2-0-260128"
PRODUCTION_FACTORS = {
    "platform_retention": "前2秒强钩子：开场必须有大脸、足球、比分板悬念或可读中文标题。",
    "vertical_readability": "9:16优先：大脸、大球、大字，单屏只放1-3个战术关键词。",
    "series_packaging": (
        "固定栏目包装：漫画封面、战术笔记本、模拟回放、复古比分板、结尾悬念卡每日复用。"
    ),
    "character_continuity": "同一集内虚构队名、队色、号码、发型、角色职责保持一致。",
    "retro_manga_craft": (
        "原创80年代复古少年足球漫画动画，精细手绘线稿、赛璐璐上色、老漫画纸张颗粒。"
    ),
    "distribution_split": "抖音重钩子和完播；小红书同步封面标题与3-5张战术漫画图文卡。",
    "compliance": "不使用真实队徽、赞助商、官方球衣、真人脸、命名IP、投注动作或确定赛果。",
}
QUALITY_GATES = {
    "visual_craft": "精修赛璐璐动画：干净稳定线稿、非草稿、非粗糙涂鸦、非现代3D。",
    "continuity": "角色比例、队色、号码、发型和镜头语言在整场短片内一致。",
    "platform_fit": "首帧有悬念，字幕可读，竖屏中心主体清晰。",
    "football_relevance": "每个镜头都服务于压迫、反击、定位球、体能或第一粒进球等变量。",
    "safety": "无真实俱乐部标识、真人相似脸、赌博视觉、赔率平台或结果承诺。",
}
PLATFORM_OUTPUTS = {
    "douyin": "60秒竖屏短视频",
    "xiaohongshu": "视频封面 + 3-5张战术漫画图文卡",
}
V31_MASTER_STYLE_PROMPT = (
    "原创80年代复古少年足球漫画动画，精修赛璐璐动画，精细手绘黑色墨线，"
    "稳定角色模型，赛璐璐色块上色，老漫画纸张颗粒，速度线，集中线，"
    "汗水特写，热血但正经的赛前战术动画栏目。"
)
V31_CONTINUITY_PROMPT = (
    "保持同一集内虚构球队、队色、号码、发型、角色职责和线稿风格一致；"
    "镜头必须像连续动画片段，不像互不相关的海报。"
)
V31_PLATFORM_PROMPT = (
    "短视频生产影响因子：前2秒强钩子，固定栏目包装，竖屏大脸大球大字，"
    "1-3个可读中文关键词，适合抖音完播和小红书封面/图文拆卡。"
)
V31_NEGATIVE_PROMPT = (
    "不要真实队徽、真实球员脸、官方赞助、官方球衣、命名漫画动画游戏IP、"
    "粗糙草稿、低细节卡通、现代3D、写实转播、电竞海报光、投注单、赔率平台、"
    "金钱、赌博动作、确定赛果。"
)
MAJOR_LEAGUES = {
    "英超",
    "意甲",
    "西甲",
    "德甲",
    "法甲",
    "欧冠",
    "欧罗巴",
    "葡超",
}


class DailyContentProvider(Protocol):
    source_api: str
    source_page: str

    def fetch(self) -> dict[str, Any]: ...


class DailyContentService:
    def __init__(
        self,
        *,
        jczq_provider: DailyContentProvider,
        compliance_checker: ContentComplianceChecker | None = None,
    ) -> None:
        self._jczq_provider = jczq_provider
        self._compliance_checker = compliance_checker or ContentComplianceChecker()

    def build_run(
        self,
        *,
        run_date: str,
        output_dir: Path | str,
        provider_label: str,
        render_pdf: bool = False,
        public_script_override: str | None = None,
    ) -> DailyContentRun:
        value = self._jczq_provider.fetch()
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        run_id = f"daily-content-{run_date.replace('-', '')}-{datetime.now().strftime('%H%M%S')}"
        matches = [
            self._build_match_pack(
                match=match,
                value=value,
                public_script_override=public_script_override,
            )
            for match in _flatten_selling_matches(value)
        ]
        run = DailyContentRun(
            run_id=run_id,
            run_date=run_date,
            generated_at=generated_at,
            provider=provider_label,
            scope="popular-all",
            style_profile=STYLE_PROFILE_ID,
            matches=matches,
            warnings=_run_warnings(value, matches),
        )
        artifacts = self.write_artifacts(run, output_dir=Path(output_dir), render_pdf=render_pdf)
        return DailyContentRun(
            run_id=run.run_id,
            run_date=run.run_date,
            generated_at=run.generated_at,
            provider=run.provider,
            scope=run.scope,
            style_profile=run.style_profile,
            matches=run.matches,
            artifacts=artifacts,
            warnings=run.warnings,
        )

    def write_artifacts(
        self, run: DailyContentRun, *, output_dir: Path, render_pdf: bool
    ) -> DailyContentArtifacts:
        run_dir = (
            output_dir
            / run.run_date.replace("-", "")
            / f"run-{run.run_id.rsplit('-', 1)[-1]}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        json_path = run_dir / f"daily-match-content-{run.run_date.replace('-', '')}.json"
        markdown_path = run_dir / f"daily-match-content-{run.run_date.replace('-', '')}.md"
        pdf_path = run_dir / f"daily-match-content-{run.run_date.replace('-', '')}.pdf"
        manifest_path = run_dir / "seedance-manifest.json"
        status_path = run_dir / "seedance-status.json"
        artifacts = DailyContentArtifacts(
            run_dir=str(run_dir),
            json_path=str(json_path),
            markdown_path=str(markdown_path),
            pdf_path=str(pdf_path) if render_pdf else None,
            seedance_manifest_path=str(manifest_path),
            status_path=str(status_path),
        )
        enriched = DailyContentRun(
            run_id=run.run_id,
            run_date=run.run_date,
            generated_at=run.generated_at,
            provider=run.provider,
            scope=run.scope,
            style_profile=run.style_profile,
            matches=run.matches,
            artifacts=artifacts,
            warnings=run.warnings,
        )
        json_path.write_text(
            json.dumps(enriched.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        markdown_path.write_text(self.render_markdown(enriched), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(self.render_seedance_manifest(enriched), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._write_match_artifacts(enriched, run_dir=run_dir)
        status_path.write_text(
            json.dumps({"run_id": run.run_id, "tasks": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if render_pdf:
            self.render_pdf(enriched, pdf_path=pdf_path)
        return artifacts

    def _write_match_artifacts(self, run: DailyContentRun, *, run_dir: Path) -> None:
        matches_dir = run_dir / "matches"
        for match in run.matches:
            match_dir = matches_dir / _safe_path_part(match.match_id)
            match_dir.mkdir(parents=True, exist_ok=True)
            (match_dir / "videos").mkdir(exist_ok=True)
            (match_dir / "analysis.json").write_text(
                json.dumps(match.internal_analysis.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (match_dir / "public-script.md").write_text(
                "\n".join(
                    [
                        f"# {match.match_no} {match.home_team} vs {match.away_team}",
                        "",
                        match.public_script.voiceover_text,
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (match_dir / "storyboard.md").write_text(
                _render_match_storyboard(match),
                encoding="utf-8",
            )
            (match_dir / "seedance-vertical.json").write_text(
                json.dumps(
                    [task.to_dict() for task in match.seedance_specs.get("vertical", [])],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (match_dir / "seedance-horizontal.json").write_text(
                json.dumps(
                    [task.to_dict() for task in match.seedance_specs.get("horizontal", [])],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (match_dir / "compliance.json").write_text(
                json.dumps(match.compliance, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (match_dir / "production-factors.json").write_text(
                json.dumps(_production_factor_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def render_seedance_manifest(self, run: DailyContentRun) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        for match in run.matches:
            for ratio_key, specs in match.seedance_specs.items():
                for spec in specs:
                    task = spec.to_dict()
                    task["match_id"] = match.match_id
                    task["ratio_key"] = ratio_key
                    tasks.append(task)
        return {
            "run_id": run.run_id,
            "run_date": run.run_date,
            "style_profile": run.style_profile,
            **_production_factor_payload(),
            "run_dir": run.artifacts.run_dir,
            "status_path": run.artifacts.status_path,
            "tasks": tasks,
        }

    def render_markdown(self, run: DailyContentRun) -> str:
        lines = [
            f"# Nutmeg 每日逐场内容与动画审核包 {run.run_date}",
            "",
            f"- 生成时间：{run.generated_at}",
            f"- 范围：{run.scope}",
            f"- 动画风格：{run.style_profile}",
            "- 视频生成：审核后再提交 Seedance；本文档本身不会触发外部视频生成。",
            "",
        ]
        for match in run.matches:
            lines.extend(
                [
                    f"## {match.match_no} {match.home_team} vs {match.away_team}",
                    "",
                    f"- 赛事：{match.competition}",
                    f"- 开赛：{match.kickoff_time}",
                    f"- 内容级别：{match.focus_level} / {match.storyboard.segment_count} 段",
                    f"- 合规：{match.compliance.get('risk_level')} / "
                    f"{match.compliance.get('publish_recommendation')}",
                    "",
                    "### 内部分析",
                    "",
                    match.internal_analysis.opening_read,
                    "",
                    "- 足球变量：" + "；".join(match.internal_analysis.football_factors),
                    "- 市场变量：" + "；".join(match.internal_analysis.market_factors),
                    "- 核心风险：" + "；".join(match.internal_analysis.key_risks),
                    f"- 内部倾向：{match.internal_analysis.internal_lean}",
                    "",
                    "### 公开视频 60 秒口播",
                    "",
                    match.public_script.voiceover_text,
                    "",
                    "### 动画分镜",
                    "",
                ]
            )
            for segment in match.storyboard.segments:
                lines.append(
                    f"{segment.segment_no}. {segment.duration_seconds}s｜"
                    f"{segment.visual_direction}｜字幕：{segment.subtitle_text}"
                )
            if match.warnings:
                lines.extend(["", "### 警告", *[f"- {warning}" for warning in match.warnings]])
            lines.append("")
        return "\n".join(lines)

    def render_pdf(self, run: DailyContentRun, *, pdf_path: Path) -> None:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=16 * mm,
            bottomMargin=14 * mm,
        )
        styles = getSampleStyleSheet()
        title = ParagraphStyle(
            "DailyContentTitle",
            parent=styles["Title"],
            fontName="STSong-Light",
            fontSize=17,
            leading=23,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#7a1f12"),
        )
        h2 = ParagraphStyle(
            "DailyContentH2",
            parent=styles["Heading2"],
            fontName="STSong-Light",
            fontSize=12,
            leading=17,
            textColor=colors.HexColor("#0f5132"),
        )
        body = ParagraphStyle(
            "DailyContentBody",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=9.2,
            leading=13,
        )
        story = [
            Paragraph(_esc(f"Nutmeg 每日逐场内容与动画审核包 {run.run_date}"), title),
            Spacer(1, 4 * mm),
            Paragraph(_esc(f"生成时间：{run.generated_at}；比赛数：{len(run.matches)}"), body),
            Paragraph("视频生成需审核后另行确认提交；本 PDF 不触发外部生成。", body),
            Spacer(1, 4 * mm),
        ]
        for match in run.matches:
            story.append(
                Paragraph(_esc(f"{match.match_no} {match.home_team} vs {match.away_team}"), h2)
            )
            story.append(Paragraph(_esc(match.internal_analysis.opening_read), body))
            story.append(Paragraph(_esc(match.public_script.voiceover_text), body))
            story.append(Spacer(1, 3 * mm))
        doc.build(story)

    def _build_match_pack(
        self,
        *,
        match: dict[str, Any],
        value: dict[str, Any],
        public_script_override: str | None = None,
    ) -> MatchContentPack:
        match_no = str(match.get("matchNumStr") or "")
        home = str(match.get("homeTeamAbbName") or "主队")
        away = str(match.get("awayTeamAbbName") or "客队")
        competition = str(match.get("leagueAbbName") or "赛事")
        kickoff = " ".join(
            item
            for item in [str(match.get("matchDate") or ""), str(match.get("matchTime") or "")[:5]]
            if item
        )
        focus_level = _focus_level(match)
        segment_count = 6 if focus_level == "focus" else 4
        segment_duration = 10 if focus_level == "focus" else 15
        market_factors = _market_factors(match)
        internal_analysis = InternalAnalysis(
            opening_read=(
                f"{home} 对 {away} 这场的内容重点，不是简单给结论，"
                "而是把状态、赛程和市场预期拆开看。"
            ),
            football_factors=[
                f"{home}主场节奏与开局压迫",
                f"{away}客场反击和阵容完整度",
                "临场首发会显著影响比赛结构",
            ],
            market_factors=market_factors,
            key_risks=["临场轮换", "早段进球", "红黄牌和节奏突变"],
            internal_lean=_internal_lean(match, market_factors),
            confidence="medium" if focus_level == "focus" else "low",
            responsible_use_note="内部判断只用于赛前研究，不是投注指令。",
        )
        public_script = (
            _override_public_script(public_script_override)
            if public_script_override is not None
            else _public_script(match_no, competition, home, away)
        )
        compliance = self._compliance_checker.assess(
            titles=public_script.title_candidates,
            short_video_script=public_script.voiceover_text,
            long_article=(
                "本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，"
                "也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。"
            ),
        )
        storyboard = _storyboard(
            match_no=match_no,
            competition=competition,
            home=home,
            away=away,
            segment_count=segment_count,
            segment_duration=segment_duration,
        )
        vertical = [
            _seedance_spec(
                match_no=match_no,
                ratio_key="vertical",
                ratio="9:16",
                segment=segment,
                seed_base=match_no,
            )
            for segment in storyboard.segments
        ]
        horizontal = [
            _seedance_spec(
                match_no=match_no,
                ratio_key="horizontal",
                ratio="16:9",
                segment=segment,
                seed_base=f"{match_no}-h",
            )
            for segment in storyboard.segments
        ]
        seedance_specs = {"vertical": vertical, "horizontal": horizontal}
        warnings: list[str] = []
        if compliance.risk_level in {"HIGH", "BLOCKED"}:
            seedance_specs = {"vertical": [], "horizontal": []}
            warnings.append(
                "Public script is not eligible for video generation until compliance is revised."
            )
        return MatchContentPack(
            match_id=match_no,
            match_no=match_no,
            competition=competition,
            home_team=home,
            away_team=away,
            kickoff_time=kickoff,
            popularity_score=_popularity_score(match),
            focus_level=focus_level,
            internal_analysis=internal_analysis,
            public_script=public_script,
            storyboard=storyboard,
            seedance_specs=seedance_specs,
            compliance=compliance.to_dict(),
            evidence={
                "official_last_update": value.get("lastUpdateTime"),
                "source_api": self._jczq_provider.source_api,
                "source_page": self._jczq_provider.source_page,
            },
            warnings=warnings,
        )


def _flatten_selling_matches(value: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for group in value.get("matchInfoList") or []:
        for match in group.get("subMatchList") or []:
            if match.get("matchStatus") == "Selling":
                matches.append(match)
    return matches


def _production_factor_payload() -> dict[str, Any]:
    return {
        "style_profile": STYLE_PROFILE_ID,
        "production_factors": PRODUCTION_FACTORS,
        "quality_gates": QUALITY_GATES,
        "platform_outputs": PLATFORM_OUTPUTS,
    }


def _focus_level(match: dict[str, Any]) -> str:
    league = str(match.get("leagueAbbName") or "")
    if league in MAJOR_LEAGUES:
        return "focus"
    if _available_pool_count(match) >= 4:
        return "focus"
    return "standard"


def _available_pool_count(match: dict[str, Any]) -> int:
    return sum(1 for item in match.get("poolList") or [] if item.get("poolStatus") == "Selling")


def _market_factors(match: dict[str, Any]) -> list[str]:
    factors = ["赔率只作为市场预期观察，不等于比赛答案"]
    for pool in ["had", "hhad", "ttg", "crs", "hafu"]:
        payload = match.get(pool)
        if isinstance(payload, dict):
            update = " ".join(
                item for item in [payload.get("updateDate"), payload.get("updateTime")] if item
            )
            if update:
                factors.append(f"{pool.upper()} 更新 {update}")
    return factors[:4]


def _internal_lean(match: dict[str, Any], market_factors: list[str]) -> str:
    home = str(match.get("homeTeamAbbName") or "主队")
    away = str(match.get("awayTeamAbbName") or "客队")
    if len(market_factors) > 2:
        return f"内部只做观察：{home}与{away}的市场分歧需要结合临场阵容复核。"
    return "证据不足以给出强倾向，优先观察。"


def _public_script(match_no: str, competition: str, home: str, away: str) -> PublicScript:
    hook = f"{match_no}这场{competition}，看点不是一句强弱能讲完。"
    body = [
        f"{home}如果想掌控比赛，开局节奏和中场压迫会很关键。",
        f"{away}真正的机会，可能来自反击速度和定位球细节。",
        "市场预期可以作为观察样本，但不能代替比赛本身。",
        "临场首发、早段进球和节奏变化，都会让剧本重新改写。",
    ]
    closing = SHORT_VIDEO_DISCLAIMER
    return PublicScript(
        title_candidates=[
            f"{home}vs{away}：强弱之外的关键变量",
            f"{competition}赛前观察：这场别只看结论",
            f"{match_no}动画拆局：节奏才是主角",
        ],
        hook=hook,
        body=body,
        closing=closing,
        voiceover_text=" ".join([hook, *body, closing]),
        forbidden_terms_removed=[],
    )


def _override_public_script(text: str) -> PublicScript:
    return PublicScript(
        title_candidates=["人工覆盖脚本"],
        hook=text,
        body=[text],
        closing="",
        voiceover_text=text,
        forbidden_terms_removed=[],
    )


def _storyboard(
    *,
    match_no: str,
    competition: str,
    home: str,
    away: str,
    segment_count: int,
    segment_duration: int,
) -> VideoStoryboard:
    segments = []
    focus_beats = [
        (
            "2秒钩子",
            f"旧电视雪花闪一下，复古漫画封面展开，{home}与{away}的虚构少年队"
            "在球员通道对峙，正中央大字抛出本场悬念。",
            "大脸眼神特写切到足球旋转，再快速拉到漫画封面。",
            "悬念标题、赛事名、两队虚构色块。",
        ),
        (
            "主队武器",
            f"{home}的虚构核心球员启动压迫或控场，队友站位变成手绘箭头阵型。",
            "草皮低机位推镜，球鞋触球后出现速度线和汗水切脸。",
            "主队关键词：压迫 / 节奏 / 宽度三选一。",
        ),
        (
            "客队反制",
            f"{away}的虚构核心球员沿反击通道加速，画面被切成三格漫画分镜。",
            "分屏追跑，低角度跟拍，冲刺瞬间用集中线强调冲突。",
            "客队关键词：反击 / 定位球 / 中场抗压三选一。",
        ),
        (
            "战术笔记本",
            "战术笔记本翻页，手绘球场、压迫圈、反击箭头和体能提示依次浮现。",
            "俯视战术板变形为真实草皮，保持字幕大而少。",
            "只显示2-3个变量：第一球、转换、定位球。",
        ),
        (
            "模拟回放",
            "进入模拟精彩镜头：一次抢断后的直塞、门前扑救或边路传中，标明这是赛前想象。",
            "眼神特写、球旋转特写、射门腿部冻结姿势、墨线爆裂转场。",
            "模拟回放，不显示确定比分。",
        ),
        (
            "复古比分板",
            "老式复古比分板亮起，但不填最终比分，只留下下一集式悬念问题。",
            "比分板闪烁后切到漫画章节完结卡，字幕提醒理性看球。",
            "关键问题 + 免责声明。",
        ),
    ]
    standard_beats = [
        (
            "钩子封面",
            f"复古漫画封面直接打开，{home}与{away}的虚构队长在中圈对视。",
            "首帧大脸，随后拉到竖屏封面标题。",
            "本场最大悬念。",
        ),
        (
            "双方武器",
            f"{home}的压迫箭头与{away}的反击路线在同一张手绘战术图上碰撞。",
            "左右分屏，球员冲刺与战术箭头交替。",
            "主队武器 / 客队反制。",
        ),
        (
            "战术回放",
            "战术笔记本翻页后接一段模拟机会，强调第一粒进球和临场节奏的不确定。",
            "俯视战术板转为草皮低机位，再用墨线冻结关键动作。",
            "第一球 / 节奏 / 风险。",
        ),
        (
            "比分板收束",
            "复古比分板和漫画章节卡收尾，只给观看问题，不给确定赛果。",
            "旧电视闪烁、纸张颗粒、章节完结卡定格。",
            "理性看球免责声明。",
        ),
    ]
    beats = focus_beats if segment_count == 6 else standard_beats
    for index, (subtitle, visual, camera, overlay) in enumerate(beats[:segment_count], start=1):
        narration = f"{competition}{match_no}第{index}段：{subtitle}。"
        segments.append(
            VideoSegment(
                segment_no=index,
                duration_seconds=segment_duration,
                narration=narration,
                visual_direction=visual,
                camera_direction=camera,
                tactical_overlay=overlay,
                subtitle_text=subtitle,
                seedance_prompt_zh=_v31_seedance_prompt(
                    home=home,
                    away=away,
                    visual=visual,
                    camera=camera,
                    overlay=overlay,
                ),
            )
        )
    return VideoStoryboard(
        style_profile_id=STYLE_PROFILE_ID,
        ratio_primary="9:16",
        ratio_secondary="16:9",
        segment_count=segment_count,
        segments=segments,
    )


def _v31_seedance_prompt(
    *, home: str, away: str, visual: str, camera: str, overlay: str
) -> str:
    return (
        f"{V31_MASTER_STYLE_PROMPT} {V31_CONTINUITY_PROMPT} {V31_PLATFORM_PROMPT} "
        f"本集将{home}和{away}抽象成原创虚构少年足球队，只借用城市气质、颜色灵感和战术身份，"
        f"不复刻真实队徽、赞助商或官方球衣。画面：{visual} 镜头：{camera} "
        f"战术浮层：{overlay} 竖屏安全构图，中文标题清晰可读。"
        f"负向限制：{V31_NEGATIVE_PROMPT}"
    )


def _seedance_spec(
    *,
    match_no: str,
    ratio_key: str,
    ratio: str,
    segment: VideoSegment,
    seed_base: str,
) -> SeedanceTaskSpec:
    seed = int(hashlib.sha256(f"{seed_base}-{segment.segment_no}".encode()).hexdigest()[:8], 16)
    prompt = segment.seedance_prompt_zh
    if ratio == "16:9":
        prompt = prompt.replace("竖屏安全构图", "横屏栏目构图，保留战术蓝图空间")
    return SeedanceTaskSpec(
        task_key=f"{match_no}-{ratio_key}-segment-{segment.segment_no:02d}",
        provider="volcengine-ark",
        model=SEEDANCE_MODEL,
        content=[{"type": "text", "text": prompt}],
        resolution="720p",
        ratio=ratio,
        duration=segment.duration_seconds,
        seed=seed,
        camera_fixed=False,
        watermark=True,
        generate_audio=False,
        safety_identifier="nutmeg-owner-local",
    )


def _popularity_score(match: dict[str, Any]) -> float:
    score = 55.0
    if str(match.get("leagueAbbName") or "") in MAJOR_LEAGUES:
        score += 20.0
    score += min(_available_pool_count(match) * 4.0, 20.0)
    return min(score, 100.0)


def _run_warnings(value: dict[str, Any], matches: list[MatchContentPack]) -> list[str]:
    warnings = []
    if not value.get("lastUpdateTime"):
        warnings.append("官方赔率更新时间缺失。")
    if not matches:
        warnings.append("没有找到正在销售的竞彩足球比赛。")
    return warnings


def _safe_path_part(value: str) -> str:
    return value.replace("/", "-").replace(" ", "_")


def _render_match_storyboard(match: MatchContentPack) -> str:
    lines = [
        f"# {match.match_no} {match.home_team} vs {match.away_team} 动画分镜",
        "",
        f"- 风格：{match.storyboard.style_profile_id}",
        f"- 段数：{match.storyboard.segment_count}",
        "",
    ]
    for segment in match.storyboard.segments:
        lines.extend(
            [
                f"## Segment {segment.segment_no} ({segment.duration_seconds}s)",
                "",
                f"- 旁白：{segment.narration}",
                f"- 画面：{segment.visual_direction}",
                f"- 镜头：{segment.camera_direction}",
                f"- 战术浮层：{segment.tactical_overlay}",
                f"- 字幕：{segment.subtitle_text}",
                f"- Seedance Prompt：{segment.seedance_prompt_zh}",
                "",
            ]
        )
    return "\n".join(lines)


def _esc(value: Any) -> str:
    return escape(str(value), quote=False)
