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


def _build_slip(slip_id, channel, placed_at, faces, legs_file, fair_file, combo, multiplier,
                issue, scheme_no, trial, note, data_dir=Path(".nutmeg-data"), deviation="",
                prediction=""):
    from nutmeg.decision.betslip import BetSlip, BetslipError, SlipLeg, parse_faces_row

    legs: list[SlipLeg] = []
    face_map: dict[str, str] = {}
    if channel == "jczq":
        if not legs_file:
            raise BetslipError("竞彩票须给 --legs-file")
        raw = json.loads(Path(legs_file).read_text("utf-8"))
        legs = [SlipLeg(
            key=str(x["key"]), name=x.get("name", ""),
            market=x.get("market", "had"), line=x.get("line"),
            selections=tuple(x.get("selections", ())),
            odds=tuple(x.get("odds", ())), fair=x.get("fair")) for x in raw]
    else:
        if not faces:
            raise BetslipError("足彩票须给 --faces")
        face_map = parse_faces_row(faces)
        from nutmeg.decision.review_runner import issue_belief

        fair = (json.loads(Path(fair_file).read_text("utf-8")) if fair_file
                else issue_belief(data_dir, issue))
        legs = [SlipLeg(
            key=no, market="had",
            selections=tuple({"3": "home", "1": "draw", "0": "away"}[c] for c in f),
            fair=fair.get(no)) for no, f in sorted(face_map.items(), key=lambda kv: int(kv[0]))]
    return BetSlip(
        slip_id=slip_id, channel=channel, placed_at=placed_at, legs=legs,
        multiplier=multiplier,
        combo_sizes=tuple(int(c) for c in combo.split(",")) if combo else (),
        issue=issue, scheme_no=scheme_no, purchased=not trial, note=note,
        deviation=deviation, prediction=prediction, faces=face_map)


def _diagnose(slip, data_dir, planned=()):
    """登记即诊断（2026-09-30）：共享裸单（含跨渠道）与对照处方，只记录不阻断。
    `planned`：同组还没登记的计划票（整组预审时当作已购同伴一起比）。"""
    from nutmeg.decision.betslip import load_slips
    from nutmeg.decision.betslip_diagnosis import (
        DEVIATION_REASONS,
        cross_translators,
        diagnose,
        draft_faces_for,
        peers,
        prescription_for,
    )

    if slip.deviation and slip.deviation not in DEVIATION_REASONS:
        raise ValueError(f"--deviation `{slip.deviation}` 不在 {DEVIATION_REASONS}")
    slips = [*load_slips(data_dir), *planned]
    cross = cross_translators(slip, slips, data_dir)
    return diagnose(slip, peers(slip, slips, cross), prescription_for(slip, data_dir), cross,
                    draft=draft_faces_for(slip, data_dir))


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
    from nutmeg.decision.betslip import BetslipError, first_kickoff, register_slip
    from nutmeg.decision.review import review_record

    try:
        slip = _build_slip(slip_id, channel, placed_at, faces, legs_file, fair_file, combo,
                           multiplier, issue, scheme_no, trial, note, data_dir, deviation,
                           prediction)
        slip.diagnosis = _diagnose(slip, data_dir)
        slip.first_kickoff = first_kickoff(slip, data_dir)
        # 审票记录随票入账（宪法 §6）：否决了仍买是事实，账房按它出「否决仍买」一行；
        # 审票自己出错也不挡登记（登记是事实），留痕
        try:
            verdict = _review(slip, slip.diagnosis, data_dir)
            slip.diagnosis["review"] = review_record(verdict)
        except Exception as exc:  # noqa: BLE001
            verdict = {"lines": [f"审票失败：{exc!r}"[:160]]}
            slip.diagnosis["review"] = {"error": repr(exc)[:200]}
        discipline = [line for line in (_issue_brake_line(slip, data_dir),
                                        _brake_line(data_dir, placed_at)) if line]
        discipline = [line for line in discipline if line.startswith("⛔")]
        if discipline and "error" not in slip.diagnosis["review"]:
            record = slip.diagnosis["review"]
            record["vetoed"] = True
            record["codes"] = [*record["codes"],
                               *(["BRAKE"] if any("刹车" in x for x in discipline) else []),
                               *(["STOP"] if any("止损" in x or "已触发" in x
                                                 for x in discipline) else [])]
        _cli.typer.echo(register_slip(data_dir, slip))
        for line in slip.diagnosis.get("lines", []):
            _cli.typer.echo("   " + line)
        for line in verdict["lines"]:
            _cli.typer.echo("   " + line)
        for line in discipline:
            if "刹车" in line:
                _cli.typer.echo("   " + line)
        if slip.deviation_after_kickoff:
            _cli.typer.echo("   ⚠️偏离理由写于票内最早开球之后：照记，"
                            "但不进「人的偏离」按理由的净值")
        _cli.typer.echo("   " + _brake_line(data_dir, placed_at))
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


def _issue_brake_line(slip, data_dir: Path, *, extra_yuan: int = 0) -> str | None:
    """期级刹车（宪法 §4，2026-10-06 起预审否决）：本期已登记实购 + extra + 这张 是否超帽。"""
    if slip.channel == "jczq" or not slip.issue:
        return None
    from nutmeg.decision.bankroll import brake_check
    from nutmeg.decision.betslip import load_slips

    bought = sum(s.stake_yuan for s in load_slips(data_dir, issue=slip.issue)
                 if s.purchased and s.slip_id != slip.slip_id)
    return brake_check(data_dir, slip.issue, slip.stake_yuan, already_yuan=bought + extra_yuan)


def _brake_line(data_dir: Path, placed_at: str) -> str:
    """月度止损状态（宪法 §4，2026-10-01）：只打印，不阻断——登记是事实。"""
    from datetime import date as _date

    from nutmeg.decision.bankroll import brake_state, status_line

    try:
        when = _date.fromisoformat(placed_at)
    except ValueError:
        when = _date.today()
    return status_line(brake_state(data_dir, when))


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

    try:
        slip = _build_slip("preview", channel, placed_at, faces, legs_file, fair_file, combo,
                           multiplier, issue, "", False, "", data_dir, deviation, prediction)
        diag = _diagnose(slip, data_dir)
        p = slip.hit_probability
        _cli.typer.echo(f"预览 {channel} {slip.notes} 注 × {multiplier} 倍 = ¥{slip.stake_yuan:,}"
                        + (f"｜P(全对)={p * 100:.2f}%" if p is not None else ""))
        for line in diag.get("lines", []):
            _cli.typer.echo("   " + line)
        review_lines = _review_lines(slip, diag, data_dir)
        for line in review_lines:
            _cli.typer.echo("   " + line)
        brake = _brake_line(data_dir, placed_at)
        _cli.typer.echo("   " + brake)
        issue_brake = _issue_brake_line(slip, data_dir)
        if issue_brake:
            _cli.typer.echo("   " + issue_brake)
        # 月度止损触发、期级刹车超帽（宪法 §4）与 V1/V2 同级否决（2026-10-06）：预审退出码 1，
        # 登记不受此限——连亏之后最需要这条线的时候，不该只靠意志力读一行字
        vetoed = (any(line.startswith("⛔") for line in review_lines) or brake.startswith("⛔")
                  or bool(issue_brake))
        _log_preview(data_dir, slip, vetoed)
        if vetoed:
            raise _cli.typer.Exit(code=1)       # 审票否决：改票后再审（登记不受此限）
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


_PLAN = _cli.typer.Option(
    ..., "--plan",
    help="计划票 JSON 列表；每张同 preview 的参数：label/channel/placed_at/faces 或 legs_file/"
         "combo/multiplier/issue/fair_file/deviation/prediction（文件路径相对计划文件）")


@betslip_app.command("preview-set")
def betslip_preview_set(plan: Path = _PLAN, data_dir: Path = _DATA_DIR) -> None:
    """一整组计划票一起预审（2026-10-05）：每张既和已登记的实购票比，也和组内其它计划票比
    共享裸单与联死，最后报整组总额与否决张数。逐张预审看不到组内互相同死——10-05 三张足彩
    逐张都「可出」，登记第一张后才暴露三票同死 ≥26%、两票同死 ≥48%。
    不登记、不写盘（只留预审痕）。"""
    from nutmeg.decision.betslip import BetslipError

    try:
        rows = json.loads(Path(plan).read_text("utf-8"))
        base = Path(plan).parent
        slips = []
        for i, row in enumerate(rows, 1):
            label = str(row.get("label") or f"计划{i}")
            legs_file, fair_file = row.get("legs_file"), row.get("fair_file")
            slips.append(_build_slip(
                f"plan:{label}", row["channel"], row["placed_at"], row.get("faces"),
                base / legs_file if legs_file else None, base / fair_file if fair_file else None,
                row.get("combo"), int(row.get("multiplier", 1)), str(row.get("issue", "")), "",
                False, "", data_dir, row.get("deviation", ""), row.get("prediction", "")))
        for slip in slips:
            _ = slip.notes                      # 先全组校验（场数/面集合），不合法就一张都不报
        vetoed: list[str] = []
        together: dict[str, set[str]] = {}
        for slip in slips:
            diag = _diagnose(slip, data_dir, planned=[s for s in slips if s is not slip])
            p = slip.hit_probability
            _cli.typer.echo(f"【{slip.slip_id[5:]}】{slip.channel} {slip.notes} 注 × "
                            f"{slip.multiplier} 倍 = ¥{slip.stake_yuan:,}"
                            + (f"｜P(全对)={p * 100:.2f}%" if p is not None else ""))
            for line in diag.get("lines", []):
                _cli.typer.echo("   " + line)
            review_lines = _review_lines(slip, diag, data_dir)
            earlier = sum(s.stake_yuan for s in slips[:slips.index(slip)]
                          if s.issue == slip.issue and s.channel != "jczq")
            issue_brake = _issue_brake_line(slip, data_dir, extra_yuan=earlier)
            if issue_brake:
                review_lines = [*review_lines, issue_brake]
            for line in review_lines:
                _cli.typer.echo("   " + line)
            veto = any(line.startswith("⛔") for line in review_lines)
            if veto:
                vetoed.append(slip.slip_id[5:])
            for row in diag.get("shared_naked") or []:
                together.setdefault(f"{row['key']}{row['face']}", set()).update(row["slip_ids"])
            _log_preview(data_dir, slip, veto)
        total = sum(s.stake_yuan for s in slips)
        _cli.typer.echo(f"整组 {len(slips)} 张 ¥{total:,}｜否决 {len(vetoed)} 张"
                        + (f"（{'、'.join(vetoed)}）" if vetoed else ""))
        if together:
            worst = sorted(together.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            _cli.typer.echo("   整组共享裸单：" + "；".join(
                f"{key} 在 {len(ids)} 张票上" for key, ids in worst))
        brake = _brake_line(data_dir, slips[0].placed_at) if slips else ""
        if brake:
            _cli.typer.echo("   " + brake)
        if vetoed or brake.startswith("⛔"):
            raise _cli.typer.Exit(code=1)
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


def _log_preview(data_dir: Path, slip, vetoed: bool) -> None:
    """预审留痕（2026-10-02）：截止播报据此提醒「审过但还没登记」。失败不影响预审。"""
    from datetime import datetime as _datetime

    from nutmeg.decision.day_decisions import log_preview

    try:
        keys = [leg.key for leg in slip.legs] or list(slip.faces)
        log_preview(data_dir, placed_at=slip.placed_at, channel=slip.channel, issue=slip.issue,
                    keys=keys, stake=slip.stake_yuan, vetoed=vetoed,
                    now=_datetime.now().astimezone())
    except Exception as exc:  # noqa: BLE001 —— 不挡预审，但截止提醒会因此漏掉，必须看得见
        _cli.typer.echo(f"⚠️预审留痕写入失败（截止播报不会提醒这张票）：{exc!r}", err=True)


def _review(slip, diagnosis: dict, data_dir: Path) -> dict:
    """审票（2026-10-01 定位）：V1 期望回报率 / V2 共享裸单 否决，V3 倍投警告。"""
    from nutmeg.decision.review import prize_model, review
    from nutmeg.decision.review_runner import issue_market

    market = issue_market(data_dir, slip.issue) if slip.channel != "jczq" else None
    return review(slip, diagnosis, prize_model=prize_model(data_dir), market=market)


def _review_lines(slip, diagnosis: dict, data_dir: Path) -> list[str]:
    return _review(slip, diagnosis, data_dir)["lines"]


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
