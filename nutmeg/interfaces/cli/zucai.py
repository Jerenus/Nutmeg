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
_CAND_LEGS_FILE_OPTION = _cli.typer.Option(
    None, "--legs-file",
    help="legs-base（带旗/完整度/先例）；给了才给候选贴审计码")
_CAND_AUDIT_TOP_OPTION = _cli.typer.Option(
    8, "--audit-top", help="对前 N 个候选跑真审计（含票级码）；0=只做便宜查表")
_CAND_STRUCTURE_OPTION = _cli.typer.Option(
    None, "--structure", help="只留这个形状，形如 3/3/3＝3单3双3包")
_INTAKE_LEGS_FILE_OPTION = _cli.typer.Option(
    ..., "--legs-file", help="要回填的 legs-base.json")
_INTAKE_RESEARCH_DIR_OPTION = _cli.typer.Option(
    _cli.Path(".nutmeg-data/zucai"), "--research-dir",
    help="存放 <期>-research-m<N>.json 的目录")
_INTAKE_MATCH_OPTION = _cli.typer.Option(
    None, "--match", help="只入库这些场号；不给＝全部有研究文件的场")
_INTAKE_WRITE_OPTION = _cli.typer.Option(
    False, "--write", help="真写入 legs-base；不给＝只预演报告")
_PREMISE_OUTPUT_DIR_OPTION = _cli.typer.Option(
    _cli.Path(".nutmeg-data/jczq"), "--output-dir", help="store 根目录")
_PREMISE_OUT_OPTION = _cli.typer.Option(
    None, "--out", help="前提卡落盘路径；不给＝打到 stdout")
_PREMISE_APPLY_OPTION = _cli.typer.Option(
    False, "--apply", help="真回写 store 画像；不给＝只预演")


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


@_cli.app.command("zucai-premise-card")
def zucai_premise_card(
    issue: str = _BUILD_ISSUE_OPTION,
    zucai_dir: _cli.Path = _INTAKE_RESEARCH_DIR_OPTION,
    output_dir: _cli.Path = _PREMISE_OUTPUT_DIR_OPTION,
    out: _cli.Path | None = _PREMISE_OUT_OPTION,
) -> None:
    """派研究前的前提卡：只写 store 里有的，其余明写「本卡未提供」。

    **出生事故 26128**：我给 14 个 agent 的提示里塞了自己记忆里的前提，
    一期错六条（曼城主帅写成瓜迪奥拉、伯恩茅斯写成 Iraola、贝西克塔斯写成
    van Bronckhorst，另加桑德兰「刚升班」、考文垂「在英冠」、格拉茨「卫冕冠军」）。
    写错的前提比不给前提更贵——它给了 agent 一个带锚的起点，而反偏置约束
    要求它们独立取证。

    ⛔卡上没有的，我不许替 agent 补全。
    """
    import json as _json

    from nutmeg.decision.entities import profiles_for_board
    from nutmeg.decision.premise_card import build_card, format_cards
    from nutmeg.decision.store import DecisionStore

    issue_doc = _json.loads(
        (_cli.Path(zucai_dir) / f"{issue}-issue.json").read_text("utf-8")
    )
    fair_doc = {}
    fair_path = _cli.Path(zucai_dir) / f"{issue}-fair.json"
    if fair_path.exists():
        fair_doc = _json.loads(fair_path.read_text("utf-8"))
    matches = issue_doc.get("matches") or []
    names = [
        str(m.get(key) or "")
        for m in matches
        for key in ("home", "away", "home_team", "away_team")
        if m.get(key)
    ]
    competitions = [str(m.get("competition") or "") for m in matches]
    store = DecisionStore(_cli.Path(output_dir) / "decision")
    board = profiles_for_board(store, competitions, names)
    # ⚠️键是 board_name（板面上的队名），不是 name/id —— 取错键会让整张卡
    # 静默变成「store 全空」，而 store 其实有 213 支队的画像（2026-09-17 实测）。
    profiles = {
        str(item.get("board_name") or ""): item.get("profile_notes") or []
        for item in (board.get("teams") or [])
    }
    unresolved = board.get("unresolved_leagues") or []
    # profiles_for_board 只报未解析的**联赛**；未解析的球队同样要喊出来，
    # 否则「这队没画像」与「这名字没对上」长得一模一样。
    resolved_names = {str(i.get("board_name") or "") for i in (board.get("teams") or [])}
    missing_teams = [n for n in dict.fromkeys(names) if n not in resolved_names]
    cards = []
    for index, match in enumerate(matches, start=1):
        no = int(match.get("match_no") or index)
        entry = fair_doc.get(str(no)) or {}
        cards.append(build_card(
            match, match_no=no,
            fair=entry.get("fair") or entry or {}, profiles=profiles,
        ))
    text = format_cards(
        cards, issue=issue,
        leagues=board.get("leagues") or [], unresolved_leagues=unresolved,
        unresolved_teams=missing_teams,
    )
    if out:
        _cli.Path(out).write_text(text + "\n", "utf-8")
        _cli.typer.echo(f"前提卡 {len(cards)} 场 → {out}")
    else:
        _cli.typer.echo(text)


@_cli.app.command("zucai-premise-corrections")
def zucai_premise_corrections(
    issue: str = _BUILD_ISSUE_OPTION,
    research_dir: _cli.Path = _INTAKE_RESEARCH_DIR_OPTION,
    output_dir: _cli.Path = _PREMISE_OUTPUT_DIR_OPTION,
    apply_corrections: bool = _PREMISE_APPLY_OPTION,
) -> None:
    """把 agent 对前提卡的纠正收上来，回写 store 画像。**纠正不回写＝白纠正。**

    读各场研究 JSON 的 `premise_corrections`（每条需 subject/correct/evidence）。
    ⛔缺 evidence 的纠正不收——纠正也是证据，无出处的纠正只是换一个人的记忆。
    """
    import json as _json

    from nutmeg.decision.entities import add_profile_note
    from nutmeg.decision.premise_card import collect_corrections
    from nutmeg.decision.store import DecisionStore

    found = []
    for path in sorted(_cli.Path(research_dir).glob(f"{issue}-research-m*.json")):
        found.extend(collect_corrections(_json.loads(path.read_text("utf-8"))))
    if not found:
        _cli.typer.echo(
            f"{issue}: 研究文件里没有 premise_corrections。\n"
            "（agent 提示里要写明：纠正我的前提时请同时填这个字段，含 evidence）"
        )
        return
    _cli.typer.echo(f"前提纠正 {len(found)} 条：")
    for correction in found:
        _cli.typer.echo(correction.render())
    if not apply_corrections:
        _cli.typer.echo("\n（预演。加 --apply 才回写 store 画像）")
        return
    store = DecisionStore(_cli.Path(output_dir) / "decision")
    ok = 0
    for correction in found:
        try:
            _cli.typer.echo("  " + add_profile_note(
                store,
                team_id=correction.subject if correction.subject_type == "team" else None,
                league_id=correction.subject if correction.subject_type == "league" else None,
                key=correction.field,
                note=correction.correct,
                evidence=correction.evidence,
                at=correction.as_of,
            ))
            ok += 1
        except ValueError as exc:
            _cli.typer.echo(f"  ⚠️ {correction.subject}: {exc}")
    _cli.typer.echo(f"\n回写 {ok}/{len(found)} 条")


@_cli.app.command("zucai-research-intake")
def zucai_research_intake(
    issue: str = _BUILD_ISSUE_OPTION,
    legs_file: _cli.Path = _INTAKE_LEGS_FILE_OPTION,
    research_dir: _cli.Path = _INTAKE_RESEARCH_DIR_OPTION,
    match_no: list[int] = _INTAKE_MATCH_OPTION,
    write: bool = _INTAKE_WRITE_OPTION,
) -> None:
    """深研 JSON → legs-base 的入库桥：归一键名、清洗封闭词典、查自相矛盾。

    读 `<research-dir>/<issue>-research-m<N>.json`，把结构字段搬进 legs-base。
    **只转录与校验，不产生判断**——不改任何一场的 faces、不推断动作。

    三类检查：①**封闭词典**——词典外的旗/标签剥离进 note 并留痕（不阻断出票：
    agent 自命名的旗若能堵死单选，那不是纪律是瘫痪）；②**结构自相矛盾**——
    四问④判「无情境旗」却挂着旗、宣告死面而三证不齐，判 ERROR 拒绝写入；
    ③**定义漂移与编码/正文相反**——三证(c) 逐面不同或与完整度不符、
    ④②③b 的编码与 summary 极性相反，判 WARN 交人工复核。

    出生事故 26125-26128：14 场研究每期用 /tmp 脚本搬运，零校验。agent 把叙述写进
    `crash_markers`、三证键名两套并存、26128 场2 的 (c) 在三个面上取了两个值、
    场7 `q3b=false` 而同一份 summary 写「③b 的答案是『在』」——全靠我肉眼抓。
    """
    import json as _json

    from nutmeg.decision.research_intake import format_report, intake

    doc = _json.loads(_cli.Path(legs_file).read_text("utf-8"))
    legs = doc.get("legs") or {}
    wanted = set(match_no) if match_no else None
    results = []
    for key in sorted(legs, key=int):
        if wanted is not None and int(key) not in wanted:
            continue
        path = _cli.Path(research_dir) / f"{issue}-research-m{key}.json"
        if not path.exists():
            continue
        research = _json.loads(path.read_text("utf-8"))
        results.append(intake(research, legs[key]))
    if not results:
        _cli.typer.echo("没有找到可入库的研究文件。")
        raise _cli.typer.Exit(code=2)
    _cli.typer.echo(format_report(results))
    blocked = [r for r in results if r.blocked]
    if write:
        for result in results:
            if result.blocked:
                continue
            legs[str(result.match_no)] = result.leg
        doc["legs"] = legs
        _cli.Path(legs_file).write_text(
            _json.dumps(doc, ensure_ascii=False, indent=1) + "\n", "utf-8"
        )
        written = len(results) - len(blocked)
        _cli.typer.echo(f"\n已写入 {written}/{len(results)} 场 → {legs_file}")
    else:
        _cli.typer.echo("\n（预演。加 --write 才写入 legs-base）")
    if blocked:
        raise _cli.typer.Exit(code=1)


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
    legs_file: _cli.Path | None = _CAND_LEGS_FILE_OPTION,
    audit_top: int = _CAND_AUDIT_TOP_OPTION,
    structure: str | None = _CAND_STRUCTURE_OPTION,
) -> None:
    """穷举**已声明**的票面空间；排序=帽内 P 降序，这是比较顺序不是推荐。

    给了 `--legs-file` 就两段式贴审计码：先用 `face_options` 逐腿查表给全部候选贴
    腿级码（便宜），再对前 `--audit-top` 个跑**真审计**补票级码（C15/C15b/C17/全包分配）。
    ⛔ERROR 不剔除候选，也不改排序——行权空间归 `decision-adjudicate`。
    `--structure 3/3/3` 只保留「3单3双3包」形状：26127 用户的 S333 落在我所有
    声明空间的缝里（没有一个空间允许「锚场降双×硬币降双」的交叉），形状过滤堵这个缝。
    """
    import json as _json

    from nutmeg.decision.betslip import BetslipError
    from nutmeg.decision.candidate_builder import (
        audit_candidates,
        enumerate_candidates,
        format_candidates,
        format_swaps,
        leg_face_codes,
        swap_report,
        ticket_probability,
    )
    from nutmeg.decision.legs_audit import legs_from_dict

    options = _json.loads(_cli.Path(options_file).read_text("utf-8"))
    fair = _json.loads(_cli.Path(fair_file).read_text("utf-8"))
    shape = None
    if structure:
        parts = [p for p in structure.replace("/", " ").split() if p]
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            _cli.typer.echo("--structure 形如 3/3/3（裸单数/双选数/全包数）")
            raise _cli.typer.Exit(code=2)
        shape = (int(parts[0]), int(parts[1]), int(parts[2]))
    base_payload = None
    leg_codes = None
    if legs_file:
        base_payload = _json.loads(_cli.Path(legs_file).read_text("utf-8"))
        leg_codes = leg_face_codes(legs_from_dict(base_payload))
    try:
        if base_file:
            base = _json.loads(_cli.Path(base_file).read_text("utf-8"))
            base = base.get("faces", base)
            rows = swap_report(base, options, fair, channel=channel)
            _cli.typer.echo(format_swaps(rows, ticket_probability(base, fair),
                                         limit=limit))
            return
        cands = enumerate_candidates(
            options, fair, channel=channel, cap_yuan=cap_yuan,
            leg_codes=leg_codes, structure=shape,
        )
    except BetslipError as exc:
        _cli.typer.echo(f"候选穷举错误：{exc}")
        raise _cli.typer.Exit(code=1) from exc
    if base_payload is not None and audit_top > 0:
        cands = audit_candidates(cands, base_payload, top=audit_top)
    _cli.typer.echo(format_candidates(cands, cap_yuan=cap_yuan, limit=limit))
