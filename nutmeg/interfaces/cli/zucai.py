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
    else:
        # `-fair.json` 是手工 B4 的产物，26135 起不再生成；备料自动跑 decision-am --issue
        # 落的 `-store-ids.json` 同样带去水 fair——否则整张卡静默印 0.0（2026-10-08 26136）。
        store_ids_path = _cli.Path(zucai_dir) / f"{issue}-store-ids.json"
        if store_ids_path.exists():
            fair_doc = _json.loads(store_ids_path.read_text("utf-8"))
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
        if ".rejected" in path.name:      # 拒收件：无 premise_corrections，场号也解析不出
            continue
        research = _json.loads(path.read_text("utf-8"))
        # 无头深研不写 match_no，场号在文件名里（否则每条纠正都报成「场0」）
        research.setdefault("match_no", int(path.stem.rsplit("-m", 1)[-1]))
        found.extend(collect_corrections(research))
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
        results.append(intake(research, legs[key], match_no=int(key)))
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
    revision: int = _cli.typer.Option(0, "--revision", help="判断修订号：Read ID 加 -rN（0=首版）"),
    only: str = _cli.typer.Option("", "--only", help="只发这些场次的 Read，如 11 或 3,11"),
) -> None:
    """judgment-v1 → reads.json + legs-base.json（只转录与校验词典，不产生判断）。"""
    import json as _json

    from nutmeg.decision.face_status import FaceStatusError, attach_face_status
    from nutmeg.decision.read_builder import JudgmentError, build, format_warnings

    judgment = _json.loads(_cli.Path(judgment_file).read_text("utf-8"))
    try:
        result = build(
            judgment,
            issue=issue,
            store_ids=_json.loads(_cli.Path(store_ids_file).read_text("utf-8")),
            fair=_json.loads(_cli.Path(fair_file).read_text("utf-8")),
            made_at=made_at, judge=judge, revision=revision or None,
            only={x.strip() for x in only.split(",") if x.strip()} or None)
    except JudgmentError as exc:
        _cli.typer.echo(f"judgment 结构错误：{exc}")
        raise _cli.typer.Exit(code=1) from exc
    out = _cli.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    reads_path = out / f"{issue}-reads.json"
    legs_path = out / f"{issue}-legs-base.json"
    research_dir = _cli.Path(store_ids_file).parent
    for no, leg in result.legs["legs"].items():
        research_path = research_dir / f"{issue}-research-m{no}.json"
        research = (_json.loads(research_path.read_text("utf-8"))
                    if research_path.exists() else {})
        if "never_faces" in judgment[no]:
            leg["never_faces"] = judgment[no]["never_faces"]
        try:
            attach_face_status(leg, research, source=research_path.name)
        except FaceStatusError as exc:
            _cli.typer.echo(f"场{no}: {exc}")
            raise _cli.typer.Exit(code=1) from exc
    reads_out = result.reads
    if only and reads_path.exists():
        # 修订只发改动场次：合并进整期 reads，不覆盖（2026-09-26 事故：--only 把
        # 26133-reads.json 压成 1 条，语料 v2 与 F9 只剩这一场的判断）
        from nutmeg.decision.read_builder import merge_reads

        reads_out = merge_reads(_json.loads(reads_path.read_text("utf-8")), result.reads)
    reads_path.write_text(_json.dumps(reads_out, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    legs_path.write_text(_json.dumps(result.legs, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    _cli.typer.echo(format_warnings(result))
    _cli.typer.echo(f"  reads → {reads_path}\n  legs  → {legs_path}")


_LW_ISSUE_OPTION = _cli.typer.Option(None, "--issue", help="只看这一期；不给＝所有未踢完的期")
_LW_DATA_DIR_OPTION = _cli.typer.Option(_cli.Path(".nutmeg-data"), "--data-dir")
_LW_DRY_RUN_OPTION = _cli.typer.Option(False, "--dry-run", help="只打印不推、不写状态文件")
_LW_NOW_OPTION = _cli.typer.Option(None, "--now", help="伪造当前时刻（北京时间 ISO），测试用")


@_cli.app.command("zucai-lineup-watch")
def zucai_lineup_watch(
    issue: str | None = _LW_ISSUE_OPTION,
    data_dir: _cli.Path = _LW_DATA_DIR_OPTION,
    dry_run: bool = _LW_DRY_RUN_OPTION,
    now: str | None = _LW_NOW_OPTION,
) -> None:
    """售后播报巡检（launchd 每 15 分钟）：停售倒计时 / 18:30 位移 diff / 开球前 45–75 分首发复核。

    只推需要 Jun 动作的事：无票不打网；票内场关键人与研究前提相反才推；一场一期一次。
    """
    from nutmeg.decision.bj_time import aware
    from nutmeg.decision.lineup_watch import watch

    report = watch(_cli.Path(data_dir), issue=issue, dry_run=dry_run,
                   now=aware(now) if now else None)
    if not report["issues"]:
        _cli.typer.echo(f"{report['now']} lineup-watch: 无未踢完的期")
        return
    for iss, r in report["issues"].items():
        parts = []
        for kind in ("countdown", "shift", "lineup"):
            evs = r.get(kind) or []
            st = ",".join(sorted({str(e.get("status")) for e in evs})) or "-"
            parts.append(f"{kind}={st}")
        _cli.typer.echo(f"{report['now']} {iss}: " + " ".join(parts))
        for kind in ("countdown", "shift", "lineup"):
            for e in r.get(kind) or []:
                if e.get("text"):
                    _cli.typer.echo("  " + e["text"].replace("\n", "\n  "))
