"""Kernel-backed daily verbs: ``decision-read`` / ``decision-am`` / ``decision-settle``.

Store writes go through the kernel's typed Actions (``market_day_ingest``, forecast
revisions, reconcile/calibrate flows). The old append-only JSONL verb path and the
``NUTMEG_ONTOLOGY_V2`` switch between the two were removed 2026-10-03. Results are
``DecisionWorkflowResult`` (``nutmeg.decision.workflow_result``) so the CLI renders
every step, failures included.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

_MARKET_MAP = {"had": "md-had", "hhad": "md-hhad", "ttg": "md-ttg", "crs": "md-crs"}
_RESULT_SCORE = {"home": "1-0", "draw": "0-0", "away": "0-1"}
_ACCOUNT = "acct-jczq"


class KernelCountMismatch(RuntimeError):
    """A workflow report disagrees with its persisted Action truth."""


def _default_kernel():
    from nutmeg.config.settings import get_settings
    from nutmeg.ontology.wiring import build_ontology_kernel

    kernel = build_ontology_kernel(get_settings())
    kernel.initialize()
    return kernel


def _ingest_market_day(kernel, run_date: str, output_dir, requested_at: datetime) -> str:
    from nutmeg.decision.market_data import load_sporttery_snapshot
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.ingest.market_day import MarketDayIngestRequest

    sporttery = load_sporttery_snapshot(run_date, output_dir)
    if not sporttery:
        return f"decision-sense-v2 {run_date}: 无 sporttery 快照 — 空盘(合法)"
    bold_path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    sporttery_path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    intl = json.loads(bold_path.read_text(encoding="utf-8")) if bold_path.exists() else None

    result = kernel.market_day_ingest.ingest(
        MarketDayIngestRequest(
            business_date=run_date,
            sporttery_value=sporttery,
            intl_value=intl,
            actor_id="source:sporttery",
            actor_role=ActorRole.CONNECTOR,
            requested_at=requested_at,
            sporttery_retrieved_at=_file_source_time(sporttery_path),
            intl_retrieved_at=_file_source_time(bold_path) if intl is not None else None,
        )
    )
    intl_note = "" if intl else " | 无国际欧赔(降级体彩-only)"
    return (
        f"decision-sense-v2 {run_date}: 入库 {result.matches} 场 Match + "
        f"{result.snapshots} Snapshot（{result.teams} 队）{intl_note}"
    )


def _file_source_time(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _ingest_zucai_issue(kernel, issue: str, zucai_dir, requested_at: datetime) -> str:
    """zucai 感知 on the kernel: 复用老 loader 读已存快照 → typed Actions 入库。

    与老路径同一 canonical 身份函数(canonical_match_id);源快照缺失 → 可见降级不抛断。"""
    from nutmeg.ontology.actions.entity_actions import EntityActions
    from nutmeg.ontology.actions.market_actions import MarketActions
    from nutmeg.ontology.actions.match_actions import MatchActions
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.ingest.zucai_issue import (
        ZucaiIssueIngestRequest,
        ZucaiIssueIngestService,
        ZucaiMarketSource,
        ZucaiRow,
    )
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    try:
        matches, odds, dates = _default_loader(issue, zucai_dir)
    except FileNotFoundError as exc:
        return f"decision-sense-zucai-v2 {issue}: 源快照缺失 — {exc}"

    service_factory = ActionService(lambda: OntologyUnitOfWork(kernel.engine))

    def _snapshot_probe(match_id: str, provider: str, as_of: str) -> bool:
        with OntologyUnitOfWork(kernel.engine) as uow:
            return (
                uow.market.snapshot_id_for_source_at(
                    match_id, "md-had", "read_time", provider, as_of
                )
                is not None
            )

    service = ZucaiIssueIngestService(
        entity_actions=EntityActions(service_factory),
        match_actions=MatchActions(service_factory),
        market_actions=MarketActions(service_factory),
        artifact_ingest=kernel.artifact_ingest,
        snapshot_probe=_snapshot_probe,
    )

    odds_path = max(
        (p for p in Path(zucai_dir).glob(f"{issue}-odds*.json") if not _is_intl_odds(p)),
        key=lambda path: path.stat().st_mtime,
    )
    odds_value = json.loads(odds_path.read_text(encoding="utf-8"))
    source_at = _zucai_source_time(odds_value, odds_path)
    market_provider = _zucai_market_provider(odds_value)
    rows = tuple(
        ZucaiRow(
            match_no=m.match_no,
            home=m.home_team,
            away=m.away_team,
            competition=m.competition,
            match_date=dates.get(m.match_no),
            odds=odds.get(m.match_no),
        )
        for m in matches
    )
    result = service.ingest(
        ZucaiIssueIngestRequest(
            issue=issue,
            rows=rows,
            actor_id="source:zucai",
            actor_role=ActorRole.CONNECTOR,
            requested_at=requested_at,
            market_sources=(
                ZucaiMarketSource(
                    provider=market_provider,
                    value=odds_value,
                    retrieved_at=source_at,
                ),
            ),
        )
    )
    action_count = _committed_zucai_snapshot_actions(
        kernel,
        rows,
        provider=market_provider,
    )
    prep_count = len(rows)
    if action_count != prep_count:
        raise KernelCountMismatch(
            "kernel_snapshot_count_mismatch "
            f"issue={issue} actions={action_count} prep={prep_count} "
            f"service={result.snapshots}"
        )
    skipped_note = f" | 跳过 {len(result.skipped)}" if result.skipped else ""
    return (
        f"decision-sense-zucai-v2 {issue}: 入库 {result.matches} 场 Match + "
        f"{result.snapshots} Snapshot（{result.teams} 队）{skipped_note} | "
        f"kernel对账 Snapshot: actions落库 {action_count} / prep报告 {prep_count} / "
        f"service本次 {result.snapshots}"
    )


def _zucai_source_time(value: dict, path: Path) -> datetime:
    from nutmeg.decision.bj_time import BJ

    raw = value.get("captured_at")
    if isinstance(raw, str) and raw.strip():
        normalized = raw.strip().replace(" CST", "+08:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=BJ)
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _zucai_market_provider(value: dict) -> str:
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        return "intl"
    hosts = []
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            return "intl"
        hosts.append((urlparse(source["url"]).hostname or "").casefold())
    if hosts and all(host == "sporttery.cn" or host.endswith(".sporttery.cn") for host in hosts):
        return "zucai"
    return "intl"


def _committed_zucai_snapshot_actions(kernel, rows, *, provider: str) -> int:
    from nutmeg.decision.identity import canonical_match_id
    from nutmeg.ontology.identity.models import EntityType
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    with OntologyUnitOfWork(kernel.engine) as uow:
        match_ids = set()
        for row in rows:
            if not row.match_date:
                continue
            match_id = uow.identity.entity_by_external_id(
                EntityType.MATCH,
                provider="zucai-canonical",
                external_id=canonical_match_id(row.home, row.away, row.match_date),
            )
            if match_id is not None:
                match_ids.add(match_id)
        return uow.actions.count_committed_snapshot_matches(
            match_ids,
            provider=provider,
            snapshot_kind="read_time",
        )


def run_decision_am_v2(
    run_date: str,
    output_dir,
    *,
    kernel=None,
    fetch: bool = True,
    issue: str | None = None,
    zucai_dir=None,
):
    """am on the kernel: fetch (best-effort) → market_day_ingest (+可选 zucai 感知)。

    No judgment, no push. ``issue`` 给出时追加 zucai issue 入库(足彩泳道,与老路径同参数)。"""
    from nutmeg.decision.workflow_result import compose as _compose
    from nutmeg.decision.workflow_result import now_iso as _now_iso

    stamp = _now_iso()
    requested_at = datetime.fromisoformat(stamp)
    active_kernel = kernel if kernel is not None else _default_kernel()

    steps: list = []
    if fetch:
        from nutmeg.decision.fetch import fetch_day

        steps.append(("fetch", lambda: fetch_day(run_date, output_dir)))
    steps.append(
        ("sense-v2", lambda: _ingest_market_day(active_kernel, run_date, output_dir, requested_at))
    )
    if issue:
        zdir = Path(zucai_dir) if zucai_dir is not None else Path(".nutmeg-data/zucai")
        steps.append(
            (
                "sense-zucai-v2",
                lambda: _ingest_zucai_issue(active_kernel, issue, zdir, requested_at),
            )
        )
        # 身份映射随 sense 落盘:26122 手工反查(按 fair 值)把 3 场挂到了竞彩板的同队
        # Match 上——同一支队同一天出现在两个板面时,fair 匹配必然抢错身份。
        steps.append(
            (
                "store-ids",
                lambda: _write_zucai_store_ids(active_kernel, issue, zdir),
            )
        )
    return _compose("decision-am", run_date, "数据入库(ontology v2 kernel)", steps)


def _write_zucai_store_ids(kernel, issue: str, zucai_dir: Path) -> str:
    from nutmeg.decision.zucai_identity import write_store_ids

    return write_store_ids(issue, zucai_dir, kernel)


_ROUNDING_NOISE = 2e-3


def _renormalized(distribution):
    """四位小数的价格三面之和常是 0.9999 / 1.0001：内核按 1e-6 校验会整条拒收（2026-10-05
    26135 场11 的 18:30 新价因此没进内核，文件与内核从此分歧）。只吸收舍入噪声；偏差更大的
    原样交内核去拒收。带逐面因子的 Read 不动——各自缩放会破坏 Δ 的精确重构。"""
    if not isinstance(distribution, dict) or not distribution:
        return distribution
    try:
        total = sum(float(value) for value in distribution.values())
    except (TypeError, ValueError):
        return distribution
    if total <= 0 or abs(total - 1.0) > _ROUNDING_NOISE or abs(total - 1.0) <= 1e-9:
        return distribution
    return {key: float(value) / total for key, value in distribution.items()}


@dataclass(frozen=True)
class ReadSubmission:
    """一批 Read 交内核的结构化回执：收下的 read_id、被拒的 (read_id, 原因)。

    2026-10-08 B7：此前写临时文件 → 进程内跑 `decision-read` CLI → 从输出里解析「拒绝:」文本；
    原因里带换行 / 分号就会漏判被拒的 Read（10-05 26135 场11 被拒却记成已交就是这条链）。"""

    total: int
    committed: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]
    dropped_factors: int = 0

    def summary(self) -> str:
        msg = f"decision-read-v2: 摄取 {len(self.committed)}/{self.total} 条 Read(kernel)"
        if self.dropped_factors:
            msg += f" | 旧式因子丢弃 {self.dropped_factors}"
        if self.rejected:
            msg += " | 拒绝: " + "; ".join(f"{rid}:{why}" for rid, why in self.rejected)
        return msg


def submit_reads(payloads: list[dict], *, kernel=None,
                 idempotency_prefix: str = "read") -> ReadSubmission:
    """Commit each judged Read payload as a kernel ForecastRevision (no money, no push).

    Read payloads carry kernel match ids (and, when present, a kernel market snapshot id) +
    the market string; anything else is rejected (`unresolved_match` / `unresolved_snapshot`)
    — the legacy canonical-id / `S-…` snapshot resolvers were removed 2026-10-08 (every Read
    since 09-20 carries kernel ids). Old-style factors (direction/weight_pp) cannot be replayed
    as per-outcome deltas, so the belief is committed follow-market and the drop is counted,
    never faked; new-style factors that carry a per-outcome ``delta`` reconstructing
    belief−prior are kept.

    Kernel semantics unchanged: a Read with ``status == "draft"`` is an AI draft under its own
    judge; anything else is committed as ``judge:owner`` (zucai machine Reads included — see the
    2026-10-08 B2 note; changing it needs a separate sign-off).
    """
    from nutmeg.ontology.actions.forecast_actions import (
        CommitForecastRequest,
        DraftForecastRequest,
        FactorInput,
        ForecastActions,
    )
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.actions.service import ActionService
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    active_kernel = kernel if kernel is not None else _default_kernel()
    forecasts = ForecastActions(ActionService(lambda: OntologyUnitOfWork(active_kernel.engine)))
    with OntologyUnitOfWork(active_kernel.engine) as uow:
        known_matches = set(uow.identity.all_match_ids())

    committed: list[str] = []
    dropped_factors = 0
    rejected: list[tuple[str, str]] = []
    for payload in payloads:
        read_id = str(payload.get("read_id", ""))
        market = _MARKET_MAP.get(str(payload.get("market")))
        if market is None:
            rejected.append((read_id, "unmapped_market"))
            continue
        match_id = str(payload.get("match_id") or "")
        if match_id not in known_matches:
            rejected.append((read_id, "unresolved_match"))
            continue
        prior_snapshot_id = str(payload.get("snapshot_id") or "") or None
        if prior_snapshot_id is not None:
            with OntologyUnitOfWork(active_kernel.engine) as uow:
                if not uow.market.snapshot_exists_for(prior_snapshot_id, match_id, market):
                    rejected.append((read_id, "unresolved_snapshot"))
                    continue
        prior = payload.get("prior")
        belief = payload.get("belief")
        if not any(isinstance(f, dict) and isinstance(f.get("delta"), dict)
                   for f in payload.get("factors") or []):
            prior, belief = _renormalized(prior), _renormalized(belief)
        factors: list[FactorInput] = []
        for factor in payload.get("factors") or []:
            if isinstance(factor, dict) and isinstance(factor.get("delta"), dict):
                factors.append(
                    FactorInput(
                        str(factor["factor_id"]),
                        factor["delta"],
                        factor.get("scope_entity_ids", []),
                        [],
                        factor.get("note"),
                    )
                )
            else:
                dropped_factors += 1
        is_draft = payload.get("status") == "draft"
        request_type = DraftForecastRequest if is_draft else CommitForecastRequest
        action = forecasts.draft_forecast if is_draft else forecasts.commit_forecast
        actor_id = str(payload.get("judge")) if is_draft else "judge:owner"
        actor_role = ActorRole.AI_ANALYST if is_draft else ActorRole.JUDGE_OPERATOR
        try:
            outcome = action(
                request_type(
                    match_id=match_id,
                    market_definition_id=market,
                    decision_session_id=None,
                    prior_distribution=prior,
                    belief_distribution=belief,
                    factors=factors,
                    commitment_tier=str(payload.get("commitment_tier", "commit")),
                    evidence_bundle_id=None,
                    prior_snapshot_id=prior_snapshot_id,
                    falsifier=payload.get("falsifier"),
                    actor_id=actor_id,
                    actor_role=actor_role,
                    idempotency_key=f"{idempotency_prefix}:{read_id}",
                    requested_at=datetime.fromisoformat(payload["made_at"]),
                    # 判断唯一事实 P0：整条 Read 随 revision 入库，文件成为投影
                    kind=payload.get("kind"),
                    board_key=payload.get("board_key"),
                    judgment=payload,
                )
            )
        except (ValueError, KeyError) as error:
            rejected.append((read_id, str(error)))
            continue
        if outcome.status.is_success:
            committed.append(read_id)
        else:
            rejected.append((read_id, outcome.status.value))
    return ReadSubmission(total=len(payloads), committed=tuple(committed),
                          rejected=tuple(rejected), dropped_factors=dropped_factors)


def run_decision_read_v2(reads_file, output_dir, *, kernel=None,
                         idempotency_prefix: str = "read") -> str:
    """`decision-read --reads-file`（足彩手工 B4 路径仍用）：读文件 → `submit_reads` → 一行回执。"""
    payloads = json.loads(Path(reads_file).read_text(encoding="utf-8"))
    return submit_reads(payloads, kernel=kernel, idempotency_prefix=idempotency_prefix).summary()


def _render_report_markdown(kernel, run_date: str, stage: str) -> str:
    import json as _json

    from sqlalchemy import func, select

    from nutmeg.analytics.integrity_action import compute_integrity_action_rows
    from nutmeg.ontology.repository import schema_finance as sf

    status = kernel.status()
    cards = {
        r["scorecard"]: _json.loads(r["metrics_json"])
        for r in compute_integrity_action_rows(kernel.engine)
    }
    action = cards.get("action_finance", {})
    integrity = cards.get("evidence_integrity", {})
    day_prefix = f"{run_date}%"
    with kernel.engine.connect() as connection:
        day_ticket_count = connection.execute(
            select(func.count()).select_from(sf.tickets).where(
                sf.tickets.c.approved_at.like(day_prefix)
            )
        ).scalar_one()
        day_settlement_count = connection.execute(
            select(func.count()).select_from(sf.ticket_settlements).where(
                sf.ticket_settlements.c.settled_at.like(day_prefix)
            )
        ).scalar_one()
        day_transactions = dict(
            connection.execute(
                select(sf.cash_transactions.c.kind, func.sum(sf.cash_transactions.c.amount))
                .where(sf.cash_transactions.c.occurred_at.like(day_prefix))
                .group_by(sf.cash_transactions.c.kind)
            ).all()
        )
    day_stake = abs(float(day_transactions.get("stake", 0.0)))
    day_payout = float(day_transactions.get("payout", 0.0))
    return "\n".join(
        [
            f"# 决策日报 v2 — {run_date} [{stage}]",
            "",
            f"- 场次 {status.match_count} | 判读(forecast) {status.forecast_count}",
            f"- 当日票 {day_ticket_count} | 当日结算 {day_settlement_count}",
            f"- 当日注金 ¥{day_stake:.0f} | 当日回款 ¥{day_payout:.0f}"
            f" | 累计账户净额 ¥{action.get('ledger_balance', 0):.0f}",
            f"- 覆盖 outcome {integrity.get('outcome_completeness', 0):.0%}"
            f" / closing {integrity.get('closing_coverage', 0):.0%}",
            f"- 校准 scorecards {status.scorecard_count} | factor_estimates "
            f"{status.factor_estimate_count} | proposals {status.lifecycle_proposal_count}",
            "",
            "> 空仓永远合法;本报告只读 kernel,判断永不入脚本。",
        ]
    )


def _report_v2(
    kernel,
    run_date: str,
    output_dir,
    stage: str,
    dispatch: bool,
    dry_run: bool,
    notification_service=None,
) -> str:
    from nutmeg.notifications.models import NotificationRequest, semantic_fingerprint

    markdown = _render_report_markdown(kernel, run_date, stage)
    report_path = Path(output_dir) / "daily" / run_date / f"decision-report-v2-{run_date}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")

    note = ""
    if dispatch:
        if notification_service is None:
            from nutmeg.notifications.wiring import build_notification_service

            notification_service = build_notification_service()
        request = NotificationRequest(
            kind=f"decision.{stage}.report.v2",
            business_key=run_date,
            stage=stage,
            semantic_fingerprint=semantic_fingerprint({"stage": stage, "markdown": markdown}),
            subject=f"决策日报 v2 {run_date}",
            caption=f"决策日报 v2 {run_date}",
            body=markdown,
            metadata={"run_date": run_date, "stage": stage},
        )
        outcome = notification_service.publish(request, dry_run=dry_run)
        note = f" | 推送 {outcome.status.value}"
    return f"decision-report-v2 {run_date} [{stage}]: {report_path.name}{note}"


def _normalize_score(value: object) -> str | None:
    """ "2-1"/"2:1"/"2：1" → "2-1"; home/draw/away → canonical score; else None."""
    text = str(value or "").strip().replace("：", ":").replace(":", "-")
    parts = text.split("-")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return f"{int(parts[0])}-{int(parts[1])}"
    return _RESULT_SCORE.get(str(value))


# A match cannot be final before kickoff + regulation + half-time + stoppage. Any
# auto-fetched "result" arriving earlier is poison (e.g. okooo's 开奖 page falls back to
# the latest *completed* day when the requested date has no results yet, and its row
# numbers collide with today's 竞彩号 — observed live on 2026-07-22).
_MIN_MATCH_MINUTES = 110


def _kickoff_passed(scheduled_at: str | None, now: datetime) -> bool:
    """True only when the match could physically be finished by ``now``."""
    if not scheduled_at:
        return False  # no kickoff on record → never auto-settle (manual override only)
    try:
        kickoff = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return False
    if kickoff.tzinfo is None:
        return False
    return (now - kickoff).total_seconds() >= _MIN_MATCH_MINUTES * 60


def _board_identity(run_date: str, output_dir) -> tuple[dict[str, str], dict[str, str]]:
    """竞彩号 → 身份：(legs-base 的内核 match_id, 已存体彩快照的 sporttery matchId)。

    legs-base 是设计系列 ⑥ 的身份链（竞彩编号 ↔ 内核 match_id），完整保留当天全板；体彩快照
    会被后来的抓取覆盖、丢掉已完场的场次（2026-09-20 / 09-26 等整板在内核里没有赛果就是这么来的），
    只作 legs-base 缺失时的后备。两者同时存在时在生产数据上逐场一致（2026-10-08 核对）。"""
    from nutmeg.decision.market_data import load_sporttery_snapshot

    legs_path = Path(output_dir) / "daily" / run_date / "jczq-legs-base.json"
    try:
        legs = json.loads(legs_path.read_text(encoding="utf-8")).get("legs") or {}
    except (OSError, ValueError, AttributeError):
        legs = {}
    by_legs = {str(code): str(leg["match_id"]) for code, leg in legs.items()
               if isinstance(leg, dict) and leg.get("match_id")}
    sporttery = load_sporttery_snapshot(run_date, output_dir) or {}
    by_snapshot: dict[str, str] = {}
    for day in sporttery.get("matchInfoList") or []:
        for sub in day.get("subMatchList") or []:
            if sub.get("matchNumStr") and sub.get("matchId") is not None:
                by_snapshot[str(sub["matchNumStr"])] = str(sub["matchId"])
    return by_legs, by_snapshot


def _results_v2(
    kernel, run_date: str, output_dir, live_fetcher=None, now: datetime | None = None
) -> dict[str, tuple[str, str]]:
    """Final scores keyed by kernel match id: ``{match_id: ("2-1", source)}``.

    1. ``daily/<date>/results.json`` (manual override, score or home/draw/away values) wins
       outright and is trusted as an explicit human action (source ``manual``).
    2. Otherwise the single results source ``jczq/jc-results.json[run_date]`` via
       ``nutmeg.decision.match_results`` (source ``jc-results``; 2026-10-08 B1 — before that
       the kernel took okooo while every file consumer took jc-results).
    3. okooo live is a **fallback only for board codes jc-results lacks**: the 08:10 settle
       runs before the 09:30 backfill seals yesterday, and void matches never get sealed.
       When jc-results covers the whole board okooo is not called at all (source ``okooo``).

    竞彩号 → kernel match via ``_board_identity``. Both auto paths accept a score **only for
    a match whose kickoff + 110min has passed** — a source claiming a result for an unplayed
    match is poison, not truth. Unfinished/unmappable matches are skipped — a missing result
    is never a pending settlement.
    """
    from nutmeg.decision.match_results import board_outcomes
    from nutmeg.ontology.errors import OntologyError
    from nutmeg.ontology.identity.models import EntityType
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    results_path = Path(output_dir) / "daily" / run_date / "results.json"
    if results_path.exists():
        manual = json.loads(results_path.read_text(encoding="utf-8"))
        return {
            str(match_id): (score, "manual")
            for match_id, value in manual.items()
            if (score := _normalize_score(value)) is not None
        }

    by_legs, by_snapshot = _board_identity(run_date, output_dir)
    scores: dict[str, tuple[str, str]] = {
        code: (f"{row['goals_h']}-{row['goals_a']}", "jc-results")
        for code, row in board_outcomes(Path(output_dir).parent, run_date).items()
    }
    if (set(by_legs) | set(by_snapshot)) - set(scores):
        if live_fetcher is None:
            from nutmeg.services.jczq_results import OkoooJczqResultProvider

            live_fetcher = OkoooJczqResultProvider().fetch_results
        try:
            okooo = live_fetcher(run_date) or {}
        except Exception:  # noqa: BLE001 — 后备抓不到 → 只用 jc-results(不产 pending)
            okooo = {}
        for match_no, row in okooo.items():
            score = _normalize_score((row or {}).get("score"))
            if score is not None and str(match_no) not in scores:
                scores[str(match_no)] = (score, "okooo")

    current_time = now if now is not None else datetime.now(UTC)
    results: dict[str, tuple[str, str]] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for code, scored in scores.items():
            kernel_match = by_legs.get(code)
            if kernel_match is None and code in by_snapshot:
                kernel_match = uow.identity.entity_by_external_id(
                    EntityType.MATCH, provider="sporttery", external_id=by_snapshot[code]
                )
            if kernel_match is None:
                continue  # 未对上 → 跳过
            try:
                revision = uow.identity.current_match_revision(kernel_match)
            except OntologyError:
                continue  # legs-base 的 id 不在内核里 → 跳过
            if not _kickoff_passed(revision.scheduled_at, current_time):
                continue  # 开球+110min 未到 → 物理上不可能终局,拒收(毒数据防线)
            results[kernel_match] = scored
    return results


def _reconcile_v2(kernel, run_date: str, output_dir, requested_at, live_fetcher=None) -> str:
    """Record outcomes + settle each match's tickets. Results come from ``_results_v2``
    (manual override, else jc-results with okooo filling only what jc-results lacks); a match
    with no final result is skipped — never a pending settlement.

    A match whose kernel outcome already carries the same score is skipped (a match listed
    under two board days must not grow a second outcome version); an auto-sourced score that
    disagrees with the recorded one is reported, never written over."""
    from nutmeg.ontology.actions.models import ActorRole
    from nutmeg.ontology.finance.reconcile_flow import ReconcileRequest
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    results = _results_v2(kernel, run_date, output_dir, live_fetcher=live_fetcher)
    with OntologyUnitOfWork(kernel.engine) as uow:
        recorded = {mid: getattr(uow.finance.current_outcome(mid), "score_90", None)
                    for mid in results}
    sources: dict[str, int] = {}
    known = 0
    conflicts: list[str] = []
    settled = 0
    for match_id, (score, source) in results.items():
        if recorded[match_id] == score:
            known += 1
            continue
        if recorded[match_id] is not None and source != "manual":
            conflicts.append(f"{match_id} 内核 {recorded[match_id]} vs {source} {score}")
            continue
        sources[source] = sources.get(source, 0) + 1
        outcome = kernel.reconcile.settle_match(
            ReconcileRequest(
                match_id=str(match_id),
                account_id=_ACCOUNT,
                score_90=score,
                status="final",
                source_artifact_retrieval_ids=[],
                actor_id="system:reconcile",
                actor_role=ActorRole.DETERMINISTIC_SYSTEM,
                idempotency_key=f"reconcile:{run_date}:{match_id}",
                requested_at=requested_at,
            )
        )
        settled += len(outcome.settled_ticket_ids)
    written = sum(sources.values())
    msg = f"decision-reconcile-v2 {run_date}: 结算 {written} 场结果 / {settled} 票"
    if sources:
        msg += " | 来源 " + " · ".join(f"{k} {v}" for k, v in sorted(sources.items()))
    if known:
        msg += f" | 内核已有同比分 {known} 场"
    if conflicts:
        msg += f" | ⚠️比分与内核已记不一致 {len(conflicts)} 场(未覆盖): " + "; ".join(conflicts)
    return msg


def _calibrate_v2(kernel, stamp: str) -> str:
    from nutmeg.analytics.calibrate_flow import CalibrateRequest

    result = kernel.calibrate.build(CalibrateRequest(as_of=stamp, built_at=stamp))
    return (
        f"decision-calibrate-v2: {result.status} | scorecards={result.scorecard_count} "
        f"factor_estimates={result.factor_estimate_count} "
        f"proposals={result.lifecycle_proposal_count}"
    )


def run_decision_settle_v2(
    run_date: str,
    output_dir,
    *,
    kernel=None,
    dispatch: bool = False,
    dry_run: bool = True,
    notification_service=None,
    results_fetcher=None,
):
    """settle on the kernel: reconcile (record outcomes + settle tickets) → calibrate → report."""
    from nutmeg.decision.workflow_result import compose as _compose
    from nutmeg.decision.workflow_result import now_iso as _now_iso

    stamp = _now_iso()
    requested_at = datetime.fromisoformat(stamp)
    active_kernel = kernel if kernel is not None else _default_kernel()
    steps = [
        (
            "reconcile",
            lambda: _reconcile_v2(
                active_kernel, run_date, output_dir, requested_at, live_fetcher=results_fetcher
            ),
        ),
        ("calibrate", lambda: _calibrate_v2(active_kernel, stamp)),
        (
            "report",
            lambda: _report_v2(
                active_kernel,
                run_date,
                output_dir,
                "settle",
                dispatch,
                dry_run,
                notification_service,
            ),
        ),
    ]
    return _compose("decision-settle", run_date, "复盘(结算+校准,ontology v2 kernel)", steps)


# ── 足彩快照加载（2026-10-03 自 sense_zucai 迁入；v1 sense 路径已删）──

def _is_intl_odds(path) -> bool:
    """`-odds-intl.json` 是 titan007 国际盘（2026-09-22 起由 decision-fetch-zucai-intl 落盘），
    结构是 fair 不是 500.com 三赔率；它常与 `-odds.json` 同一分钟落盘甚至更新，
    按 mtime 取「最新槽」会把它当成体彩赔率 → 14 场全 no_odds、内核 0 快照、store-ids 全空
    （2026-09-24 26132 实发；26127 起每期身份未对上疑同因）。"""
    return "-odds-intl" in path.name


def _default_loader(issue: str, output_dir):
    """从已存 zucai 快照读 (matches, odds, dates)。replay 优先,不打网。

    真源落盘结构(已核对 .nutmeg-data/zucai/):
    - `{issue}-issue.json`  = ZucaiSourceSyncService.sync 产;顶层含 draw_date,
      `matches: [{match_no, competition, home_team, away_team, match_date, ...}]`。
      → 构造 ZucaiMatch 列表 + dates(每场自身 match_date,不用 draw_date 兜底,
      否则跨多天的期又退回单日 bug)。
    - `{issue}-odds*.json`  = ZucaiOddsSyncService.sync 产(下午盘 `-odds.json` /
      早盘 `-odds-revision.json` / 历史 `-odds-jczq-*.json` 等)。
      赔率槽策略(已定):取**最新**槽(按 mtime,最接近读时的盘),
      `matches: [{match_no, home, draw, away, ...}]` → {match_no:{home,draw,away}}。
    缺 issue 或 odds 文件 → FileNotFoundError(清晰指明路径)。
    """
    import json
    from pathlib import Path

    from nutmeg.domain.zucai import ZucaiMatch

    base = Path(output_dir)
    issue_path = base / f"{issue}-issue.json"
    if not issue_path.exists():
        raise FileNotFoundError(f"zucai issue 快照缺失: {issue_path}")
    issue_data = json.loads(issue_path.read_text(encoding="utf-8"))

    matches: list = []
    dates: dict = {}
    for row in issue_data.get("matches") or []:
        no = row.get("match_no")
        matches.append(ZucaiMatch(
            match_no=no,
            competition=str(row.get("competition") or ""),
            home_team=str(row.get("home_team") or ""),
            away_team=str(row.get("away_team") or ""),
            match_date=row.get("match_date"),
        ))
        date = row.get("match_date")
        if no is not None and date:
            dates[no] = str(date)

    odds_files = [p for p in base.glob(f"{issue}-odds*.json") if not _is_intl_odds(p)]
    if not odds_files:
        raise FileNotFoundError(f"zucai odds 快照缺失: {base}/{issue}-odds*.json")
    latest = max(odds_files, key=lambda p: p.stat().st_mtime)
    odds_data = json.loads(latest.read_text(encoding="utf-8"))

    odds: dict = {}
    for row in odds_data.get("matches") or []:
        no = row.get("match_no")
        if no is None:
            continue
        try:
            odds[no] = {"home": float(row["home"]), "draw": float(row["draw"]),
                        "away": float(row["away"])}
        except (KeyError, TypeError, ValueError):
            continue
    return matches, odds, dates
