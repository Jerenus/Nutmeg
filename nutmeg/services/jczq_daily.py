from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from nutmeg.domain.jczq_daily import (
    JczqDailyAdvisorReport,
    JczqDailyLeg,
    JczqDailyMatch,
    JczqDailyPlan,
)
from nutmeg.services.jczq import (
    SPORTTERY_JCZQ_PAGE,
    JczqCalculatorProvider,
    SampleJczqCalculatorProvider,
    SportteryJczqCalculatorProvider,
)
from nutmeg.services.jczq_strategy_memory import (
    load_strategy_memory,
    memory_pattern_positive,
    render_strategy_memory_notes,
)


class JczqTextSender(Protocol):
    def send_message(self, *, chat_id: int, text: str): ...


class JczqDailyAdvisorError(ValueError):
    pass


HAD_LABELS = {"h": "胜", "d": "平", "a": "负"}
HHAD_LABELS = {"h": "让胜", "d": "让平", "a": "让负"}
HAFU_LABELS = {
    "hh": "胜/胜",
    "hd": "胜/平",
    "ha": "胜/负",
    "dh": "平/胜",
    "dd": "平/平",
    "da": "平/负",
    "ah": "负/胜",
    "ad": "负/平",
    "aa": "负/负",
}
CRS_LABELS = {
    "s01s00": "1:0",
    "s02s00": "2:0",
    "s02s01": "2:1",
    "s03s01": "3:1",
    "s00s00": "0:0",
    "s01s01": "1:1",
    "s02s02": "2:2",
    "s00s01": "0:1",
    "s00s02": "0:2",
    "s01s02": "1:2",
}
TTG_KEYS = {"s1": "1球", "s2": "2球", "s3": "3球", "s4": "4球", "s5": "5球"}
OPEN_LEAGUE_HINTS = {"挪超", "荷乙", "美职", "德甲"}
CAUTIOUS_LEAGUE_HINTS = {"意甲", "西甲", "法甲"}


class JczqDailyAdvisorService:
    def __init__(
        self,
        *,
        provider: JczqCalculatorProvider | None = None,
        telegram_sender: JczqTextSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        betting_repository: Any | None = None,
    ) -> None:
        self._provider = provider or SportteryJczqCalculatorProvider()
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._betting_repository = betting_repository

    def build_report(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str | None = None,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        revision_instruction: str | None = None,
        record_final: bool = False,
    ) -> JczqDailyAdvisorReport:
        resolved_date = _normalize_date(run_date)
        value = self._provider.fetch()
        matches = self._extract_matches(value, run_date=resolved_date)
        if not matches:
            warnings = ["今日官方接口没有可售竞彩足球比赛。"]
        else:
            warnings = []
        strategy_memory = load_strategy_memory(Path(output_dir)) if output_dir is not None else {}
        plans = self._build_plans(
            matches, instruction=revision_instruction, strategy_memory=strategy_memory
        )
        summary = self._summary(
            plans,
            revision_instruction=revision_instruction,
            strategy_memory=strategy_memory,
        )
        report = JczqDailyAdvisorReport(
            run_date=resolved_date,
            generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            official_last_update=value.get("lastUpdateTime"),
            source_page=getattr(self._provider, "source_page", SPORTTERY_JCZQ_PAGE),
            source_api=getattr(self._provider, "source_api", "unknown"),
            matches=matches,
            plans=plans,
            summary=summary,
            revision={"version": 1, "instruction": revision_instruction},
            warnings=warnings,
        )
        if output_dir is not None:
            report = self._write_artifacts(report, output_dir=Path(output_dir))
        if dispatch_telegram:
            report = self._replace_dispatch(report, self._dispatch(report, dry_run=dry_run))
            if report.artifacts.get("context_path"):
                Path(str(report.artifacts["context_path"])).write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        if record_final and self._betting_repository is not None:
            self._betting_repository.record_jczq_report(report)
        return report

    def revise(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str,
        instruction: str,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        record_final: bool = False,
    ) -> JczqDailyAdvisorReport:
        resolved_date = _normalize_date(run_date)
        context_path = self._context_path(Path(output_dir), resolved_date)
        version = 1
        if context_path.exists():
            try:
                existing = json.loads(context_path.read_text(encoding="utf-8"))
                version = int((existing.get("revision") or {}).get("version") or 1) + 1
                base_report = _report_from_dict(existing)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                version = 2
                base_report = None
        else:
            base_report = None
        if base_report is None:
            report = self.build_report(
                run_date=resolved_date,
                output_dir=output_dir,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                revision_instruction=instruction,
                record_final=record_final,
            )
        else:
            strategy_memory = load_strategy_memory(Path(output_dir))
            plans = self._build_plans(
                base_report.matches, instruction=instruction, strategy_memory=strategy_memory
            )
            report = replace(
                base_report,
                generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
                plans=plans,
                summary=self._summary(
                    plans,
                    revision_instruction=instruction,
                    strategy_memory=strategy_memory,
                ),
                dispatch={"status": "skipped"},
            )
            report = self._write_artifacts(report, output_dir=Path(output_dir))
            if dispatch_telegram:
                report = self._replace_dispatch(report, self._dispatch(report, dry_run=dry_run))
        report = replace(
            report,
            revision={"version": version, "instruction": instruction},
        )
        if report.artifacts.get("context_path"):
            Path(str(report.artifacts["context_path"])).write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if record_final and self._betting_repository is not None:
            self._betting_repository.record_jczq_report(report)
        return report

    def render_message(self, report: JczqDailyAdvisorReport) -> str:
        lines = [
            f"【Nutmeg｜{report.run_date} 竞彩足球每日顾问】",
            f"官方赔率更新时间：{report.official_last_update or '未知'}",
            "仅供小注娱乐和赛前分析参考，不保证命中；出票前以竞彩终端为准。",
            "",
            report.summary,
            "",
            "今日盘口热度扫描：",
        ]
        for match in report.matches:
            lines.append(
                f"- {match.match_no} {match.home_team} vs {match.away_team}："
                f"{match.role}；大众方向 {match.hot_direction}；{match.confidence_note}"
            )
        for plan in report.plans:
            lines.extend(["", f"{plan.name}（{plan.kind}）", plan.description])
            legs = " × ".join(f"{leg.match_no}{leg.play}{leg.pick}" for leg in plan.legs)
            lines.append(legs)
            lines.append(
                f"估算总赔率：{plan.total_odds:.2f}；2元理论返奖：{plan.two_yuan_return:.2f}元"
            )
            lines.append(f"风险：{plan.risk_note}")
        if report.revision.get("instruction"):
            lines.extend(["", f"本次修正要求：{report.revision['instruction']}"])
        return "\n".join(lines)

    def _extract_matches(
        self, value: dict[str, Any], *, run_date: str | None = None
    ) -> list[JczqDailyMatch]:
        matches: list[JczqDailyMatch] = []
        for day in value.get("matchInfoList") or []:
            business_date = str(day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            for raw in day.get("subMatchList") or []:
                if str(raw.get("matchStatus") or "").casefold() != "selling":
                    continue
                candidates = self._candidates_for(raw)
                if not candidates:
                    continue
                had = raw.get("had") or {}
                h = _float(had.get("h"))
                d = _float(had.get("d"))
                a = _float(had.get("a"))
                hot = _hot_direction(h, d, a)
                role = _role(h, d, a, raw.get("leagueAbbName"))
                confidence = _confidence_note(h, d, a, role=role)
                matches.append(
                    JczqDailyMatch(
                        match_no=str(raw.get("matchNumStr") or ""),
                        match_date=str(raw.get("matchDate") or ""),
                        match_time=str(raw.get("matchTime") or ""),
                        league=str(raw.get("leagueAbbName") or ""),
                        home_team=str(raw.get("homeTeamAbbName") or ""),
                        away_team=str(raw.get("awayTeamAbbName") or ""),
                        status=str(raw.get("matchStatus") or ""),
                        hot_direction=hot,
                        role=role,
                        confidence_note=confidence,
                        candidates=candidates,
                    )
                )
        return matches

    def _candidates_for(self, raw: dict[str, Any]) -> list[JczqDailyLeg]:
        allowed = _allowed_pools(raw)
        candidates: list[JczqDailyLeg] = []
        base = {
            "match_no": str(raw.get("matchNumStr") or ""),
            "league": str(raw.get("leagueAbbName") or ""),
            "home_team": str(raw.get("homeTeamAbbName") or ""),
            "away_team": str(raw.get("awayTeamAbbName") or ""),
        }
        if "had" in allowed:
            pool = raw.get("had") or {}
            for key, label in HAD_LABELS.items():
                leg = _leg(base, pool=pool, pool_name="had", play="胜平负", key=key, pick=label)
                if leg:
                    candidates.append(replace(leg, logic=_had_logic(label, leg.odds)))
        if "hhad" in allowed:
            pool = raw.get("hhad") or {}
            for key, label in HHAD_LABELS.items():
                leg = _leg(
                    base,
                    pool=pool,
                    pool_name="hhad",
                    play="让球胜平负",
                    key=key,
                    pick=label,
                    goal_line=str(pool.get("goalLine") or ""),
                )
                if leg:
                    candidates.append(replace(leg, logic="用让球盘判断热门方向是否能打穿或被卡。"))
        if "ttg" in allowed:
            pool = raw.get("ttg") or {}
            for key, label in TTG_KEYS.items():
                leg = _leg(base, pool=pool, pool_name="ttg", play="总进球", key=key, pick=label)
                if leg:
                    candidates.append(
                        replace(leg, logic="避开胜负热度，改押比赛节奏和总进球落点。")
                    )
        if "hafu" in allowed:
            pool = raw.get("hafu") or {}
            for key, label in HAFU_LABELS.items():
                leg = _leg(base, pool=pool, pool_name="hafu", play="半全场", key=key, pick=label)
                if leg:
                    candidates.append(
                        replace(leg, logic="用上下半场剧本放大赔率，适合僵持后分胜负。")
                    )
        if "crs" in allowed:
            pool = raw.get("crs") or {}
            for key, label in CRS_LABELS.items():
                leg = _leg(base, pool=pool, pool_name="crs", play="比分", key=key, pick=label)
                if leg:
                    candidates.append(replace(leg, logic="比分是极限灵感入口，只适合极小注。"))
        return candidates

    def _build_plans(
        self,
        matches: list[JczqDailyMatch],
        *,
        instruction: str | None,
        strategy_memory: dict[str, Any] | None = None,
    ) -> list[JczqDailyPlan]:
        if not matches:
            return []
        no_score = bool(
            instruction and any(word in instruction for word in ["不要比分", "不比分", "不要 比分"])
        )
        target_high = 100 if instruction and ("100" in instruction or "提高" in instruction) else 60
        used_match_nos: set[str] = set()
        stable_base = self._build_stable_base_plan(matches)
        main = self._make_plan(
            "最终主方案",
            "main",
            "用胜平负低赔方向保生命力，把高赔点留给半全场/平局。",
            [
                _select_leg(matches, used_match_nos, pool="had", max_odds=1.9, target=1.35),
                _select_leg(matches, used_match_nos, pool="hafu", min_odds=3.5, target=4.2),
                _select_leg(matches, used_match_nos, pool="had", max_odds=1.9, target=1.35),
                _select_leg(matches, used_match_nos, pool="had", min_odds=3.0, target=3.4),
            ],
            "主方案仍依赖一到两个高波动平局/半全场点。",
        )
        inspiration = self._search_plan(
            matches,
            name="高赔率灵感票",
            kind="inspiration",
            description="跨胜平负、让球、总进球、半全场和比分做乘法杠杆，优先保留可解释剧本。",
            target_min=target_high,
            target_max=3000,
            no_score=no_score,
        )
        contrarian = self._search_plan(
            matches,
            name="反大众盘口票",
            kind="contrarian",
            description="规避低赔热门胜负，优先选择总进球、半全场、平局和让球卡盘路径。",
            target_min=120,
            target_max=500,
            no_score=no_score,
            contrarian=True,
        )
        false_signal = self._build_false_signal_plan(matches)
        extreme = self._search_plan(
            matches,
            name="极限小注票",
            kind="extreme",
            description="用比分和半全场追求极高赔率，仅适合极小注娱乐。",
            target_min=300,
            target_max=5000,
            no_score=False,
            extreme=True,
        )
        plans = [
            plan
            for plan in [stable_base, main, inspiration, contrarian, false_signal, extreme]
            if plan.legs
        ]
        plans = self._apply_revision_overrides(plans, matches, instruction=instruction)
        plans = self._apply_memory_overrides(plans, matches, strategy_memory=strategy_memory or {})
        return self._apply_comfort_risk_protection(plans, matches)

    def _build_false_signal_plan(self, matches: list[JczqDailyMatch]) -> JczqDailyPlan:
        legs: list[JczqDailyLeg | None] = []
        used_match_nos: set[str] = set()

        strong_cover = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_favorite_cover_leg,
            target=2.4,
        )
        if strong_cover is not None:
            legs.append(
                replace(strong_cover, logic="外部不利叙事可能被资金放大，真实实力差仍支持打穿。")
            )

        comfort_resistance = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_comfort_resistance_leg,
            target=2.2,
        )
        if comfort_resistance is not None:
            legs.append(
                replace(comfort_resistance, logic="热门方向过于顺滑，改用让球保护规避大热陷阱。")
            )

        tactical = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_tactical_process_leg,
            target=4.2,
        )
        if tactical is not None:
            legs.append(replace(tactical, logic="胜负叙事拥挤时，改用节奏/过程标的表达判断。"))

        second_cover = _best_false_signal_leg(
            matches,
            used_match_nos,
            selector=_favorite_cover_leg,
            target=2.4,
        )
        if second_cover is not None:
            legs.append(
                replace(second_cover, logic="不机械反热门，强弱差明确时继续保留打穿表达。")
            )

        return self._make_plan(
            "假信号审问票",
            "false_signal",
            "把天气、轮换、战意、裁判等信息视为市场叙事，识别过度放大的有利/不利因素，再混合让球、过程和节奏标的。",
            legs,
            "假信号票不机械反热门：同时保留大热规避、实力打穿和战术过程标的。",
        )

    def _build_stable_base_plan(self, matches: list[JczqDailyMatch]) -> JczqDailyPlan:
        selected: list[JczqDailyLeg] = []
        used_match_nos: set[str] = set()
        candidates: list[tuple[float, JczqDailyLeg]] = []
        for match in matches:
            if _is_comfort_risk(match):
                # Comfortable favorites can appear in the base only through a protected low-odds cover.
                cover = _comfort_resistance_leg(match)
                if cover is not None and cover.odds <= 2.05:
                    candidates.append((0.15 + abs(cover.odds - 1.75), cover))
                continue
            favorite = _favorite_had_with_odds(match)
            if favorite is not None:
                pick, odds = favorite
                if odds <= 1.65:
                    leg = _find_leg(match, pool="had", pick=pick)
                    if leg is not None:
                        role_bonus = -0.25 if match.role == "强胆场" else 0.0
                        candidates.append((role_bonus + abs(leg.odds - 1.45), leg))
            hhad_lows = [
                leg
                for leg in match.candidates
                if leg.pool == "hhad" and leg.pick in {"让胜", "让负"} and leg.odds <= 1.85
            ]
            if hhad_lows:
                leg = min(hhad_lows, key=lambda item: abs(item.odds - 1.7))
                candidates.append((0.25 + abs(leg.odds - 1.7), leg))
        for _, leg in sorted(candidates, key=lambda item: item[0]):
            if leg.match_no in used_match_nos:
                continue
            selected.append(replace(leg, logic=f"稳健底仓：{leg.logic}"))
            used_match_nos.add(leg.match_no)
            total = 1.0
            for item in selected:
                total *= item.odds
            if len(selected) >= 3 or (len(selected) >= 2 and total >= 8):
                break
        return self._make_plan(
            "稳健底仓A",
            "stable_base",
            "每日持续参与的基础组合，只保留强度明确或已保护的低波动腿。",
            selected,
            "底仓不追大冷，用来维持每日基础；机会票另行承担赔率弹性。",
        )

    def _apply_revision_overrides(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        instruction: str | None,
    ) -> list[JczqDailyPlan]:
        if not instruction:
            return plans
        updated = list(plans)
        wants_half_full_draw_away = "平负" in instruction or "平/负" in instruction
        if not wants_half_full_draw_away:
            return updated
        for match in matches:
            match_tokens = {match.match_no, match.match_no[-3:], match.home_team, match.away_team}
            if not any(token and token in instruction for token in match_tokens):
                continue
            leg = _find_leg(match, pool="hafu", pick="平/负")
            if leg is not None:
                updated = self._inject_leg(
                    updated,
                    target_kind="main",
                    leg=leg,
                    reason="用户修正信号已升权：半全场平/负进入主方案。",
                )
        return updated

    def _apply_memory_overrides(
        self,
        plans: list[JczqDailyPlan],
        matches: list[JczqDailyMatch],
        *,
        strategy_memory: dict[str, Any],
    ) -> list[JczqDailyPlan]:
        if not memory_pattern_positive(strategy_memory, "user_revision_hafu_draw_away"):
            return plans
        updated = list(plans)
        for match in matches:
            if "客胜低赔" not in match.hot_direction and match.role != "谨慎博弈场":
                continue
            leg = _find_leg(match, pool="hafu", pick="平/负")
            if leg is None:
                continue
            updated = self._inject_leg(
                updated,
                target_kind="main",
                leg=leg,
                reason="历史记忆升权：半全场平/负近期有效，已进入主方案。",
            )
            break
        return updated

    def _apply_comfort_risk_protection(
        self, plans: list[JczqDailyPlan], matches: list[JczqDailyMatch]
    ) -> list[JczqDailyPlan]:
        protected = list(plans)
        for match in [item for item in matches if _is_comfort_risk(item)]:
            favorite = _favorite_had_pick(match)
            draw_leg = _find_leg(match, pool="had", pick="平") or _find_leg(
                match, pool="hafu", pick="平/平"
            )
            cold_pick = "负" if favorite == "胜" else "胜" if favorite == "负" else "平"
            cold_leg = _find_leg(match, pool="had", pick=cold_pick)
            if favorite:
                protected = [
                    self._replace_plan_leg(
                        plan,
                        match_no=match.match_no,
                        current_pool="had",
                        current_pick=favorite,
                        replacement=draw_leg or cold_leg,
                        reason="舒服盘不能作为隐形胆，已替换为防平/防冷保护。",
                    )
                    for plan in protected
                ]
            if draw_leg and not _plans_contain_leg(
                protected, draw_leg.match_no, draw_leg.pool, draw_leg.pick
            ):
                protected = self._inject_leg(
                    protected,
                    target_kind="main",
                    leg=draw_leg,
                    reason="舒服盘审问：已强制加入防平保护。",
                )
            if cold_leg and not _plans_contain_leg(
                protected, cold_leg.match_no, cold_leg.pool, cold_leg.pick
            ):
                protected = self._inject_leg(
                    protected,
                    target_kind="inspiration",
                    leg=cold_leg,
                    reason="舒服盘审问：已强制加入防冷保护。",
                )
        return protected

    def _replace_plan_leg(
        self,
        plan: JczqDailyPlan,
        *,
        match_no: str,
        current_pool: str,
        current_pick: str,
        replacement: JczqDailyLeg | None,
        reason: str,
    ) -> JczqDailyPlan:
        if replacement is None:
            return plan
        changed = False
        legs = []
        for leg in plan.legs:
            if leg.match_no == match_no and leg.pool == current_pool and leg.pick == current_pick:
                legs.append(replacement)
                changed = True
            else:
                legs.append(leg)
        if not changed:
            return plan
        return self._make_plan(plan.name, plan.kind, plan.description, legs, reason)

    def _inject_leg(
        self,
        plans: list[JczqDailyPlan],
        *,
        target_kind: str,
        leg: JczqDailyLeg,
        reason: str,
    ) -> list[JczqDailyPlan]:
        updated: list[JczqDailyPlan] = []
        injected = False
        for plan in plans:
            if not injected and plan.kind == target_kind and plan.legs:
                legs = [item for item in plan.legs if item.match_no != leg.match_no]
                if len(legs) == len(plan.legs):
                    replace_index = _least_protective_leg_index(legs)
                    legs[replace_index] = leg
                else:
                    legs.append(leg)
                updated.append(
                    self._make_plan(plan.name, plan.kind, plan.description, legs, reason)
                )
                injected = True
            else:
                updated.append(plan)
        return updated

    def _search_plan(
        self,
        matches: list[JczqDailyMatch],
        *,
        name: str,
        kind: str,
        description: str,
        target_min: float,
        target_max: float,
        no_score: bool,
        contrarian: bool = False,
        extreme: bool = False,
    ) -> JczqDailyPlan:
        selected: list[JczqDailyLeg] = []
        used_pools: set[str] = set()
        pool_sequence = ["ttg", "hafu", "hhad", "had"]
        for idx, match in enumerate(matches[:4]):
            candidates = [leg for leg in match.candidates if not (no_score and leg.pool == "crs")]
            desired_pool = (
                pool_sequence[idx % len(pool_sequence)] if kind == "inspiration" else None
            )
            if desired_pool:
                preferred = [
                    leg for leg in candidates if leg.pool == desired_pool and 1.75 <= leg.odds <= 8
                ]
            elif extreme:
                preferred = [
                    leg for leg in candidates if leg.pool in {"crs", "hafu"} and leg.odds >= 4
                ]
            elif contrarian:
                preferred = [
                    leg
                    for leg in candidates
                    if leg.pool in {"ttg", "hafu", "hhad", "had"} and leg.odds >= 3
                ]
            else:
                preferred = [
                    leg
                    for leg in candidates
                    if leg.pool in {"ttg", "hafu", "hhad", "had", "crs"} and 1.75 <= leg.odds <= 8
                ]
            if no_score:
                preferred = [leg for leg in preferred if leg.pool != "crs"]
            if not preferred:
                preferred = candidates
            if not preferred:
                continue

            def score(leg: JczqDailyLeg) -> tuple[float, float]:
                pool_bonus = 0.35 if leg.pool not in used_pools else 0
                contrarian_bonus = 0.5 if leg.pool in {"ttg", "hafu"} else 0
                extreme_bonus = 0.7 if extreme and leg.pool == "crs" else 0
                return (
                    min(leg.odds, 8) + pool_bonus + contrarian_bonus + extreme_bonus,
                    -abs(leg.odds - 4.5),
                )

            choice = max(preferred, key=score)
            selected.append(choice)
            used_pools.add(choice.pool)
        plan = self._make_plan(
            name, kind, description, selected, "高赔票核心风险来自精确进球/半全场/平局落点。"
        )
        if plan.total_odds < target_min and not no_score:
            boosted = []
            for match in matches[:4]:
                pool_candidates = [
                    leg for leg in match.candidates if leg.pool in {"crs", "hafu"} and leg.odds >= 4
                ]
                boosted.append(
                    max(pool_candidates or match.candidates, key=lambda leg: min(leg.odds, 10))
                )
            plan = self._make_plan(
                name, kind, description, boosted, "赔率已提高，但命中波动显著增加。"
            )
        if plan.total_odds > target_max and kind != "extreme":
            softened = []
            for leg in selected:
                alternatives = [
                    candidate
                    for match in matches
                    for candidate in match.candidates
                    if candidate.match_no == leg.match_no and candidate.odds <= max(5.5, leg.odds)
                ]
                softened.append(min(alternatives or [leg], key=lambda item: abs(item.odds - 3.5)))
            plan = self._make_plan(
                name, kind, description, softened, "已控制赔率上限，但仍属于高波动组合。"
            )
        return plan

    def _make_plan(
        self,
        name: str,
        kind: str,
        description: str,
        legs: list[JczqDailyLeg | None],
        risk_note: str,
    ) -> JczqDailyPlan:
        clean = [leg for leg in legs if leg is not None]
        total = 1.0
        for leg in clean:
            total *= leg.odds
        total = round(total, 2) if clean else 0.0
        return JczqDailyPlan(
            name=name,
            kind=kind,
            description=description,
            legs=clean,
            total_odds=total,
            two_yuan_return=round(total * 2, 2),
            risk_note=risk_note,
        )

    def _summary(
        self,
        plans: list[JczqDailyPlan],
        *,
        revision_instruction: str | None,
        strategy_memory: dict[str, Any] | None = None,
    ) -> str:
        main = next((plan for plan in plans if plan.kind == "main"), None)
        stable = next((plan for plan in plans if plan.kind == "stable_base"), None)
        inspiration = next((plan for plan in plans if plan.kind == "inspiration"), None)
        text = (
            "每日固定仓位：先保留1-2张稳健底仓，再用机会票捕捉有逻辑的反人性赔率。"
            "舒服盘审问已启用：1.75-2.05的非强胆热门必须防平防冷。"
            "假信号审问已启用：外部信息先视为资金叙事，再判断真实实力差是否被遮蔽。"
        )
        if stable:
            text += f" 稳健底仓约{stable.total_odds:.2f}倍。"
        if main and inspiration:
            text += (
                f" 最终主方案约{main.total_odds:.2f}倍，"
                f"高赔率灵感票约{inspiration.total_odds:.2f}倍。"
            )
        memory_notes = render_strategy_memory_notes(strategy_memory or {})
        if memory_notes:
            text += " 历史记忆提示：" + "；".join(memory_notes) + "。"
        if revision_instruction:
            text += f" 已按你的修正想法重算：{revision_instruction}。"
        return text

    def _write_artifacts(
        self, report: JczqDailyAdvisorReport, *, output_dir: Path
    ) -> JczqDailyAdvisorReport:
        run_dir = output_dir / "daily" / report.run_date
        run_dir.mkdir(parents=True, exist_ok=True)
        context_path = run_dir / "context.json"
        markdown_path = run_dir / "report.md"
        artifacts = {"context_path": str(context_path), "markdown_path": str(markdown_path)}
        enriched = replace(report, artifacts=artifacts)
        markdown_path.write_text(self.render_message(enriched), encoding="utf-8")
        context_path.write_text(
            json.dumps(enriched.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return enriched

    def _dispatch(self, report: JczqDailyAdvisorReport, *, dry_run: bool) -> dict[str, Any]:
        text = self.render_message(report)
        if dry_run:
            return {
                "status": "dry_run",
                "chat_ids": list(self._telegram_chat_ids),
                "caption": text[:120],
            }
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return {
                "status": "skipped",
                "chat_ids": list(self._telegram_chat_ids),
                "error": "telegram not configured",
            }
        try:
            for chat_id in self._telegram_chat_ids:
                self._telegram_sender.send_message(chat_id=chat_id, text=text)
        except Exception as exc:  # pragma: no cover - defensive network seam
            return {
                "status": "failed",
                "chat_ids": list(self._telegram_chat_ids),
                "error": str(exc),
            }
        return {"status": "sent", "chat_ids": list(self._telegram_chat_ids)}

    def _replace_dispatch(
        self, report: JczqDailyAdvisorReport, dispatch: dict[str, Any]
    ) -> JczqDailyAdvisorReport:
        return replace(report, dispatch=dispatch)

    def _context_path(self, output_dir: Path, run_date: str) -> Path:
        return output_dir / "daily" / run_date / "context.json"


def build_jczq_daily_provider(provider: str) -> JczqCalculatorProvider:
    key = provider.strip().casefold()
    if key == "live":
        return SportteryJczqCalculatorProvider()
    if key == "sample":
        return SampleJczqCalculatorProvider()
    raise JczqDailyAdvisorError("provider must be `live` or `sample`.")


def _report_from_dict(payload: dict[str, Any]) -> JczqDailyAdvisorReport:
    matches = [_match_from_dict(item) for item in payload.get("matches") or []]
    plans = [
        JczqDailyPlan(
            name=str(item.get("name") or ""),
            kind=str(item.get("kind") or ""),
            description=str(item.get("description") or ""),
            legs=[_leg_from_dict(leg) for leg in item.get("legs") or []],
            total_odds=float(item.get("total_odds") or 0),
            two_yuan_return=float(item.get("two_yuan_return") or 0),
            risk_note=str(item.get("risk_note") or ""),
        )
        for item in payload.get("plans") or []
    ]
    return JczqDailyAdvisorReport(
        run_date=str(payload.get("run_date") or _normalize_date(None)),
        generated_at=str(payload.get("generated_at") or ""),
        official_last_update=payload.get("official_last_update"),
        source_page=str(payload.get("source_page") or SPORTTERY_JCZQ_PAGE),
        source_api=str(payload.get("source_api") or "unknown"),
        matches=matches,
        plans=plans,
        summary=str(payload.get("summary") or ""),
        revision=dict(payload.get("revision") or {"version": 1}),
        artifacts=dict(payload.get("artifacts") or {}),
        dispatch=dict(payload.get("dispatch") or {"status": "skipped"}),
        warnings=[str(item) for item in payload.get("warnings") or []],
    )


def _match_from_dict(payload: dict[str, Any]) -> JczqDailyMatch:
    return JczqDailyMatch(
        match_no=str(payload.get("match_no") or ""),
        match_date=str(payload.get("match_date") or ""),
        match_time=str(payload.get("match_time") or ""),
        league=str(payload.get("league") or ""),
        home_team=str(payload.get("home_team") or ""),
        away_team=str(payload.get("away_team") or ""),
        status=str(payload.get("status") or ""),
        hot_direction=str(payload.get("hot_direction") or ""),
        role=str(payload.get("role") or ""),
        confidence_note=str(payload.get("confidence_note") or ""),
        candidates=[_leg_from_dict(item) for item in payload.get("candidates") or []],
    )


def _leg_from_dict(payload: dict[str, Any]) -> JczqDailyLeg:
    return JczqDailyLeg(
        match_no=str(payload.get("match_no") or ""),
        league=str(payload.get("league") or ""),
        home_team=str(payload.get("home_team") or ""),
        away_team=str(payload.get("away_team") or ""),
        pool=str(payload.get("pool") or ""),
        play=str(payload.get("play") or ""),
        pick=str(payload.get("pick") or ""),
        odds=float(payload.get("odds") or 0),
        logic=str(payload.get("logic") or ""),
        goal_line=str(payload.get("goal_line") or ""),
        odds_update=str(payload.get("odds_update") or ""),
    )


def _normalize_date(value: str | None) -> str:
    if value is None or value == "today":
        return date.today().isoformat()
    return value


def _allowed_pools(raw: dict[str, Any]) -> set[str]:
    allowed = set()
    for item in raw.get("poolList") or []:
        if str(item.get("poolStatus") or "").casefold() == "selling":
            allowed.add(str(item.get("poolCode") or "").casefold())
    return allowed


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _leg(
    base: dict[str, str],
    *,
    pool: dict[str, Any],
    pool_name: str,
    play: str,
    key: str,
    pick: str,
    goal_line: str = "",
) -> JczqDailyLeg | None:
    odds = _float(pool.get(key))
    if odds is None or odds <= 0:
        return None
    update = " ".join(
        part
        for part in [str(pool.get("updateDate") or ""), str(pool.get("updateTime") or "")]
        if part
    )
    return JczqDailyLeg(
        match_no=base["match_no"],
        league=base["league"],
        home_team=base["home_team"],
        away_team=base["away_team"],
        pool=pool_name,
        play=play,
        pick=pick,
        odds=odds,
        logic="",
        goal_line=goal_line,
        odds_update=update,
    )


def _hot_direction(h: float | None, d: float | None, a: float | None) -> str:
    values = [("主胜", h), ("平局", d), ("客胜", a)]
    present = [(name, value) for name, value in values if value is not None]
    if not present:
        return "未知"
    name, value = min(present, key=lambda item: item[1])
    return f"{name}低赔({value:.2f})"


def _role(h: float | None, d: float | None, a: float | None, league: Any) -> str:
    league_name = str(league or "")
    low = (
        min(value for value in [h, d, a] if value is not None)
        if any(value is not None for value in [h, d, a])
        else 9
    )
    if low <= 1.35:
        return "强胆场"
    if league_name in OPEN_LEAGUE_HINTS:
        return "开放节奏场"
    if league_name in CAUTIOUS_LEAGUE_HINTS:
        return "谨慎博弈场"
    return "均衡分歧场"


def _confidence_note(
    h: float | None, d: float | None, a: float | None, *, role: str = ""
) -> str:
    low = (
        min(value for value in [h, d, a] if value is not None)
        if any(value is not None for value in [h, d, a])
        else None
    )
    if low is None:
        return "缺少胜平负概率基准。"
    implied = 1 / low
    if implied >= 0.72:
        return "胜平负方向可做胆，但让胜不能自动视为稳胆。"
    if 1.75 <= low <= 2.05 and role != "强胆场":
        return "有倾向但分歧仍大，舒服盘需防平防冷，不能作为隐形胆。"
    if implied >= 0.5:
        return "有倾向但分歧仍大，适合做组合变量。"
    return "均衡盘不宜做胆，更适合寻找反大众杠杆。"


def _had_logic(label: str, odds: float) -> str:
    if odds <= 1.4:
        return "低赔热门方向，适合保生命力但赔率杠杆有限。"
    if label == "平":
        return "平局是阻击大众胜负方向的主要反人性入口。"
    return "胜负方向赔率有分歧，需结合其他玩法放大或降风险。"


def _select_leg(
    matches: list[JczqDailyMatch],
    used_match_nos: set[str],
    *,
    pool: str,
    min_odds: float = 0,
    max_odds: float = 99,
    target: float,
) -> JczqDailyLeg | None:
    candidates: list[JczqDailyLeg] = []
    for match in matches:
        if match.match_no in used_match_nos:
            continue
        candidates.extend(
            leg for leg in match.candidates if leg.pool == pool and min_odds <= leg.odds <= max_odds
        )
    if not candidates:
        return None
    choice = min(candidates, key=lambda leg: abs(leg.odds - target))
    used_match_nos.add(choice.match_no)
    return choice


def _best_false_signal_leg(
    matches: list[JczqDailyMatch],
    used_match_nos: set[str],
    *,
    selector,
    target: float,
) -> JczqDailyLeg | None:
    candidates: list[JczqDailyLeg] = []
    for match in matches:
        if match.match_no in used_match_nos:
            continue
        leg = selector(match)
        if leg is not None:
            candidates.append(leg)
    if not candidates:
        return None
    choice = min(candidates, key=lambda leg: abs(leg.odds - target))
    used_match_nos.add(choice.match_no)
    return choice


def _favorite_cover_leg(match: JczqDailyMatch) -> JczqDailyLeg | None:
    favorite = _favorite_had_with_odds(match)
    if favorite is None:
        return None
    pick, odds = favorite
    if odds > 1.65:
        return None
    cover_pick = _hhad_cover_pick(match, pick)
    if cover_pick is None:
        return None
    return _find_leg(match, pool="hhad", pick=cover_pick)


def _comfort_resistance_leg(match: JczqDailyMatch) -> JczqDailyLeg | None:
    if not _is_comfort_risk(match):
        return None
    favorite = _favorite_had_pick(match)
    if favorite is None:
        return None
    if favorite == "胜":
        return _find_leg(match, pool="hhad", pick="让负")
    if favorite == "负":
        return _find_leg(match, pool="hhad", pick="让胜")
    return _find_leg(match, pool="had", pick="平")


def _tactical_process_leg(match: JczqDailyMatch) -> JczqDailyLeg | None:
    preferred = [
        leg
        for leg in match.candidates
        if (
            (leg.pool == "hafu" and leg.pick in {"平/胜", "平/负"})
            or (leg.pool == "ttg" and leg.pick in {"3球", "4球", "5球"})
        )
        and 3.4 <= leg.odds <= 6.5
    ]
    if not preferred:
        return None
    return min(preferred, key=lambda leg: abs(leg.odds - 4.2))


def _is_comfort_risk(match: JczqDailyMatch) -> bool:
    return "舒服盘" in match.confidence_note


def _favorite_had_pick(match: JczqDailyMatch) -> str | None:
    had = [leg for leg in match.candidates if leg.pool == "had" and leg.pick in {"胜", "负"}]
    if not had:
        return None
    favorite = min(had, key=lambda leg: leg.odds)
    if 1.75 <= favorite.odds <= 2.05:
        return favorite.pick
    return None


def _favorite_had_with_odds(match: JczqDailyMatch) -> tuple[str, float] | None:
    had = [leg for leg in match.candidates if leg.pool == "had" and leg.pick in {"胜", "负"}]
    if not had:
        return None
    favorite = min(had, key=lambda leg: leg.odds)
    return favorite.pick, favorite.odds


def _hhad_cover_pick(match: JczqDailyMatch, favorite: str) -> str | None:
    goal_lines = [leg.goal_line for leg in match.candidates if leg.pool == "hhad" and leg.goal_line]
    goal_line = goal_lines[0] if goal_lines else ""
    if favorite == "胜" and goal_line.startswith("-"):
        return "让胜"
    if favorite == "负" and goal_line.startswith("+"):
        return "让负"
    return None


def _find_leg(match: JczqDailyMatch, *, pool: str, pick: str) -> JczqDailyLeg | None:
    return next((leg for leg in match.candidates if leg.pool == pool and leg.pick == pick), None)


def _plans_contain_leg(
    plans: list[JczqDailyPlan], match_no: str, pool: str, pick: str
) -> bool:
    return any(
        leg.match_no == match_no and leg.pool == pool and leg.pick == pick
        for plan in plans
        for leg in plan.legs
    )


def _least_protective_leg_index(legs: list[JczqDailyLeg]) -> int:
    if not legs:
        return 0
    for index, leg in enumerate(legs):
        if leg.pool == "had" and leg.odds <= 2.05:
            return index
    return min(range(len(legs)), key=lambda index: legs[index].odds)
