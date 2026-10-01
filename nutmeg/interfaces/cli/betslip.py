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
_ISSUE_FILTER = _cli.typer.Option(None, "--issue")
_CHANNEL_FILTER = _cli.typer.Option(None, "--channel")
_SLIP_FILTER = _cli.typer.Option(None, "--slip-id")
_RESULTS_FILE = _cli.typer.Option(
    ..., "--results-file",
    help="{腿key:{outcome_90,goals_h,goals_a}}；90' 口径三源核验后的赛果")
_PRIZE_PER_NOTE = _cli.typer.Option(
    None, "--prize-per-note", help="足彩官方单注奖金（gameNo=90）；缺则不产派奖数字")
_FACES_REQ = _cli.typer.Option(..., "--faces")
_N_MATCHES = _cli.typer.Option(14, "--n-matches")


def _fail(exc: Exception) -> None:
    _cli.typer.echo(f"betslip error: {exc}")
    raise _cli.typer.Exit(code=1)


def _build_slip(slip_id, channel, placed_at, faces, legs_file, fair_file, combo, multiplier,
                issue, scheme_no, trial, note, data_dir=Path(".nutmeg-data")):
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
        faces=face_map)


def _diagnose(slip, data_dir):
    """登记即诊断（2026-09-30）：共享裸单（含跨渠道）与对照处方，只记录不阻断。"""
    from nutmeg.decision.betslip import load_slips
    from nutmeg.decision.betslip_diagnosis import (
        cross_translators,
        diagnose,
        peers,
        prescription_for,
    )

    slips = load_slips(data_dir)
    cross = cross_translators(slip, slips, data_dir)
    return diagnose(slip, peers(slip, slips, cross), prescription_for(slip, data_dir), cross)


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
    data_dir: Path = _DATA_DIR,
) -> None:
    """登记一张已买的票（幂等，同 slip_id 覆盖）。"""
    from nutmeg.decision.betslip import BetslipError, register_slip

    try:
        slip = _build_slip(slip_id, channel, placed_at, faces, legs_file, fair_file, combo,
                           multiplier, issue, scheme_no, trial, note, data_dir)
        slip.diagnosis = _diagnose(slip, data_dir)
        if slip.channel == "jczq" and slip.purchased:
            # 实票入账到本体（2026-10-01）：登记是事实，内核是镜像；镜像失败不挡登记
            from nutmeg.decision.ledger_writeback import writeback_jczq_slip

            try:
                slip.diagnosis["kernel"] = writeback_jczq_slip(slip, data_dir=data_dir)
            except Exception as exc:  # noqa: BLE001 — 内核不可用时留痕不抛
                slip.diagnosis["kernel"] = {"status": "error", "error": repr(exc)[:200]}
        _cli.typer.echo(register_slip(data_dir, slip))
        for line in slip.diagnosis.get("lines", []):
            _cli.typer.echo("   " + line)
        for line in _review_lines(slip, slip.diagnosis, data_dir):
            _cli.typer.echo("   " + line)
        if slip.diagnosis.get("kernel"):
            from nutmeg.decision.ledger_writeback import summary_line

            _cli.typer.echo("   " + summary_line(slip.diagnosis["kernel"]))
        _cli.typer.echo("   " + _brake_line(data_dir, placed_at))
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


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
    data_dir: Path = _DATA_DIR,
) -> None:
    """买之前先看：同一张票的注数/P/共享裸单/对照处方，不登记、不写盘（2026-09-30）。"""
    from nutmeg.decision.betslip import BetslipError

    try:
        slip = _build_slip("preview", channel, placed_at, faces, legs_file, fair_file, combo,
                           multiplier, issue, "", False, "", data_dir)
        diag = _diagnose(slip, data_dir)
        p = slip.hit_probability
        _cli.typer.echo(f"预览 {channel} {slip.notes} 注 × {multiplier} 倍 = ¥{slip.stake_yuan:,}"
                        + (f"｜P(全对)={p * 100:.2f}%" if p is not None else ""))
        for line in diag.get("lines", []):
            _cli.typer.echo("   " + line)
        review_lines = _review_lines(slip, diag, data_dir)
        for line in review_lines:
            _cli.typer.echo("   " + line)
        _cli.typer.echo("   " + _brake_line(data_dir, placed_at))
        if any(line.startswith("⛔") for line in review_lines):
            raise _cli.typer.Exit(code=1)       # 审票否决：改票后再审（登记不受此限）
    except (BetslipError, KeyError, ValueError) as exc:
        _fail(exc)


def _review_lines(slip, diagnosis: dict, data_dir: Path) -> list[str]:
    """审票（2026-10-01 定位）：V1 期望回报率 / V2 共享裸单 否决，V3 倍投警告。"""
    from nutmeg.decision.review import prize_model, review
    from nutmeg.decision.review_runner import issue_market

    market = issue_market(data_dir, slip.issue) if slip.channel != "jczq" else None
    return review(slip, diagnosis, prize_model=prize_model(data_dir), market=market)["lines"]


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


@betslip_app.command("parse")
def betslip_parse(
    faces: str = _FACES_REQ,
    n_matches: int = _N_MATCHES,
) -> None:
    """把一行票面解析成 {场次: 面集合} —— 人眼读 31/30 是系统性错误源。"""
    from nutmeg.decision.betslip import BetslipError, parse_faces_row

    try:
        out = parse_faces_row(faces, n_matches=n_matches)
    except BetslipError as exc:
        _fail(exc)
        return
    _cli.typer.echo(json.dumps(out, ensure_ascii=False, indent=1))
