"""预审与带审票登记的唯一实现（2026-10-27 产品形态第 0 阶段）。

此前整条流水线只在 `interfaces/cli/betslip.py` 的私有函数里，decision-web 的登记端点自己
拼了半份（不记 STOP/BRAKE/DAYCAP、不收偏离理由）。CLI、期页、竞彩板现在都调这里。
登记是事实：审票与纪律只记录，从不拦登记。
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from pathlib import Path

from nutmeg.decision.betslip import (
    BetSlip,
    BetslipError,
    SlipLeg,
    first_kickoff,
    load_slips,
    parse_faces_row,
    register_slip,
)

_SEL = {"3": "home", "1": "draw", "0": "away"}


def build_slip(*, slip_id: str, channel: str, placed_at: str, faces: str | None = None,
               legs: list[dict] | None = None, fair: dict | None = None, combo: str | None = None,
               multiplier: int = 1, issue: str = "", scheme_no: str = "", trial: bool = False,
               note: str = "", deviation: str = "", prediction: str = "",
               data_dir: Path = Path(".nutmeg-data")) -> BetSlip:
    """竞彩给 `legs`（腿 JSON 数组）；足彩给 `faces`，`fair` 缺省取 legs-base 判断概率。"""
    face_map: dict[str, str] = {}
    if channel == "jczq":
        if not legs:
            raise BetslipError("竞彩票须给 --legs-file")
        slip_legs = [SlipLeg(
            key=str(x["key"]), name=x.get("name", ""),
            market=x.get("market", "had"), line=x.get("line"),
            selections=tuple(x.get("selections", ())),
            odds=tuple(x.get("odds", ())), fair=x.get("fair")) for x in legs]
    else:
        if not faces:
            raise BetslipError("足彩票须给 --faces")
        face_map = parse_faces_row(faces)
        board = fair if fair is not None else zucai_fair(data_dir, issue)
        slip_legs = [SlipLeg(
            key=no, market="had", selections=tuple(_SEL[c] for c in f),
            fair=board.get(no)) for no, f in sorted(face_map.items(), key=lambda kv: int(kv[0]))]
    return BetSlip(
        slip_id=slip_id, channel=channel, placed_at=placed_at, legs=slip_legs,
        multiplier=multiplier,
        combo_sizes=tuple(int(c) for c in combo.split(",")) if combo else (),
        issue=issue, scheme_no=scheme_no, purchased=not trial, note=note,
        deviation=deviation, prediction=prediction, faces=face_map)


def zucai_fair(data_dir: Path, issue: str) -> dict[str, dict]:
    """足彩整板 fair：legs-base 的判断概率（CLI 不给 --fair-file 时同口径）。"""
    from nutmeg.decision.review_runner import issue_belief

    return issue_belief(data_dir, issue)


def diagnose_slip(slip: BetSlip, data_dir: Path, planned=()) -> dict:
    """登记即诊断（2026-09-30）：共享裸单（含跨渠道）与对照处方，只记录不阻断。
    `planned`：同组还没登记的计划票（整组预审时当作已购同伴一起比）。"""
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


def review_verdict(slip: BetSlip, diagnosis: dict, data_dir: Path) -> dict:
    """审票（2026-10-01 定位）：V1 期望回报率 / V2 共享裸单 否决，V3 倍投警告。"""
    from nutmeg.decision.review import prize_model, review
    from nutmeg.decision.review_runner import issue_market

    market = issue_market(data_dir, slip.issue) if slip.channel != "jczq" else None
    return review(slip, diagnosis, prize_model=prize_model(data_dir), market=market)


def issue_brake_line(slip: BetSlip, data_dir: Path, *, extra_yuan: int = 0) -> str | None:
    """期级刹车（宪法 §4，2026-10-06 起预审否决）：本期已登记实购 + extra + 这张 是否超帽。"""
    if slip.channel == "jczq" or not slip.issue:
        return None
    from nutmeg.decision.bankroll import brake_check

    bought = sum(s.stake_yuan for s in load_slips(data_dir, issue=slip.issue)
                 if s.purchased and s.slip_id != slip.slip_id)
    return brake_check(data_dir, slip.issue, slip.stake_yuan, already_yuan=bought + extra_yuan)


def day_cap_line(slip: BetSlip, data_dir: Path, *, extra_yuan: int = 0) -> str | None:
    """日总帽 ¥2,000（宪法 §4，2026-10-12 入预审）：同一下单日已登记实购（所有渠道）
    + extra + 这张 是否超帽；预审否决，登记不受限。"""
    from nutmeg.decision.bankroll import day_cap_check

    day = str(slip.placed_at)[:10]
    bought = sum(s.stake_yuan for s in load_slips(data_dir)
                 if s.purchased and s.slip_id != slip.slip_id and str(s.placed_at)[:10] == day)
    return day_cap_check(day, slip.stake_yuan, already_yuan=bought + extra_yuan)


def brake_line(data_dir: Path, placed_at: str) -> str:
    """月度止损状态（宪法 §4，2026-10-01）：只打印，不阻断——登记是事实。"""
    from nutmeg.decision.account import pending_ledger
    from nutmeg.decision.bankroll import brake_state, status_line

    try:
        when = _date.fromisoformat(placed_at)
    except ValueError:
        when = _date.today()
    try:   # 待结实购票按全损计（2026-10-28）；登记簿读不出就退回已结账口径
        pending = pending_ledger(data_dir, when.strftime("%Y-%m"))
    except Exception:  # noqa: BLE001
        pending = None
    return status_line(brake_state(data_dir, when, pending=pending))


def log_preview_safe(data_dir: Path, slip: BetSlip, vetoed: bool) -> str | None:
    """预审留痕（2026-10-02）：截止播报据此提醒「审过但还没登记」。失败不影响预审：
    返回告警文本（调用方负责让人看见），不抛。"""
    from nutmeg.decision.day_decisions import log_preview

    try:
        keys = [leg.key for leg in slip.legs] or list(slip.faces)
        log_preview(data_dir, placed_at=slip.placed_at, channel=slip.channel, issue=slip.issue,
                    keys=keys, stake=slip.stake_yuan, vetoed=vetoed,
                    now=datetime.now().astimezone(), faces=slip.faces or None,
                    p=slip.hit_probability)
        return None
    except Exception as exc:  # noqa: BLE001 —— 不挡预审，但截止提醒会因此漏掉，必须看得见
        return f"⚠️预审留痕写入失败（截止播报不会提醒这张票）：{exc!r}"


def precheck(slip: BetSlip, data_dir: Path, *, planned=(), extra_issue_yuan: int = 0,
             extra_day_yuan: int = 0, log: bool = True) -> dict:
    """一张票的全部预审结果（CLI `betslip preview` 与 `/api/precheck` 同一份）。"""
    data_dir = Path(data_dir)
    diagnosis = diagnose_slip(slip, data_dir, planned)
    verdict = review_verdict(slip, diagnosis, data_dir)
    brake = brake_line(data_dir, slip.placed_at)
    issue_brake = issue_brake_line(slip, data_dir, extra_yuan=extra_issue_yuan)
    day_cap = day_cap_line(slip, data_dir, extra_yuan=extra_day_yuan)
    discipline = [x for x in (issue_brake, day_cap) if x]
    # 月度止损触发、期级刹车超帽、日帽超帽（宪法 §4）与 V1/V2 同级否决（2026-10-06）：
    # 预审否决，登记不受此限——连亏之后最需要这条线的时候，不该只靠意志力读一行字
    vetoed = bool(verdict["vetoed"] or brake.startswith("⛔") or discipline)
    warning = log_preview_safe(data_dir, slip, vetoed) if log else None
    return {"notes": slip.notes, "stake": slip.stake_yuan, "multiplier": slip.multiplier,
            "p": slip.hit_probability, "diagnosis": diagnosis,
            "diagnosis_lines": diagnosis.get("lines", []), "verdicts": verdict["verdicts"],
            "ratio": verdict["ratio"], "review_lines": verdict["lines"],
            "discipline": discipline, "brake_line": brake, "vetoed": vetoed,
            "log_warning": warning}


def register_reviewed(slip: BetSlip, data_dir: Path) -> dict:
    """带审票登记（宪法 §6：审票随票入账）。纪律否决记码不拦登记。

    返回 `brake_line` 是登记**之后**的月度止损状态（这张票已算进待结）。"""
    from nutmeg.decision.review import review_record

    data_dir = Path(data_dir)
    slip.diagnosis = diagnose_slip(slip, data_dir)
    slip.first_kickoff = first_kickoff(slip, data_dir)
    # 审票记录随票入账（宪法 §6）：否决了仍买是事实，账房按它出「否决仍买」一行；
    # 审票自己出错也不挡登记（登记是事实），留痕
    try:
        verdict = review_verdict(slip, slip.diagnosis, data_dir)
        slip.diagnosis["review"] = review_record(verdict)
    except Exception as exc:  # noqa: BLE001
        verdict = {"lines": [f"审票失败：{exc!r}"[:160]]}
        slip.diagnosis["review"] = {"error": repr(exc)[:200]}
    discipline = [x for x in (issue_brake_line(slip, data_dir), day_cap_line(slip, data_dir),
                              brake_line(data_dir, slip.placed_at)) if x and x.startswith("⛔")]
    if discipline and "error" not in slip.diagnosis["review"]:
        record = slip.diagnosis["review"]
        record["vetoed"] = True
        record["codes"] = [*record["codes"],
                           *(["BRAKE"] if any("刹车" in x for x in discipline) else []),
                           *(["DAYCAP"] if any("日帽" in x for x in discipline) else []),
                           *(["STOP"] if any("止损" in x or "已触发" in x
                                             for x in discipline) else [])]
    summary = register_slip(data_dir, slip)
    return {"summary": summary,
            "lines": [*slip.diagnosis.get("lines", []), *verdict["lines"],
                      *[x for x in discipline if "刹车" in x or "日帽" in x]],
            "after_kickoff": bool(slip.deviation_after_kickoff),
            "brake_line": brake_line(data_dir, slip.placed_at)}
