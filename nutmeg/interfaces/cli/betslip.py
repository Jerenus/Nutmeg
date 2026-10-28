"""实票登记 CLI —— 「没入账 = 没打」的入口。

登记的是**已经买了的票**（倍数/方案号/试玩标记/混合过关俱全），不是预算草稿。
命令只做确定性算术与结算，不产生任何判读。
"""
from __future__ import annotations

import json
from pathlib import Path

import nutmeg.interfaces.cli as _cli

betslip_app = _cli.typer.Typer(help="实票登记与结算（没入账=没打）")
_cli.app.add_typer(betslip_app, name="betslip")

_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_SLIP_ID = _cli.typer.Option(..., "--slip-id", help="票面唯一号，如 26122-T1")
_CHANNEL_REQ = _cli.typer.Option(..., "--channel", help="jczq | renjiu | shengfucai")
_PLACED_AT = _cli.typer.Option(..., "--placed-at", help="下单日期 YYYY-MM-DD")
_FACES = _cli.typer.Option(
    None, "--faces",
    help="足彩票面：位置式 `310 10 … `(14 token) 或点名式 `2·310 3·10`")
_LEGS_FILE = _cli.typer.Option(
    None, "--legs-file", help="竞彩腿 JSON 数组（key/market/line/selections/odds/fair）")
_FAIR_FILE = _cli.typer.Option(
    None, "--fair-file", help="足彩去水 fair：{场次:{home,draw,away}}，用于算 P")
_COMBO = _cli.typer.Option(
    None, "--combo", help="竞彩过关方式，如 `4` 或 `2,3`（混合过关）")
_MULTIPLIER = _cli.typer.Option(1, "--multiplier", help="倍数")
_ISSUE_OPT = _cli.typer.Option("", "--issue", help="足彩期号")
_SCHEME_NO = _cli.typer.Option("", "--scheme-no", help="方案号/实票号")
_TRIAL = _cli.typer.Option(False, "--trial", help="试玩虚拟方案：登记但不计入实购净值")
_NOTE = _cli.typer.Option("", "--note")
_DEVIATION = _cli.typer.Option(
    "", "--deviation",
    help="相对机器初稿的偏离理由：fact_self_judged | price_instinct | stake_allocation "
         "| structure_preference | other（有差异时登记）")
_PREDICTION = _cli.typer.Option("", "--prediction", help="偏离附带的一句赛后可核验预测")
_ISSUE_FILTER = _cli.typer.Option(None, "--issue")
_CHANNEL_FILTER = _cli.typer.Option(None, "--channel")
_SLIP_FILTER = _cli.typer.Option(None, "--slip-id")
_RESULTS_FILE = _cli.typer.Option(
    ..., "--results-file",
    help="{腿key:{outcome_90,goals_h,goals_a}}；90' 口径三源核验后的赛果")
_PRIZE_PER_NOTE = _cli.typer.Option(
    None, "--prize-per-note", help="足彩官方单注奖金（gameNo=90）；缺则不产派奖数字")


def _fail(exc: Exception) -> None:
    _cli.typer.echo(f"betslip error: {exc}")
    raise _cli.typer.Exit(code=1)


def _slip_from_args(slip_id, channel, placed_at, faces, legs_file, fair_file, combo,
                    multiplier, issue, scheme_no, trial, note, data_dir=Path(".nutmeg-data"),
                    deviation="", prediction=""):
    """命令行参数 → 票：文件在这里读，其余交 `decision.precheck.build_slip`。"""
    from nutmeg.decision.precheck import build_slip

    legs = (json.loads(Path(legs_file).read_text("utf-8"))
            if channel == "jczq" and legs_file else None)
    fair = (json.loads(Path(fair_file).read_text("utf-8"))
            if channel != "jczq" and fair_file else None)
    return build_slip(slip_id=slip_id, channel=channel, placed_at=placed_at, faces=faces,
                      legs=legs, fair=fair, combo=combo, multiplier=multiplier, issue=issue,
                      scheme_no=scheme_no, trial=trial, note=note, deviation=deviation,
                      prediction=prediction, data_dir=data_dir)


@betslip_app.command("register")
def betslip_register(
    slip_id: str = _SLIP_ID,
    channel: str = _CHANNEL_REQ,
    placed_at: str = _PLACED_AT,
    faces: str | None = _FACES,
    legs_file: Path | None = _LEGS_FILE,
    fair_file: Path | None = _FAIR_FILE,
    combo: str | None = _COMBO,
    multiplier: int = _MULTIPLIER,
    issue: str = _ISSUE_OPT,
    scheme_no: str = _SCHEME_NO,
    trial: bool = _TRIAL,
    note: str = _NOTE,
    deviation: str = _DEVIATION,
    prediction: str = _PREDICTION,
    data_dir: Path = _DATA_DIR,
) -> None:
    """登记一张已买的票（幂等，同 slip_id 覆盖）。偏离初稿时带 --deviation/--prediction
    （只记录，登记是事实）。"""
    from nutmeg.decision.betslip import BetslipError
    from nutmeg.decision.precheck import register_reviewed

    try:
        slip = _slip_from_args(slip_id, channel, placed_at, faces, legs_file, fair_file, combo,
                               multiplier, issue, scheme_no, trial, note, data_dir, deviation,
                               prediction)
        out = register_reviewed(slip, data_dir)
        _cli.typer.echo(out["summary"])
        for line in out["lines"]:
            _cli.typer.echo("   " + line)
        if out["after_kickoff"]:
            _cli.typer.echo("   ⚠️偏离理由写于票内最早开球之后：照记，"
                            "但不进「人的偏离」按理由的净值")
        _cli.typer.echo("   " + out["brake_line"])
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


@betslip_app.command("preview")
def betslip_preview(
    channel: str = _CHANNEL_REQ,
    placed_at: str = _PLACED_AT,
    faces: str | None = _FACES,
    legs_file: Path | None = _LEGS_FILE,
    fair_file: Path | None = _FAIR_FILE,
    combo: str | None = _COMBO,
    multiplier: int = _MULTIPLIER,
    issue: str = _ISSUE_OPT,
    deviation: str = _DEVIATION,
    prediction: str = _PREDICTION,
    data_dir: Path = _DATA_DIR,
) -> None:
    """买之前先看：同一张票的注数/P/共享裸单/对照处方，不登记、不写盘（2026-09-30）。"""
    from nutmeg.decision.betslip import BetslipError
    from nutmeg.decision.precheck import precheck

    try:
        slip = _slip_from_args("preview", channel, placed_at, faces, legs_file, fair_file,
                               combo, multiplier, issue, "", False, "", data_dir, deviation,
                               prediction)
        out = precheck(slip, data_dir)
        p = out["p"]
        _cli.typer.echo(f"预览 {channel} {out['notes']} 注 × {multiplier} 倍 = ¥{out['stake']:,}"
                        + (f"｜P(全对)={p * 100:.2f}%" if p is not None else ""))
        for line in [*out["diagnosis_lines"], *out["review_lines"], out["brake_line"],
                     *out["discipline"]]:
            _cli.typer.echo("   " + line)
        if out["log_warning"]:
            _cli.typer.echo(out["log_warning"], err=True)
        if out["vetoed"]:
            raise _cli.typer.Exit(code=1)       # 审票否决：改票后再审（登记不受此限）
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


_PLAN = _cli.typer.Option(
    ..., "--plan",
    help="计划票 JSON 列表；每张同 preview 的参数：label/channel/placed_at/faces 或 legs_file/"
         "combo/multiplier/issue/fair_file/deviation/prediction（文件路径相对计划文件）")


_ALTERNATIVES = _cli.typer.Option(
    False, "--alternatives",
    help="计划里是互斥的备选方案（只会买其中一张）：每张只和已登记实购票比，不做组内互审、"
         "不报整组总额")


_GIVEN = _cli.typer.Option(
    None, "--given", help="钉住赛果再看各票还剩多少（可重复）：`1:1` = 场1 开平")


def _plan_slips(plan: Path, data_dir: Path) -> tuple[list[dict], list]:
    """计划 JSON → (原始行, 票)；文件路径相对计划文件。先全组校验，不合法就一张都不报。"""
    rows = json.loads(Path(plan).read_text("utf-8"))
    base = Path(plan).parent
    slips = []
    for i, row in enumerate(rows, 1):
        label = str(row.get("label") or f"计划{i}")
        legs_file, fair_file = row.get("legs_file"), row.get("fair_file")
        slips.append(_slip_from_args(
            f"plan:{label}", row["channel"], row["placed_at"], row.get("faces"),
            base / legs_file if legs_file else None, base / fair_file if fair_file else None,
            row.get("combo"), int(row.get("multiplier", 1)), str(row.get("issue", "")), "",
            False, "", data_dir, row.get("deviation", ""), row.get("prediction", "")))
    for slip in slips:
        _ = slip.notes                      # 场数/面集合校验
    return rows, slips


def _arithmetic_ready(slip) -> bool:
    """整组算术只认「每注就是整张票」的足彩票：胜负彩 14 场、任九恰 9 场，且每场有 fair。
    任九选 >9 场是复式（中 9 即中），全对连乘不是它的中奖概率。"""
    from nutmeg.decision.betslip import RENJIU_PICK, SFC_MATCHES

    need = SFC_MATCHES if slip.channel == "shengfucai" else RENJIU_PICK
    return (slip.channel != "jczq" and len(slip.faces) == need
            and all(leg.fair for leg in slip.legs))


def _group_lines(slips, data_dir: Path, alternatives: bool, pins: dict[str, str]) -> list[str]:
    """按期号出整组算术（至少中一张 / 两两同死 / 钉住赛果），已登记的本期实购票一起算。"""
    from nutmeg.decision.betslip import load_slips
    from nutmeg.decision.slip_group import report_lines

    lines = []
    for issue in dict.fromkeys(s.issue for s in slips if s.channel != "jczq"):
        plan = [s for s in slips if s.channel != "jczq" and s.issue == issue]
        bought = [s for s in load_slips(data_dir, issue=issue)
                  if s.purchased and s.channel != "jczq"]
        skipped = [s.slip_id.removeprefix("plan:") for s in [*bought, *plan]
                   if not _arithmetic_ready(s)]
        if skipped:
            lines.append(f"整组算术（{issue}）跳过：{'、'.join(skipped)}"
                         "（任九 >9 场复式或缺 fair）")
        bought = [s for s in bought if _arithmetic_ready(s)]
        plan = [s for s in plan if _arithmetic_ready(s)]
        fair = {leg.key: leg.fair for s in [*bought, *plan] for leg in s.legs}
        lines += report_lines([(s.slip_id[5:], s.faces) for s in plan],
                              [(s.slip_id, s.faces) for s in bought], fair, issue=issue,
                              alternatives=alternatives, results=pins)
    return lines


def _pins(items: list[str] | None, *, single: bool) -> dict[str, str]:
    """`["1:1", "13:0"]` → {"1": "1", "13": "0"}；`single`＝每场只许一个结果（赛果）。"""
    from nutmeg.decision.betslip import BetslipError, parse_faces_row

    if not items:
        return {}
    out = parse_faces_row(" ".join(items))
    if single and any(len(f) != 1 for f in out.values()):
        raise BetslipError(f"--given 每场只能钉一个结果：{items}")
    return out


@betslip_app.command("preview-set")
def betslip_preview_set(plan: Path = _PLAN, data_dir: Path = _DATA_DIR,
                        alternatives: bool = _ALTERNATIVES,
                        given: list[str] | None = _GIVEN) -> None:
    """一整组计划票一起预审（2026-10-05）：每张既和已登记的实购票比，也和组内其它计划票比
    共享裸单与联死，最后报整组总额与否决张数。逐张预审看不到组内互相同死——10-05 三张足彩
    逐张都「可出」，登记第一张后才暴露三票同死 ≥26%、两票同死 ≥48%。
    不登记、不写盘（只留预审痕）。

    `--alternatives`（2026-10-08）：比较互斥备选时组内互审没有意义——四张备选共享同一条裸单
    是同一个判断的四种写法，不是假分散；那时每张都被组内其它张 V2 否决，读不出任何差别。

    整组算术（2026-10-09）：至少中一张、两两同死（同死点＝都选了的场里谁都没盖的面）、
    `--given` 钉住赛果后各票还剩多少；备选模式改报「每张与已登记实购票合起来」。26136 那天
    第一版副单照抄主单的选法，主副同死 73.7%——单看两张的 P 读不出来。"""
    from nutmeg.decision.betslip import BetslipError
    from nutmeg.decision.precheck import brake_line, log_preview_safe, precheck

    try:
        pins = _pins(given, single=True)
        _, slips = _plan_slips(plan, data_dir)
        vetoed: list[str] = []
        together: dict[str, set[str]] = {}
        if alternatives:
            _cli.typer.echo(f"互斥备选 {len(slips)} 张：每张只和已登记实购票比（不做组内互审）")
        for slip in slips:
            earlier = 0 if alternatives else sum(
                s.stake_yuan for s in slips[:slips.index(slip)]
                if s.issue == slip.issue and s.channel != "jczq")
            same_day = 0 if alternatives else sum(
                s.stake_yuan for s in slips[:slips.index(slip)]
                if str(s.placed_at)[:10] == str(slip.placed_at)[:10])
            out = precheck(slip, data_dir, planned=(
                [] if alternatives else [s for s in slips if s is not slip]),
                extra_issue_yuan=earlier, extra_day_yuan=same_day, log=False)
            p = out["p"]
            _cli.typer.echo(f"【{slip.slip_id[5:]}】{slip.channel} {out['notes']} 注 × "
                            f"{slip.multiplier} 倍 = ¥{out['stake']:,}"
                            + (f"｜P(全对)={p * 100:.2f}%" if p is not None else ""))
            for line in out["diagnosis_lines"]:
                _cli.typer.echo("   " + line)
            review_lines = [*out["review_lines"], *out["discipline"]]
            for line in review_lines:
                _cli.typer.echo("   " + line)
            # 逐张否决不含月度止损（止损在整组末行报一次、单独决定退出码）
            veto = any(line.startswith("⛔") for line in review_lines)
            if veto:
                vetoed.append(slip.slip_id[5:])
            for row in out["diagnosis"].get("shared_naked") or []:
                together.setdefault(f"{row['key']}{row['face']}", set()).update(row["slip_ids"])
            warning = log_preview_safe(data_dir, slip, veto)
            if warning:
                _cli.typer.echo(warning, err=True)
        total = sum(s.stake_yuan for s in slips)
        if alternatives:
            _cli.typer.echo(f"备选 {len(slips)} 张｜否决 {len(vetoed)} 张"
                            + (f"（{'、'.join(vetoed)}）" if vetoed else ""))
        else:
            _cli.typer.echo(f"整组 {len(slips)} 张 ¥{total:,}｜否决 {len(vetoed)} 张"
                            + (f"（{'、'.join(vetoed)}）" if vetoed else ""))
        if together and not alternatives:
            worst = sorted(together.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            _cli.typer.echo("   整组共享裸单：" + "；".join(
                f"{key} 在 {len(ids)} 张票上" for key, ids in worst))
        for line in _group_lines(slips, data_dir, alternatives, pins):
            _cli.typer.echo(line)
        brake = brake_line(data_dir, slips[0].placed_at) if slips else ""
        if brake:
            _cli.typer.echo("   " + brake)
        if vetoed or brake.startswith("⛔"):
            raise _cli.typer.Exit(code=1)
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


_BASE_PLAN = _cli.typer.Option(..., "--plan", help="基准票（同 preview-set 的计划 JSON）")
_SEARCH_CHANNEL = _cli.typer.Option("renjiu", "--channel", help="要搜的票：renjiu | shengfucai")
_MAX_NOTES = _cli.typer.Option(..., "--max-notes", help="注数帽（金额＝注数×2）")
_FIX = _cli.typer.Option(None, "--fix", help="固定某场的面（可重复）：`1:31`")


@betslip_app.command("complement")
def betslip_complement(plan: Path = _BASE_PLAN, channel: str = _SEARCH_CHANNEL,
                       max_notes: int = _MAX_NOTES, fix: list[str] | None = _FIX,
                       data_dir: Path = _DATA_DIR) -> None:
    """固定基准票，在注数帽内搜一张让「至少中一张」最大的票（2026-10-09）。

    不与任何基准票共享裸单（V2 会否决的结构搜出来也没法买）。26136：与主单同价的副单，
    照抄主单选法合起来 14.13%，搜出来的反着选 16.27%。只算术，不登记、不写盘。"""
    from nutmeg.decision.betslip import (
        PRICE_PER_NOTE,
        RENJIU_PICK,
        SFC_MATCHES,
        BetslipError,
    )
    from nutmeg.decision.precheck import zucai_fair
    from nutmeg.decision.slip_group import best_complement, death_text, p_all, p_any, pct

    try:
        if channel not in ("renjiu", "shengfucai"):
            raise BetslipError("--channel 只能是 renjiu 或 shengfucai")
        rows, slips = _plan_slips(plan, data_dir)
        pairs = [(row, s) for row, s in zip(rows, slips, strict=True) if s.channel != "jczq"]
        if not pairs or any(not _arithmetic_ready(s) for _, s in pairs):
            raise BetslipError("基准须是足彩票（胜负彩 14 场 / 任九恰 9 场）且每场有 fair")
        row, first = pairs[0]
        fair = (json.loads((Path(plan).parent / row["fair_file"]).read_text("utf-8"))
                if row.get("fair_file") else zucai_fair(data_dir, first.issue))
        base = [(s.slip_id[5:], s.faces) for _, s in pairs]
        fixed = _pins(fix, single=False)
        found = best_complement([t for _, t in base], fair, max_notes=max_notes, fixed=fixed,
                                n_matches=SFC_MATCHES if channel == "shengfucai"
                                else RENJIU_PICK)
        before = p_any([t for _, t in base], fair)
        _cli.typer.echo(f"互补搜索（{first.issue}，基准 {len(base)} 张，"
                        f"至少中一张 {pct(before)}）："
                        f"{channel} ≤{max_notes} 注"
                        + (f"，固定 {' '.join(f'{k}:{v}' for k, v in fixed.items())}"
                           if fixed else "") + "；不与基准共享裸单")
        if found is None:
            raise BetslipError("帽内找不到合法的票（注数 / 固定面 / 不共享裸单 三条同时满足）")
        union, ticket = found
        notes = 1
        for f in ticket.values():
            notes *= len(f)
        order = sorted(ticket, key=int)
        _cli.typer.echo(f"最好的一张：{' '.join(f'{no}:{ticket[no]}' for no in order)}｜"
                        f"{notes} 注 ¥{notes * PRICE_PER_NOTE:,}｜"
                        f"P(全对) {pct(p_all([ticket], fair))}")
        _cli.typer.echo(f"   合起来至少中一张 {pct(union)}（+{(union - before) * 100:.2f}pp）；"
                        + "；".join(f"与 {label} 同死 {death_text([t, ticket], fair)}"
                                   for label, t in base))
        singles = [f"{no}:{ticket[no]}({p_all([{no: ticket[no]}], fair) * 100:.0f}%)"
                   for no in order if len(ticket[no]) == 1]
        if singles:
            _cli.typer.echo("   单选：" + "、".join(singles))
        _cli.typer.echo("⚠️局部搜索（固定种子随机重启），不保证全局最优；"
                        "概率来自 fair，结论随 fair 变")
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


@betslip_app.command("list")
def betslip_list(
    issue: str | None = _ISSUE_FILTER,
    channel: str | None = _CHANNEL_FILTER,
    data_dir: Path = _DATA_DIR,
) -> None:
    """列出已登记票面；方案号缺失会显式标出（账空是刹车条款失效的根因）。"""
    from nutmeg.decision.betslip import format_slips, load_slips

    _cli.typer.echo(format_slips(load_slips(data_dir, issue=issue, channel=channel)))


@betslip_app.command("settle")
def betslip_settle(
    results_file: Path = _RESULTS_FILE,
    issue: str | None = _ISSUE_FILTER,
    channel: str | None = _CHANNEL_FILTER,
    slip_id: str | None = _SLIP_FILTER,
    prize_per_note: float | None = _PRIZE_PER_NOTE,
    data_dir: Path = _DATA_DIR,
) -> None:
    """结算已登记票面（竞彩按赔率连乘；足彩须给官方单注奖金）。"""
    from nutmeg.decision.betslip import load_slips, settle_slip

    results = json.loads(Path(results_file).read_text("utf-8"))
    slips = load_slips(data_dir, issue=issue, channel=channel)
    if slip_id:
        slips = [s for s in slips if s.slip_id == slip_id]
    if not slips:
        _cli.typer.echo("(无匹配票面)")
        return
    total_stake = total_payout = 0.0
    pending = False
    for slip in slips:
        s = settle_slip(slip, results, prize_per_note=prize_per_note)
        _cli.typer.echo(f"\n== {slip.slip_id} {slip.channel} ¥{slip.stake_yuan:,}"
                        + ("" if slip.purchased else "（试玩）"))
        for line in s.detail:
            _cli.typer.echo(f"   {line}")
        if s.payout_yuan is None:
            pending = True
            _cli.typer.echo(f"   未结：{s.pending_legs} 腿赛果缺（不伪造派奖）")
            continue
        _cli.typer.echo(f"   中 {s.combos_won}/{s.combos_total} 串 → 派奖 "
                        f"¥{s.payout_yuan:,.2f}｜净 {s.pnl_yuan:+,.2f}")
        if slip.purchased:
            total_stake += slip.stake_yuan
            total_payout += s.payout_yuan
    tag = "（含未结票，合计只统计已结部分）" if pending else ""
    _cli.typer.echo(f"\n合计实购 投入 ¥{total_stake:,.0f} 派奖 ¥{total_payout:,.0f} "
                    f"净 {total_payout - total_stake:+,.0f}{tag}")
