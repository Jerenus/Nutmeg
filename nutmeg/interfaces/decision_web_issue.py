"""期页与竞彩当日板的路由（2026-10-27 产品形态）。只读组装 + 转调 precheck / bridge；不产生判断。

§3 桥（2026-10-28 第 3 阶段）：`/api/bridge/{期}/preview` 只读；`/action/bridge` 登记桥后票
`<期>-B1`（试玩）再写 `zucai/<期>-bridge.jsonl`——登记失败不写桥记录，只走一次由桥记录守。

500 票面（第 4 阶段）：先照抄录卡在 500 app 下单，再登记实票。`/api/issue/{期}/slip500` 只算不写；
`/action/issue/{期}/register` 登记 `<期>-T<n>`（实购，票号由 `betslip.next_slip_id` 分配）。
"""
from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

_ISSUE = re.compile(r"\d{5}")

# precheck.build_slip 的报错是写给命令行的；页面上换成人话（precheck 不改）
_PAGE_WORDS = {"足彩票须给 --faces": "还没选场", "竞彩票须给 --legs-file": "还没选腿"}
_SHORT = re.compile(r"任九至少选 (\d+) 场，实得 (\d+) 场")


def _check_issue(issue: str) -> str:
    if not _ISSUE.fullmatch(issue):
        raise HTTPException(status_code=400, detail="期号须为 5 位数字")
    return issue


def _page_error(message: str) -> str:
    if message in _PAGE_WORDS:
        return _PAGE_WORDS[message]
    if short := _SHORT.fullmatch(message):
        need, got = int(short[1]), int(short[2])
        return f"任九还差 {need - got} 场（已选 {got} 场）"
    return message


def _error_text(error: Exception) -> str:
    message = error.args[0] if isinstance(error, KeyError) and error.args else error
    return _page_error(str(message))


def _today_bj() -> str:
    from datetime import datetime

    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ).date().isoformat()


def _picked(faces: dict | None) -> dict[str, str]:
    """页面传来的 {场号: 面}，空面（未选）去掉。"""
    return {str(k): str(v) for k, v in (faces or {}).items() if v}


def _matrices(data_dir: Path, issue: str, errors: list[str]) -> dict[str, dict]:
    from nutmeg.decision.counter_matrix import issue_matrices

    try:
        return {m["no"]: m for m in issue_matrices(data_dir, issue)}
    except Exception as exc:  # noqa: BLE001 —— 矩阵缺席要看得见，不能读成「没有证据」
        errors.append(f"反证矩阵失败：{exc!r}"[:200])
        return {}


def _names(data_dir: Path, issue: str, matrices: dict[str, dict]) -> dict[str, str]:
    """{场号: 主-客}（1–14 全有键）：期次文件优先，缺则反证矩阵（legs-base）的名字。"""
    from nutmeg.decision.lineup_watch import issue_doc, match_names

    doc = issue_doc(data_dir, issue)
    names = {no: f"{t[0]}-{t[1]}" for no, t in match_names(doc).items()} if doc else {}
    return {str(i): names.get(str(i)) or (matrices.get(str(i)) or {}).get("name", "")
            for i in range(1, 15)}


def _multiplier(raw) -> int:
    try:
        value = int(1 if raw in (None, "") else raw)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= 99:
        raise ValueError("倍数须为 1–99 的整数")
    return value


def _sale_ticket(data_dir: Path, issue: str, payload: dict, *, slip_id: str, deviation: str = "",
                 prediction: str = "", scheme_no: str = ""):
    """500 下单的那张票（实购）：9 场＝任九、14 场＝胜负彩，其它场数不成票。不写文件。"""
    from nutmeg.decision.betslip import RENJIU_PICK, SFC_MATCHES, format_faces_row, parse_faces_row
    from nutmeg.decision.precheck import build_slip

    picked = _picked(payload.get("faces"))
    faces = parse_faces_row(format_faces_row(picked)) if picked else {}
    channel = {RENJIU_PICK: "renjiu", SFC_MATCHES: "shengfucai"}.get(len(faces))
    if channel is None:
        raise ValueError(f"任九要 {RENJIU_PICK} 场、胜负彩要 {SFC_MATCHES} 场"
                         f"（已选 {len(faces)} 场）")
    return build_slip(slip_id=slip_id, channel=channel, placed_at=_today_bj(),
                      faces=format_faces_row(faces), issue=issue,
                      multiplier=_multiplier(payload.get("multiplier")), scheme_no=scheme_no,
                      trial=False, deviation=deviation, prediction=prediction, data_dir=data_dir)


def _zucai_gates(slip) -> list[dict]:
    """死法清单前五门（slip 腿上的 fair）。"""
    from nutmeg.decision.slip_group import death_list, is_coin

    fair = {leg.key: leg.fair for leg in slip.legs if leg.fair}
    ticket = {no: f for no, f in slip.faces.items() if no in fair}
    ordered, _ = death_list([ticket], fair, top=5)
    return [{"no": no, "face": f, "p": p, "coin": is_coin(fair[no])} for no, f, p in ordered[:5]]


def _zucai_mode(channel: str, n: int) -> str:
    from nutmeg.decision.betslip import RENJIU_PICK, SFC_MATCHES

    if channel == "shengfucai":
        return "胜负彩" if n == SFC_MATCHES else f"胜负彩 · 还差 {SFC_MATCHES - n} 场"
    if n == RENJIU_PICK:
        return "任九"
    if n < RENJIU_PICK:
        return f"任九 · 还差 {RENJIU_PICK - n} 场"
    return f"{n} 场 · 任九不可购"


def _parlay(sizes: tuple[int, ...], n_legs: int) -> str:
    if sizes == (1,) and n_legs == 1:
        return "单关"
    return "+".join(f"{m}串1" for m in sizes)


def issue_payload(data_dir: Path, issue: str, *, today: _date) -> dict:
    from nutmeg.decision.bankroll import issue_brake
    from nutmeg.decision.bridge import bridge_record
    from nutmeg.decision.files import read_json
    from nutmeg.decision.packet_doc import load_packet
    from nutmeg.decision.precheck import brake_line, month_brake
    from nutmeg.decision.review_runner import issue_market

    errors: list[str] = []
    packet = load_packet(data_dir, issue)
    errors += packet["errors"]
    market = issue_market(data_dir, issue)
    matrices = _matrices(data_dir, issue, errors)
    draft = read_json(Path(data_dir) / "zucai" / f"{issue}-draft.json", None)
    if draft is None:
        errors.append(f"缺 {issue}-draft.json（judgment draft --write 未跑）")
    names = _names(data_dir, issue, matrices)
    # 止损块与 CLI 预审同一份「实质余量」（待结实购票按全损计）
    state = month_brake(data_dir, today.isoformat())
    matches = []
    for i in range(1, 15):
        no = str(i)
        matrix = matrices.get(no)
        matches.append({"no": no, "name": names[no],
                        "fair": market.get(no), "packet": packet["by_no"].get(no),
                        "matrix": matrix})
    return {"issue": issue, "matches": matches, "default": packet["default"],
            "main_shape": packet["main_shape"], "alternatives": packet["alternatives"],
            "signed_bold": packet["signed_bold"], "built_at": packet.get("built_at"),
            "draft_candidates": (draft or {}).get("candidates") or [],
            "brake": {**state, "line": brake_line(data_dir, today.isoformat()),
                      "issue": issue_brake(data_dir, issue)},
            "bridge": bridge_record(data_dir, issue), "errors": errors}


def bridge_view(data_dir: Path, issue: str, payload: dict, *, slip_id: str = "preview",
                trial: bool = True, deviation: str = "", prediction: str = "") -> tuple:
    """桥上一版票的全部读数（preview 与定稿同一份）→ (slip, view)。不写任何文件。
    任九 9 场之外按 14 场＝胜负彩；`faces` 是页面的 {场号: 面}，丢的场不传。"""
    from nutmeg.decision.betslip import SFC_MATCHES, format_faces_row
    from nutmeg.decision.bridge import cite_readout, diff_cells, opening_lines, self_checks
    from nutmeg.decision.choice_ledger import shape_of
    from nutmeg.decision.packet_doc import load_packet
    from nutmeg.decision.precheck import build_slip, precheck
    from nutmeg.decision.review_runner import issue_market

    faces = _picked(payload.get("faces"))
    channel = "shengfucai" if len(faces) == SFC_MATCHES else "renjiu"
    slip = build_slip(slip_id=slip_id, channel=channel, placed_at=_today_bj(),
                      faces=format_faces_row(faces) if faces else None, issue=issue,
                      trial=trial, deviation=deviation, prediction=prediction,
                      data_dir=data_dir)
    pre = precheck(slip, data_dir, log=False)
    packet = load_packet(data_dir, issue)
    errors = list(packet["errors"])
    gates = _zucai_gates(slip)
    main = packet["main_shape"] or {}
    diffs = diff_cells(slip.faces, main.get("faces") or {}, issue_market(data_dir, issue),
                       {str(k): v for k, v in (payload.get("cites") or {}).items()},
                       {str(k): v for k, v in (payload.get("outs") or {}).items()},
                       _matrices(data_dir, issue, errors))
    # 桥上签的博胆只认票内的单（双 / 包 / 丢的场号一律忽略），带上票面面——记录写明签了什么
    signed = [{"no": no, "face": f} for no in dict.fromkeys(
        str(x) for x in payload.get("signed_bold") or [])
        if len(f := slip.faces.get(no) or "") == 1]
    return slip, {"opening": opening_lines(packet, slip.faces, gates),
                  "checks": self_checks(packet, slip.faces, pre,
                                        signed_bold=[x["no"] for x in signed]),
                  "signed_bold": signed,
                  "diffs": diffs, "readout": cite_readout(diffs), "gates": gates,
                  "shape": shape_of(slip.faces), "stake": pre["stake"], "p": pre["p"],
                  "main_label": main.get("label"), "errors": errors}


def _walked(record: dict) -> str:
    from nutmeg.decision.bj_time import parse_bj

    at = parse_bj(record.get("at"))
    return (f"本期桥已走过（{at.strftime('%H:%M') if at else '时刻不明'}），"
            "再想改就照抄 §2 主形")


def register_issue_routes(app: FastAPI, templates) -> None:
    @app.get("/issue/{issue}")
    def issue_page(request: Request, issue: str):
        return templates.TemplateResponse(request, "decision/issue.html",
                                          {"title": f"期 {_check_issue(issue)}", "issue": issue})

    @app.get("/api/issue/{issue}")
    def issue_api(issue: str) -> dict:
        return issue_payload(app.state.data_dir, _check_issue(issue), today=_date.today())

    @app.post("/api/precheck")
    def precheck_api(payload: dict = Body(...)) -> Any:  # noqa: B008
        """点格即审：与 CLI `betslip preview` 同一份 precheck。默认不留预审痕——每次点格都写
        会把截止播报的「审过未登记」刷屏；「审这张」/登记前那一次传 `log: true`。"""
        from nutmeg.decision.betslip import BetslipError, format_faces_row
        from nutmeg.decision.choice_ledger import shape_of
        from nutmeg.decision.precheck import build_slip, precheck

        data_dir = app.state.data_dir
        try:
            channel = str(payload.get("channel") or "renjiu")
            faces = _picked(payload.get("faces"))
            row = format_faces_row(faces) if channel != "jczq" and faces else None
            legs = payload.get("legs") if channel == "jczq" else None
            combo = payload.get("combo") or (len(legs) if legs else None)
            slip = build_slip(slip_id="preview", channel=channel,
                              placed_at=str(payload.get("placed_at") or _date.today()),
                              faces=row, legs=legs, combo=str(combo) if combo else None,
                              multiplier=int(payload.get("multiplier") or 1),
                              issue=str(payload.get("issue") or ""), data_dir=data_dir)
            out = precheck(slip, data_dir, log=bool(payload.get("log")))
            out.pop("diagnosis", None)
            gates: list[dict] = []
            if channel == "jczq":
                out["mode"] = out["shape"] = _parlay(slip.combo_sizes, len(slip.legs))
            else:
                gates = _zucai_gates(slip)
                out["mode"] = _zucai_mode(channel, len(slip.faces))
                out["shape"] = shape_of(slip.faces)
            return {"ok": True, **out, "faces_row": row, "gates": gates}
        except (BetslipError, KeyError, ValueError) as error:
            return {"ok": False, "error": _error_text(error)}

    @app.post("/api/bridge/{issue}/preview")
    def bridge_preview_api(issue: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """桥上每改一格就对照一次：五条自检 + 差异格 + 读数。只读——不留预审痕、不登记。"""
        try:
            _, view = bridge_view(app.state.data_dir, _check_issue(issue), payload)
        except (KeyError, ValueError) as error:   # BetslipError 是 ValueError
            return {"ok": False, "error": _error_text(error)}
        return {"ok": True, **view}

    @app.post("/action/bridge")
    def bridge_action(payload: dict = Body(...)) -> Any:  # noqa: B008
        """定稿：登记桥后票 `<期>-B1`（试玩），成功后才写桥记录。只走一次。
        等价命令：`betslip preview-set --plan` + `betslip register --slip-id <期>-B1 --trial`。
        `signed_bold`（场号列表）＝桥上签的博胆：只认票内的单，记录里落成 [{no, face}]。"""
        from nutmeg.decision.bridge import append_bridge, bridge_record
        from nutmeg.decision.precheck import register_reviewed

        data_dir = app.state.data_dir
        issue = _check_issue(str(payload.get("issue") or ""))
        if (old := bridge_record(data_dir, issue)) is not None:
            return {"ok": False, "error": _walked(old)}
        try:
            # 偏离理由不在封闭枚举里时 precheck 的诊断抛 ValueError——登记之前就挡回
            slip, view = bridge_view(data_dir, issue, payload, slip_id=f"{issue}-B1",
                                     deviation=str(payload.get("deviation") or ""),
                                     prediction=str(payload.get("prediction") or ""))
            done = register_reviewed(slip, data_dir)
            whys = {str(k): str(v) for k, v in (payload.get("whys") or {}).items() if v}
            checks = [{**c, "why": whys[str(c["id"])]} if str(c["id"]) in whys else c
                      for c in view["checks"]]
            append_bridge(data_dir, issue, {
                "slip_id": slip.slip_id, "channel": slip.channel,
                "draft0": _picked(payload.get("draft0")), "faces": slip.faces,
                "main_label": view["main_label"], "diffs": view["diffs"],
                "readout": view["readout"], "checks": checks, "signed_bold": view["signed_bold"],
                "deviation": slip.deviation, "prediction": slip.prediction})
        except (KeyError, ValueError) as error:
            return {"ok": False, "error": _error_text(error)}
        return {"ok": True, "at": bridge_record(data_dir, issue)["at"],
                "summary": done["summary"], "lines": done["lines"], "readout": view["readout"]}

    @app.post("/api/issue/{issue}/slip500")
    def slip500_api(issue: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """抄录卡：14 格（场号 · 简称 · 面）+ 位置式 / 点名式两行 + 注数金额。只算不写——
        注数金额就是登记时那张票的 `notes / stake_yuan`，与 precheck 同源。"""
        from nutmeg.decision.betslip import format_faces_row

        data_dir = app.state.data_dir
        _check_issue(issue)
        try:
            slip = _sale_ticket(data_dir, issue, payload, slip_id="preview")
            row = format_faces_row(slip.faces)
            notes, stake = slip.notes, slip.stake_yuan
        except (KeyError, ValueError) as error:   # BetslipError 是 ValueError
            return {"ok": False, "error": _error_text(error)}
        names = _names(data_dir, issue, _matrices(data_dir, issue, []))
        cells = [{"no": no, "name": names[no], "token": token}
                 for no, token in zip(names, row.split(), strict=True)]
        named = " ".join(f"{no}·{f}" for no, f in sorted(slip.faces.items(),
                                                          key=lambda kv: int(kv[0])))
        return {"ok": True, "faces_row": row, "named": named, "cells": cells,
                "notes": notes, "stake": stake}

    @app.post("/action/issue/{issue}/register")
    def register_action(issue: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """「我已在 500 下单」→ 登记实票 `<期>-T<n>`（实购）。等价命令：
        `betslip register --slip-id <期>-T<n> --faces … --multiplier … --scheme-no …`。
        偏离理由与预测都没写、本期走过桥 → 沿用桥记录的（同一判断的延续）。否决只记码不拦登记。"""
        from nutmeg.decision.betslip import format_faces_row, load_slips, next_slip_id
        from nutmeg.decision.bridge import bridge_ledger, bridge_record
        from nutmeg.decision.precheck import register_reviewed

        data_dir = app.state.data_dir
        _check_issue(issue)
        deviation = str(payload.get("deviation") or "").strip()
        prediction = str(payload.get("prediction") or "").strip()
        record = bridge_record(data_dir, issue)
        if record is not None and not deviation and not prediction:
            deviation = str(record.get("deviation") or "")
            prediction = str(record.get("prediction") or "")
        try:
            slip = _sale_ticket(data_dir, issue, payload, slip_id=next_slip_id(data_dir, issue),
                                deviation=deviation, prediction=prediction,
                                scheme_no=str(payload.get("scheme_no") or "").strip())
            done = register_reviewed(slip, data_dir)
        except (KeyError, ValueError) as error:   # 偏离理由不在封闭枚举里也在登记之前挡回
            return {"ok": False, "error": _error_text(error)}
        saved = next(s for s in load_slips(data_dir, issue=issue) if s.slip_id == slip.slip_id)
        review = saved.diagnosis.get("review") or {}
        changed = None
        if record is not None:   # 跨渠道（胜负彩对任九 B1）不比，bridge_ledger 不出这张 → null
            changed = next((r["changed"] for r in bridge_ledger(data_dir, issue)["real"]
                            if r["slip_id"] == saved.slip_id), None)
        return {"ok": True, "slip_id": saved.slip_id, "summary": done["summary"],
                "lines": done["lines"], "faces_row": format_faces_row(saved.faces),
                "notes": saved.notes, "stake": saved.stake_yuan, "multiplier": saved.multiplier,
                "codes": list(review.get("codes") or []), "vetoed": bool(review.get("vetoed")),
                "after_kickoff": done["after_kickoff"], "brake_line": done["brake_line"],
                "b1_changed": changed}
