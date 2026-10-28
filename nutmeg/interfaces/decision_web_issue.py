"""期页与竞彩当日板的路由（2026-10-27 产品形态）。只读组装 + 转调 precheck；不产生判断。"""
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
    from nutmeg.decision.counter_matrix import issue_matrices
    from nutmeg.decision.files import read_json
    from nutmeg.decision.lineup_watch import issue_doc, match_names
    from nutmeg.decision.packet_doc import load_packet
    from nutmeg.decision.precheck import brake_line, month_brake
    from nutmeg.decision.review_runner import issue_market

    errors: list[str] = []
    packet = load_packet(data_dir, issue)
    errors += packet["errors"]
    market = issue_market(data_dir, issue)
    try:
        matrices = {m["no"]: m for m in issue_matrices(data_dir, issue)}
    except Exception as exc:  # noqa: BLE001 —— 矩阵缺席要看得见，不能读成「没有证据」
        matrices = {}
        errors.append(f"反证矩阵失败：{exc!r}"[:200])
    draft = read_json(Path(data_dir) / "zucai" / f"{issue}-draft.json", None)
    if draft is None:
        errors.append(f"缺 {issue}-draft.json（judgment draft --write 未跑）")
    doc = issue_doc(data_dir, issue)
    names = {no: f"{t[0]}-{t[1]}" for no, t in match_names(doc).items()} if doc else {}
    # 止损块与 CLI 预审同一份「实质余量」（待结实购票按全损计）
    state = month_brake(data_dir, today.isoformat())
    matches = []
    for i in range(1, 15):
        no = str(i)
        matrix = matrices.get(no)
        matches.append({"no": no, "name": names.get(no) or (matrix or {}).get("name", ""),
                        "fair": market.get(no), "packet": packet["by_no"].get(no),
                        "matrix": matrix})
    return {"issue": issue, "matches": matches, "default": packet["default"],
            "main_shape": packet["main_shape"], "alternatives": packet["alternatives"],
            "signed_bold": packet["signed_bold"], "built_at": packet.get("built_at"),
            "draft_candidates": (draft or {}).get("candidates") or [],
            "brake": {**state, "line": brake_line(data_dir, today.isoformat()),
                      "issue": issue_brake(data_dir, issue)},
            "errors": errors}


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
        from nutmeg.decision.slip_group import death_list, is_coin

        data_dir = app.state.data_dir
        try:
            channel = str(payload.get("channel") or "renjiu")
            faces = {str(k): str(v) for k, v in (payload.get("faces") or {}).items() if v}
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
                fair = {leg.key: leg.fair for leg in slip.legs if leg.fair}
                ticket = {no: f for no, f in slip.faces.items() if no in fair}
                ordered, _ = death_list([ticket], fair, top=5)
                gates = [{"no": no, "face": f, "p": p, "coin": is_coin(fair[no])}
                         for no, f, p in ordered[:5]]
                out["mode"] = _zucai_mode(channel, len(slip.faces))
                out["shape"] = shape_of(slip.faces)
            return {"ok": True, **out, "faces_row": row, "gates": gates}
        except (BetslipError, KeyError, ValueError) as error:
            message = error.args[0] if isinstance(error, KeyError) and error.args else error
            return {"ok": False, "error": _page_error(str(message))}
