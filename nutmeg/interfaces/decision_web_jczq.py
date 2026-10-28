"""竞彩当日板的路由（2026-10-28 产品形态第 5 阶段）。只读组装 + 转调 precheck；不产生判断。

板面＝`gym.board.load_jczq_board`（体彩快照：SP、让球、在售、开球、单关、过关方式）
+ `judgment_brief.jczq_brief`（表态 / 旗 / 损耗 / 关注度 / rubric / 一句话 / 大热），
市场 fair 取 `board_rows.jczq_rows` 的 legs-base 行（唯一读法）。

腿由**服务端**按选择表 `{编号: 面}` 组装：赔率＝板面 SP、fair＝legs-base 市场——页面不传赔率，
也改不了它。票号 `<YYYYMMDD>-J<n>` 由 `betslip.next_jczq_slip_id` 分配。登记是事实：否决只记码。
"""
from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from nutmeg.interfaces.decision_web_forms import error_text, parlay_label, parse_multiplier

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_LEGS = 8                      # 体彩胜平负过关最多 8 场
_CN = {"3": "胜", "1": "平", "0": "负"}
_ORDER = "310"


def _check_day(day: str) -> str:
    try:
        if _DAY.fullmatch(day):
            _date.fromisoformat(day)
            return day
    except ValueError:
        pass
    raise HTTPException(status_code=400, detail="日期须为 YYYY-MM-DD")


def _board(data_dir: Path, day: str, errors: list[str]):
    from nutmeg.gym.board import load_jczq_board

    try:
        return load_jczq_board(data_dir, day)
    except FileNotFoundError:
        errors.append(f"{day} 无体彩快照（jczq/daily/{day}/sporttery_markets.json 未抓）")
    except Exception as exc:  # noqa: BLE001 —— 板面读坏要看得见，不能读成「今天没场」
        errors.append(f"体彩快照读取失败：{exc!r}"[:200])
    return None


def _day_matches(board, day: str) -> list:
    """本板面日的全部场（在售 + 停售/已开/早场补录），次日场不算。"""
    pool = {**board.extra, **board.matches}
    return [pool[c] for c in sorted(pool) if pool[c].business_date == day]


def _kicked(match, now: datetime) -> bool | None:
    from nutmeg.decision.bj_time import aware

    if not match.kickoff_bj:
        return None
    try:
        return aware(match.kickoff_bj) <= now
    except ValueError:
        return None


def _blocked(match, now: datetime) -> str | None:
    """不可选的理由；可选 → None。可选＝在售、开球时刻已知且未到、胜平负三价齐全。"""
    if not match.selling:
        return "已停售"
    if len(match.had) != 3:
        return "胜平负未开售"
    kicked = _kicked(match, now)
    if kicked is None:
        return "开球时刻不明"
    return "已开球" if kicked else None


def _market_fair(data_dir: Path, day: str) -> tuple[list[dict], dict[str, dict]]:
    """legs-base 行（`jczq_rows`，唯一读法）与 {编号: 市场 fair（home/draw/away）}。"""
    from nutmeg.decision.board_rows import jczq_rows

    rows = jczq_rows(data_dir, day)
    return rows, {r["code"]: r["leg"].get("fair") for r in rows if r["leg"].get("fair")}


def _codes(d: dict | None, keys=("home", "draw", "away")) -> dict[str, float] | None:
    if not d:
        return None
    return {code: float(d[k]) for code, k in zip(_ORDER, keys, strict=True) if k in d}


def jczq_payload(data_dir: Path, day: str, *, now: datetime) -> dict:
    from nutmeg.decision.bankroll import status_line
    from nutmeg.decision.judgment_brief import jczq_brief
    from nutmeg.decision.precheck import month_brake

    data_dir = Path(data_dir)
    errors: list[str] = []
    board = _board(data_dir, day, errors)
    legs_rows, fair_by = _market_fair(data_dir, day)
    if board is not None and not legs_rows:
        errors.append(f"缺 jczq/daily/{day}/jczq-legs-base.json（市场 fair / 表态未出）")
    brief_by: dict[str, dict] = {}
    if legs_rows:
        try:
            brief_by = {r["code"]: r for r in jczq_brief(data_dir, day, rows=legs_rows)["rows"]}
        except Exception as exc:  # noqa: BLE001 —— 初判列缺席要看得见
            errors.append(f"初判包失败：{exc!r}"[:200])
    rows = []
    for m in _day_matches(board, day) if board is not None else []:
        b = brief_by.get(m.code) or {}
        sp = dict(m.had) if len(m.had) == 3 else None
        fair = _codes(fair_by.get(m.code))
        ret = ({c: round(fair[c] * sp[c], 3) for c in _ORDER if c in fair}
               if sp and fair else None)
        kicked = _kicked(m, now)
        rows.append({
            "code": m.code, "name": m.name, "league": m.league, "kickoff": m.kickoff_bj,
            "kicked": kicked, "selectable": _blocked(m, now) is None,
            "sp": sp, "fair": fair, "ret": ret,
            "single": m.single_allowed.get("had", False), "hhad": m.hhad,
            "stance": b.get("stance", "—"), "flags": b.get("flags", ""),
            "load": b.get("load", ""), "attention": b.get("attention", ""),
            "rubric": b.get("rubric", "—"), "note": b.get("note", ""), "fav": b.get("fav", ""),
            "kind": b.get("kind", ""),
        })
    state = month_brake(data_dir, day)
    selectable = [r for r in rows if r["selectable"]]
    return {
        "day": day, "rows": rows,
        "allup_had": list((board.allup if board is not None else {}).get("had") or []),
        "brake": {"line": status_line(state), "room": state["room"], "tripped": state["tripped"],
                  "stop_loss": state["stop_loss"], "effective_net": state["effective_net"],
                  "pending": state["pending"]},
        "counts": {"rows": len(rows), "selectable": len(selectable),
                   "kicked": sum(1 for r in rows if r["kicked"]),
                   "singles_open": sum(1 for r in selectable if r["single"]),
                   # 初判包含 legs-base 里的足彩重叠码（z<期>-<场>），计数只算板上的场
                   "researched": sum(1 for r in rows if r["kind"] in ("研究", "改判")),
                   "favs": sum(1 for r in rows if r["fav"])},
        "errors": errors}


def _faces(code: str, raw) -> str:
    text = str(raw or "")
    if not text or any(ch not in _ORDER for ch in text):
        raise ValueError(f"{code} 选项 `{text}` 不合法（只认 3/1/0）")
    return "".join(c for c in _ORDER if c in text)


def build_legs(data_dir: Path, day: str, picks: dict | None, *, now: datetime) -> list[dict]:
    """{编号: 面} → 腿 JSON（`precheck.build_slip` 的 legs）。拒：板上没有 / 不可选 / 面不合法 /
    1 腿而单关未开 / 超 8 腿 / 体彩当日不开 n串1。"""
    from nutmeg.gym.board import FACE_OF

    errors: list[str] = []
    board = _board(Path(data_dir), day, errors)
    if board is None:
        raise ValueError(errors[0])
    picked = {str(k): v for k, v in (picks or {}).items() if v}
    if not picked:
        raise ValueError("还没选腿")
    if len(picked) > MAX_LEGS:
        raise ValueError(f"竞彩过关最多 {MAX_LEGS} 场（已选 {len(picked)} 场）")
    _, fair_by = _market_fair(Path(data_dir), day)
    legs, matches = [], []
    for code in sorted(picked):
        m = board.lookup(code)
        if m is None or m.business_date != day:
            raise ValueError(f"{code} 不在 {day} 板面上")
        if why := _blocked(m, now):
            raise ValueError(f"{code} {m.name} {why}，不能选")
        faces = _faces(code, picked[code])
        matches.append(m)
        legs.append({"key": code, "name": m.name, "market": "had",
                     "selections": [FACE_OF[c] for c in faces],
                     "odds": [m.had[c] for c in faces], "fair": fair_by.get(code)})
    n = len(legs)
    if n == 1 and not matches[0].single_allowed.get("had"):
        raise ValueError(f"{matches[0].code} 胜平负单关未开，至少再选一场过关")
    if n >= 2 and f"{n}x1" not in (board.allup.get("had") or []):
        raise ValueError(f"体彩今天胜平负不开 {n}串1")
    return legs


def _slip(data_dir: Path, day: str, payload: dict, *, now: datetime, slip_id: str,
          deviation: str = "", prediction: str = "", scheme_no: str = ""):
    from nutmeg.decision.precheck import build_slip

    legs = build_legs(data_dir, day, payload.get("picks"), now=now)
    return build_slip(slip_id=slip_id, channel="jczq", placed_at=day, legs=legs,
                      combo=str(len(legs)), multiplier=parse_multiplier(payload.get("multiplier")),
                      scheme_no=scheme_no, trial=False, deviation=deviation,
                      prediction=prediction, data_dir=data_dir)


def _leg_view(slip) -> list[dict]:
    from nutmeg.gym.board import CODE_OF

    return [{"code": leg.key, "name": leg.name,
             "faces": "".join(CODE_OF[s] for s in leg.selections), "odds": list(leg.odds)}
            for leg in slip.legs]


def _max_payout(slip) -> float:
    total = 2.0 * slip.multiplier
    for leg in slip.legs:
        total *= max(leg.odds)
    return round(total, 2)


def slip_text(slip) -> str:
    """500 投注单：逐腿「周三001 大阪钢巴-布里兰 胜平负 胜 @1.54」，
    末行「n串1 · N 注 · M 倍 · ¥X」。"""
    lines = []
    for leg in _leg_view(slip):
        cn = "/".join(_CN[c] for c in leg["faces"])
        odds = "/".join(f"{o:.2f}" for o in leg["odds"])
        lines.append(f"{leg['code']} {leg['name']} 胜平负 {cn} @{odds}")
    lines.append(f"{parlay_label(slip.combo_sizes, len(slip.legs))} · {slip.notes} 注 · "
                 f"{slip.multiplier} 倍 · ¥{slip.stake_yuan:,}")
    return "\n".join(lines)


def register_jczq_routes(app: FastAPI, templates) -> None:
    from nutmeg.decision.bj_time import BJ

    if not hasattr(app.state, "now"):    # 测试 / 沙盒回放可换钟
        app.state.now = lambda: datetime.now(BJ)

    @app.get("/jczq")
    def jczq_today():
        return RedirectResponse(f"/jczq/{app.state.now().date().isoformat()}", status_code=307)

    @app.get("/jczq/{day}")
    def jczq_page(request: Request, day: str):
        return templates.TemplateResponse(request, "decision/jczq.html",
                                          {"title": f"竞彩 {_check_day(day)}", "day": day})

    @app.get("/api/jczq/{day}")
    def jczq_api(day: str) -> dict:
        return jczq_payload(app.state.data_dir, _check_day(day), now=app.state.now())

    @app.post("/api/jczq/{day}/precheck")
    def jczq_precheck(day: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """选择表即审：服务端组腿 → 与 CLI `betslip preview --channel jczq` 同一份 precheck。
        不留预审痕（每点一格都写会把截止播报刷屏）。"""
        from nutmeg.decision.precheck import precheck

        data_dir = app.state.data_dir
        _check_day(day)
        try:
            slip = _slip(data_dir, day, payload, now=app.state.now(), slip_id="preview")
            out = precheck(slip, data_dir, log=False)
        except (KeyError, ValueError) as error:   # BetslipError 是 ValueError
            return {"ok": False, "error": error_text(error)}
        out.pop("diagnosis", None)
        return {"ok": True, **out, "combo": parlay_label(slip.combo_sizes, len(slip.legs)),
                "max_payout": _max_payout(slip), "legs": _leg_view(slip)}

    @app.post("/action/jczq/{day}/register")
    def jczq_register(day: str, payload: dict = Body(...)) -> Any:  # noqa: B008
        """「我已在 500 下单」→ 登记实票 `<YYYYMMDD>-J<n>`（实购）。等价命令：
        `betslip register --channel jczq --slip-id … --legs-file … --combo n --multiplier …`。
        偏离理由不在封闭枚举里在登记之前挡回；否决只记码不拦登记。"""
        from nutmeg.decision.betslip import load_slips, next_jczq_slip_id
        from nutmeg.decision.precheck import register_reviewed

        data_dir = app.state.data_dir
        _check_day(day)
        try:
            slip = _slip(data_dir, day, payload, now=app.state.now(),
                         slip_id=next_jczq_slip_id(data_dir, day),
                         deviation=str(payload.get("deviation") or "").strip(),
                         prediction=str(payload.get("prediction") or "").strip(),
                         scheme_no=str(payload.get("scheme_no") or "").strip())
            done = register_reviewed(slip, data_dir)
        except (KeyError, ValueError) as error:
            return {"ok": False, "error": error_text(error)}
        saved = next(s for s in load_slips(data_dir, channel="jczq") if s.slip_id == slip.slip_id)
        review = saved.diagnosis.get("review") or {}
        return {"ok": True, "slip_id": saved.slip_id, "summary": done["summary"],
                "lines": done["lines"], "notes": saved.notes, "stake": saved.stake_yuan,
                "multiplier": saved.multiplier,
                "codes": list(review.get("codes") or []), "vetoed": bool(review.get("vetoed")),
                "after_kickoff": done["after_kickoff"], "brake_line": done["brake_line"],
                "slip_text": slip_text(saved)}
