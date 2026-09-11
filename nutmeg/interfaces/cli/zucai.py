"""Zucai (足彩) CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli

_JUDGMENT_FILE_OPTION = _cli.typer.Option(..., "--judgment-file",
                                          help="judgment-v1（主循环判读产物）")
_BUILD_ISSUE_OPTION = _cli.typer.Option(..., "--issue")
_STORE_IDS_FILE_OPTION = _cli.typer.Option(..., "--store-ids-file")
_BUILD_FAIR_FILE_OPTION = _cli.typer.Option(..., "--fair-file")
_MADE_AT_OPTION = _cli.typer.Option(..., "--made-at", help="ISO 判读时刻")
_BUILD_OUTPUT_DIR_OPTION = _cli.typer.Option(_cli.Path(".nutmeg-data/zucai"),
                                             "--output-dir")
_JUDGE_OPTION = _cli.typer.Option("claude", "--judge")
_CAND_OPTIONS_FILE_OPTION = _cli.typer.Option(
    ..., "--options-file", help='{"场次":["31","310",""]}；"" = 丢整场')
_CAND_CHANNEL_OPTION = _cli.typer.Option("renjiu", "--channel")
_CAND_CAP_OPTION = _cli.typer.Option(None, "--cap-yuan")
_CAND_BASE_FILE_OPTION = _cli.typer.Option(
    None, "--base-file", help="给定基准票面则改出单点/两点替换报告")
_CAND_LIMIT_OPTION = _cli.typer.Option(20, "--limit")


@_cli.app.command("zucai-report")
def zucai_report(
    issue_id: str | None = _cli.ZUCAI_ISSUE_ID_OPTION,
    issue_file: _cli.Path | None = _cli.ZUCAI_ISSUE_FILE_OPTION,
    odds_file: _cli.Path | None = _cli.ZUCAI_ODDS_FILE_OPTION,
    overrides_file: _cli.Path | None = _cli.ZUCAI_OVERRIDES_FILE_OPTION,
    output_dir: _cli.Path = _cli.ZUCAI_OUTPUT_DIR_OPTION,
    pdf: bool = _cli.typer.Option(False, "--pdf"),
    record_final: bool = _cli.typer.Option(True, "--record-final/--no-record-final"),
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_zucai_workflow_service()
    try:
        report = service.build_report(
            issue_id=issue_id,
            issue_file=issue_file,
            odds_file=odds_file,
            overrides_file=overrides_file,
            output_dir=output_dir,
            render_pdf=pdf or dispatch_telegram,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
            record_final=record_final,
        )
    except _cli.ZucaiValidationError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = report.to_dict()
    delivery_failed = _required_delivery_failed(
        report.dispatch.status,
        dispatch_telegram=dispatch_telegram,
        dry_run=dry_run,
    )
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        if delivery_failed:
            raise _cli.typer.Exit(code=1)
        return

    _cli.console.print(
        f"zucai issue={report.issue.issue_id} matches={len(report.recommendations)} "
        f"plans={len(report.plans)} warnings={len(report.warnings)}"
    )
    _cli.console.print(f"markdown={report.artifacts.markdown_path}")
    if report.artifacts.pdf_path:
        _cli.console.print(f"pdf={report.artifacts.pdf_path}")
    _cli.console.print(f"dispatch={report.dispatch.status}")
    for recommendation in report.recommendations:
        _cli.console.print(
            f"{recommendation.match_no}. pick={recommendation.pick} "
            f"risk={recommendation.risk_tier} confidence={recommendation.confidence:.2f}"
        )
    if delivery_failed:
        raise _cli.typer.Exit(code=1)


@_cli.app.command("zucai-renjiu-daily")
def zucai_renjiu_daily(
    run_date: str = _cli.typer.Option("today", "--date"),
    issue_id: str | None = _cli.ZUCAI_ISSUE_ID_OPTION,
    issue_file: _cli.Path | None = _cli.ZUCAI_ISSUE_FILE_OPTION,
    odds_file: _cli.Path | None = _cli.ZUCAI_ODDS_FILE_OPTION,
    output_dir: _cli.Path = _cli.ZUCAI_OUTPUT_DIR_OPTION,
    pdf: bool = _cli.typer.Option(False, "--pdf"),
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_zucai_renjiu_daily_service()
    value_bridge = _cli._build_zucai_value_bridge_for_daily(run_date)
    try:
        report = service.build_report(
            run_date=run_date,
            issue_id=issue_id,
            issue_file=issue_file,
            odds_file=odds_file,
            output_dir=output_dir,
            render_pdf=pdf or dispatch_telegram,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
            value_bridge=value_bridge,
        )
    except _cli.ZucaiRenjiuValidationError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = report.to_dict()
    delivery_failed = _required_delivery_failed(
        report.dispatch.status,
        dispatch_telegram=dispatch_telegram,
        dry_run=dry_run,
    )
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        if delivery_failed:
            raise _cli.typer.Exit(code=1)
        return

    recommended = next(
        ticket for ticket in report.tickets if ticket.ticket_id == report.recommended_ticket_id
    )
    _cli.console.print(
        f"zucai-renjiu-daily issue={report.issue_id} recommended={recommended.name} "
        f"cost={recommended.cost_yuan} dispatch={report.dispatch.status}"
    )
    _cli.console.print(f"markdown={report.artifacts.markdown_path}")
    if report.artifacts.pdf_path:
        _cli.console.print(f"pdf={report.artifacts.pdf_path}")
    for ticket in report.tickets:
        _cli.console.print(
            f" - {ticket.name}: {ticket.code} ({ticket.stake_count}注/{ticket.cost_yuan}元)"
        )
    if delivery_failed:
        raise _cli.typer.Exit(code=1)


@_cli.app.command("zucai-auto-run")
def zucai_auto_run(
    run_date: str = _cli.typer.Option("today", "--date"),
    slot: str = _cli.typer.Option(..., "--slot"),
    registry_file: _cli.Path = _cli.ZUCAI_REGISTRY_FILE_OPTION,
    output_dir: _cli.Path = _cli.ZUCAI_SCHEDULE_OUTPUT_DIR_OPTION,
    run_record_file: _cli.Path = _cli.ZUCAI_RUN_RECORD_FILE_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    force: bool = _cli.typer.Option(False, "--force"),
    quiet: bool = _cli.typer.Option(False, "--quiet"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_zucai_scheduled_delivery_service()
    try:
        result = service.run(
            run_date=run_date,
            slot=slot,
            registry_file=registry_file,
            output_dir=output_dir,
            run_record_file=run_record_file,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
            force=force,
        )
    except _cli.ZucaiScheduleValidationError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = result.to_dict()
    delivery_failed = _required_delivery_failed(
        result.dispatch.status,
        dispatch_telegram=dispatch_telegram,
        dry_run=dry_run,
    )
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        if delivery_failed:
            raise _cli.typer.Exit(code=1)
        return
    if quiet and result.status == "skipped_no_issue":
        return
    _cli.console.print(
        f"zucai-auto-run date={result.run_date} slot={result.slot} "
        f"status={result.status} issue={result.issue_id or '-'}"
    )
    if result.skipped_reason:
        _cli.console.print(f"reason={result.skipped_reason}")
    if result.artifacts.pdf_path:
        _cli.console.print(f"pdf={result.artifacts.pdf_path}")
    _cli.console.print(f"dispatch={result.dispatch.status}")
    for warning in result.warnings:
        _cli.console.print(f"warning: {warning}")
    if delivery_failed:
        raise _cli.typer.Exit(code=1)


def _required_delivery_failed(
    status: str,
    *,
    dispatch_telegram: bool,
    dry_run: bool,
) -> bool:
    return (
        dispatch_telegram
        and not dry_run
        and status not in {"sent", "deduplicated"}
    )


@_cli.app.command("zucai-source-sync")
def zucai_source_sync(
    source_file: _cli.Path | None = _cli.ZUCAI_SOURCE_FILE_OPTION,
    source_url: str | None = _cli.ZUCAI_SOURCE_URL_OPTION,
    live_fetch: bool = _cli.typer.Option(False, "--live-fetch"),
    run_date: str = _cli.typer.Option("today", "--date"),
    source_label: str = _cli.ZUCAI_SOURCE_LABEL_OPTION,
    output_dir: _cli.Path = _cli.ZUCAI_OUTPUT_DIR_OPTION,
    registry_file: _cli.Path = _cli.ZUCAI_REGISTRY_FILE_OPTION,
    timeout_seconds: float = _cli.typer.Option(5.0, "--timeout-seconds"),
    max_bytes: int = _cli.typer.Option(524_288, "--max-bytes"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_zucai_source_sync_service()
    try:
        result = service.sync(
            source_file=source_file,
            source_url=source_url,
            live_fetch=live_fetch,
            run_date=run_date,
            output_dir=output_dir,
            registry_file=registry_file,
            source_label=source_label,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    except _cli.ZucaiSourceValidationError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = result.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"zucai-source-sync parsed={result.parsed_count} "
        f"active={','.join(result.active_issue_ids) or '-'}"
    )
    _cli.console.print(f"registry={result.registry_path}")
    for issue_id, path in result.written_issue_paths.items():
        _cli.console.print(f" - {issue_id}: {path}")
    for warning in result.warnings:
        _cli.console.print(f"warning: {warning}")


@_cli.app.command("zucai-odds-sync")
def zucai_odds_sync(
    source_file: _cli.Path | None = _cli.ZUCAI_SOURCE_FILE_OPTION,
    source_url: str | None = _cli.ZUCAI_SOURCE_URL_OPTION,
    live_fetch: bool = _cli.typer.Option(False, "--live-fetch"),
    issue_id: str | None = _cli.ZUCAI_ISSUE_ID_OPTION,
    slot: str = _cli.typer.Option(..., "--slot"),
    captured_at: str | None = _cli.typer.Option(None, "--captured-at"),
    source_label: str = _cli.ZUCAI_ODDS_SOURCE_LABEL_OPTION,
    output_dir: _cli.Path = _cli.ZUCAI_OUTPUT_DIR_OPTION,
    registry_file: _cli.Path = _cli.ZUCAI_REGISTRY_FILE_OPTION,
    timeout_seconds: float = _cli.typer.Option(5.0, "--timeout-seconds"),
    max_bytes: int = _cli.typer.Option(524_288, "--max-bytes"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_zucai_odds_sync_service()
    try:
        result = service.sync(
            source_file=source_file,
            source_url=source_url,
            live_fetch=live_fetch,
            issue_id=issue_id,
            slot=slot,
            captured_at=captured_at,
            output_dir=output_dir,
            registry_file=registry_file,
            source_label=source_label,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    except _cli.ZucaiOddsSourceValidationError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = result.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(
        f"zucai-odds-sync issue={result.issue_id} slot={result.slot} rows={result.parsed_count}"
    )
    _cli.console.print(f"odds={result.odds_path}")
    _cli.console.print(f"registry={result.registry_path}")
    for warning in result.warnings:
        _cli.console.print(f"warning: {warning}")


@_cli.app.command("zucai-grade")
def zucai_grade(
    report_file: _cli.Path = _cli.ZUCAI_REPORT_FILE_OPTION,
    outcomes_file: _cli.Path = _cli.ZUCAI_OUTCOMES_FILE_OPTION,
    record_db: bool = _cli.typer.Option(True, "--record-db/--no-record-db"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_zucai_workflow_service()
    try:
        grade = service.grade_report(
            report_file=report_file,
            outcomes_file=outcomes_file,
            record_db=record_db,
        )
    except _cli.ZucaiValidationError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = grade.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"zucai-grade issue={grade.issue_id} "
        f"matches={len(grade.match_results)} plans={len(grade.plan_results)}"
    )
    for plan in grade.plan_results:
        _cli.console.print(
            f" - {plan.name}: hit={plan.hit_count}/{plan.selected_count} "
            f"covered={'yes' if plan.covered else 'no'}"
        )
    for warning in grade.warnings:
        _cli.console.print(f" warning: {warning}")


@_cli.app.command("zucai-build-reads")
def zucai_build_reads(
    judgment_file: _cli.Path = _JUDGMENT_FILE_OPTION,
    issue: str = _BUILD_ISSUE_OPTION,
    store_ids_file: _cli.Path = _STORE_IDS_FILE_OPTION,
    fair_file: _cli.Path = _BUILD_FAIR_FILE_OPTION,
    made_at: str = _MADE_AT_OPTION,
    output_dir: _cli.Path = _BUILD_OUTPUT_DIR_OPTION,
    judge: str = _JUDGE_OPTION,
) -> None:
    """judgment-v1 → reads.json + legs-base.json（只转录与校验词典，不产生判断）。"""
    import json as _json

    from nutmeg.decision.read_builder import JudgmentError, build, format_warnings

    try:
        result = build(
            _json.loads(_cli.Path(judgment_file).read_text("utf-8")),
            issue=issue,
            store_ids=_json.loads(_cli.Path(store_ids_file).read_text("utf-8")),
            fair=_json.loads(_cli.Path(fair_file).read_text("utf-8")),
            made_at=made_at, judge=judge)
    except JudgmentError as exc:
        _cli.typer.echo(f"judgment 结构错误：{exc}")
        raise _cli.typer.Exit(code=1) from exc
    out = _cli.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    reads_path = out / f"{issue}-reads.json"
    legs_path = out / f"{issue}-legs-base.json"
    reads_path.write_text(_json.dumps(result.reads, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    legs_path.write_text(_json.dumps(result.legs, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    _cli.typer.echo(format_warnings(result))
    _cli.typer.echo(f"  reads → {reads_path}\n  legs  → {legs_path}")


@_cli.app.command("zucai-candidates")
def zucai_candidates(
    options_file: _cli.Path = _CAND_OPTIONS_FILE_OPTION,
    fair_file: _cli.Path = _BUILD_FAIR_FILE_OPTION,
    channel: str = _CAND_CHANNEL_OPTION,
    cap_yuan: int | None = _CAND_CAP_OPTION,
    base_file: _cli.Path | None = _CAND_BASE_FILE_OPTION,
    limit: int = _CAND_LIMIT_OPTION,
) -> None:
    """穷举**已声明**的票面空间；排序=帽内 P 降序，这是比较顺序不是推荐。"""
    import json as _json

    from nutmeg.decision.betslip import BetslipError
    from nutmeg.decision.candidate_builder import (
        enumerate_candidates,
        format_candidates,
        format_swaps,
        swap_report,
        ticket_probability,
    )

    options = _json.loads(_cli.Path(options_file).read_text("utf-8"))
    fair = _json.loads(_cli.Path(fair_file).read_text("utf-8"))
    try:
        if base_file:
            base = _json.loads(_cli.Path(base_file).read_text("utf-8"))
            base = base.get("faces", base)
            rows = swap_report(base, options, fair, channel=channel)
            _cli.typer.echo(format_swaps(rows, ticket_probability(base, fair),
                                         limit=limit))
            return
        cands = enumerate_candidates(options, fair, channel=channel, cap_yuan=cap_yuan)
    except BetslipError as exc:
        _cli.typer.echo(f"候选穷举错误：{exc}")
        raise _cli.typer.Exit(code=1) from exc
    _cli.typer.echo(format_candidates(cands, cap_yuan=cap_yuan, limit=limit))
