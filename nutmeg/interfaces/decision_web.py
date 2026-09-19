"""Workshop UI — 决策本体判读工作台(spec 2026-07-07-workshop-ui-design.md)。

独立 FastAPI 应用,直接读 DecisionStore 九对象。判断永不在此:界面只渲染
agent 判断(workbench 事件)+ 记录人裁决。两个 typed action(Task 4)复用
ingest_reads/compose_tickets 的既有校验,零旁门。仿 client_web.py 模式。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.decision.ontology import MarketSnapshot, Match
from nutmeg.decision.store import DecisionStore
from nutmeg.decision.workbench import read_events


def _day_state(store: DecisionStore, output_dir, date: str,
               kernel_state=None) -> dict[str, Any]:
    """当日状态。给了 ``kernel_state``（内核读侧，见 decision_web_kernel）时以内核为唯一权威：
    matches / snapshots / reads 全部来自内核，文件事件（追问线程等）与内核合成的议程项合并。
    没给则走旧 DecisionStore 路径，一字不变。**不双写、不混读**——M5 禁无声双权威。"""
    if kernel_state is not None:
        kernel = kernel_state(date)
        return {
            "date": date,
            "matches": kernel["matches"],
            "snapshots": kernel["snapshots"],
            "reads": kernel["reads"],
            "events": read_events(output_dir, date) + kernel["events"],
        }
    prefix = f"M-{date}-"
    matches = [m.to_dict() for m in store.load(Match)
               if m.match_id.startswith(prefix)]
    snaps = [s.to_dict() for s in store.load(MarketSnapshot)
             if s.match_id.startswith(prefix) and s.kind == "read_time"]
    return {
        "date": date,
        "matches": matches,
        "snapshots": snaps,
        "events": read_events(output_dir, date),
    }


def _factor_cls():
    from nutmeg.decision.ontology import Factor
    return Factor


def self_daily(output_dir, date: str) -> Path:
    return Path(output_dir) / "daily" / date


def create_decision_app(*, store: DecisionStore, output_dir, kernel_state=None,
                        zucai_dir=None, sop_invoke=None, observe_repo=None) -> FastAPI:
    app = FastAPI(title="Nutmeg 判读工作台")
    web_root = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    # 静态资源带 mtime 版本号：2026-09-18 加 renderSlip 后浏览器仍跑旧 app.js，右栏空着——
    # 硬刷新才出来。没有版本号的 <script src> 等于让用户替我们清缓存。
    _assets = [
        web_root / "static" / "decision" / name
        for name in ("app.js", "observe.js", "observe.css")
    ]
    _mtimes = [asset.stat().st_mtime for asset in _assets if asset.exists()]
    templates.env.globals["asset_v"] = str(int(max(_mtimes))) if _mtimes else "0"
    app.state.store = store
    app.state.output_dir = Path(output_dir)
    # 足彩物料目录：默认与 betslips.jsonl 同级的 .nutmeg-data/zucai（见 decision-web CLI）。
    app.state.zucai_dir = Path(zucai_dir) if zucai_dir else Path(output_dir).parent / "zucai"

    @app.get("/api/workbench")
    def workbench_api(date: str) -> dict:
        return _day_state(store, output_dir, date, kernel_state)

    @app.get("/")
    def workbench_page(request: Request, date: str = "", issue: str = ""):
        from datetime import date as _d
        date = date or _d.today().isoformat()
        return templates.TemplateResponse(
            request, "decision/workbench.html",
            {"title": "判读工作台",
             "state": _day_state(store, output_dir, date, kernel_state),
             "issue": issue})

    from datetime import date as _date

    from fastapi import Body
    from fastapi.responses import JSONResponse

    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.workbench import distill_note, record_decision

    def _today() -> str:
        return _date.today().isoformat()

    def _date_of(match_id: str) -> str:
        # M-<date>-... → date(供 record_decision 归日)
        parts = match_id.split("-")
        return "-".join(parts[1:4]) if len(parts) >= 4 else _today()

    @app.post("/action/approve-read")
    def approve_read(payload: dict = Body(...)) -> Any:  # noqa: B008
        read = dict(payload["read"])
        obj_id = payload.get("obj_id", read.get("read_id", ""))
        date = _date_of(read.get("match_id", ""))
        # §3.5:把该 obj 的追问往来蒸馏进 note(不进 store);判断不在此
        note = distill_note(output_dir, date, obj_id=obj_id)
        if note:
            read["note"] = (read.get("note", "") + " ⟨" + note + "⟩").strip()
        factors = store.load(_factor_cls()) or load_seed_factors()
        errors = ingest_reads([read], store=store, factors=factors)  # 同一校验闸
        if errors:
            record_decision(output_dir, date, action="approve_read",
                            obj_id=obj_id, result="拒绝: " + "; ".join(errors))
            return JSONResponse({"ok": False, "errors": errors}, status_code=400)
        record_decision(output_dir, date, action="approve_read",
                        obj_id=obj_id, result=f"{read['read_id']} 入库")
        return {"ok": True, "read_id": read["read_id"]}

    @app.post("/action/reject-read")
    def reject_read(payload: dict = Body(...)) -> Any:  # noqa: B008
        obj_id = payload.get("obj_id", "")
        date = payload.get("date", _today())
        record_decision(output_dir, date, action="reject_read", obj_id=obj_id,
                        result=payload.get("reason", ""))
        return {"ok": True}

    @app.post("/action/confirm-legs")
    def confirm_legs(payload: dict = Body(...)) -> Any:  # noqa: B008
        import json
        date = payload.get("date", _today())
        legs = payload["legs"]
        legs_file = self_daily(output_dir, date) / "legs.json"
        legs_file.parent.mkdir(parents=True, exist_ok=True)
        if legs_file.exists():        # 写前留 .bak(spec §5 幂等)
            legs_file.with_suffix(".json.bak").write_text(
                legs_file.read_text(encoding="utf-8"), encoding="utf-8")
        legs_file.write_text(json.dumps(legs, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        record_decision(output_dir, date, action="confirm_legs",
                        obj_id="legs", result=f"{len(legs)} 腿 → legs.json")
        return {"ok": True, "legs": len(legs)}

    from nutmeg.decision.workbench import append_user_message, read_events

    @app.post("/thread")
    def thread_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        """§3.5:浏览器追问 → user_message 事件(obj_id 锚定)。终端 agent 监视
        文件后回应(写 agent_reply/read_draft),浏览器经 /events 拉回。"""
        date = payload.get("date", _today())
        append_user_message(output_dir, date, obj_id=payload["obj_id"],
                            text=payload["text"], at=payload.get("at", ""))
        return {"ok": True}

    # ── 人写事件（阶段三）：手记与被考虑过的票面 ───────────────────────
    # 出生事故 2026-09-18 的 26129:SFC-B→C→D→E 四轮票面迭代与否决理由
    # 全部只存在于聊天窗口,仓库里只剩终版文件——第二天在 app 里什么都看不到。
    @app.post("/action/note")
    def note_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.workbench import append_note

        seq = append_note(output_dir, str(payload["date"]),
                          obj_id=str(payload.get("obj_id") or "day"),
                          text=str(payload.get("text") or ""))
        return {"ok": True, "seq": seq}

    @app.post("/action/candidate")
    def candidate_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.workbench import append_candidate

        seq = append_candidate(output_dir, str(payload["date"]),
                               obj_id=str(payload.get("obj_id") or "ticket"),
                               version=str(payload.get("version") or ""),
                               faces=dict(payload.get("faces") or {}),
                               notes=int(payload.get("notes") or 0),
                               stake_yuan=int(payload.get("stake_yuan") or 0),
                               p_all=payload.get("p_all"),
                               verdict=str(payload.get("verdict") or "considered"),
                               reason=str(payload.get("reason") or ""),
                               parent_version=(str(payload["parent_version"])
                                               if payload.get("parent_version") else None))
        return {"ok": True, "seq": seq}

    # ── SOP 任务栏（阶段一）：同一条命令，从页面按 ──────────────────────
    @app.get("/api/sop-steps")
    def sop_steps(issue: str, date: str) -> dict:
        from nutmeg.decision.sop_tasks import STEPS, SopParams

        p = SopParams(issue=issue, date=date, zucai_dir=app.state.zucai_dir,
                      output_dir=Path(output_dir), legs_file=None)
        return {"issue": issue, "date": date, "steps": [
            {"step_id": s.step_id, "label": s.label, "needs_legs": s.needs_legs,
             # 没声明产物的步骤（B4b 只打 stdout）不判定完成，不是「未完成」
             "done": (all(a.exists() for a in s.artifacts(p))
                      if s.artifacts(p) else None)}
            for s in STEPS]}

    @app.post("/action/run-task")
    def run_task(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.sop_tasks import SopParams, cli_invoke, run_step

        legs = payload.get("legs_file")
        p = SopParams(issue=str(payload["issue"]), date=str(payload["date"]),
                      zucai_dir=app.state.zucai_dir, output_dir=Path(output_dir),
                      legs_file=Path(legs) if legs else None)
        try:
            return run_step(str(payload.get("step_id")), p,
                            invoke=sop_invoke or cli_invoke)
        except KeyError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

    @app.get("/events")
    def events(date: str, since: int = 0) -> dict:
        """轮询式事件拉取(SSE 的 HTTP 后备;前端 app.js 用 EventSource 或轮询)。
        返回 since 之后的新事件与新游标。"""
        evs = read_events(output_dir, date, since=since)
        cursor = evs[-1]["seq"] if evs else since
        return {"events": evs, "cursor": cursor}

    # ── RSI 观察台：只读 API，每块数据各自降级 ─────────────────────────
    from nutmeg.decision.observe_views import day_view, experiment_card, wind_for_day

    def _safe(fn, default, errors: list[str]):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- 观察台不能因单块缺失而整页失败
            errors.append(str(exc))
            return default

    @app.get("/api/observe")
    def api_observe(as_of: str | None = None, day: str | None = None) -> dict:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        now_dt = datetime.now(ZoneInfo("Asia/Shanghai"))
        now = as_of or now_dt.isoformat(timespec="seconds")
        today = day or now_dt.date().isoformat()
        tomorrow = (
            datetime.fromisoformat(today).date() + timedelta(days=1)
        ).isoformat()
        errors: list[str] = []
        rows = (
            _safe(lambda: observe_repo.experiments(as_of=now), [], errors)
            if observe_repo
            else []
        )
        cards = [experiment_card(row, row.get("falsifier") or {}) for row in rows]
        duties_today = (
            _safe(lambda: observe_repo.duties_due(today, now=now), [], errors)
            if observe_repo
            else []
        )
        duties_tomorrow = (
            _safe(lambda: observe_repo.duties_due(tomorrow, now=now), [], errors)
            if observe_repo
            else []
        )
        issue = next(
            (duty.get("issue") for duty in duties_today if duty.get("issue")),
            None,
        )
        wind = _safe(
            lambda: wind_for_day(app.state.zucai_dir, issue), None, errors
        )
        return {
            "as_of": now,
            "experiments": cards,
            "duties_today": duties_today,
            "duties_tomorrow": duties_tomorrow,
            "wind": wind,
            "errors": errors,
        }

    @app.get("/api/observe/exp/{exp_id}")
    def api_observe_exp(exp_id: str, as_of: str | None = None) -> list:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = as_of or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        )
        errors: list[str] = []
        return (
            _safe(
                lambda: observe_repo.experiment_timeline(exp_id, as_of=now),
                [],
                errors,
            )
            if observe_repo
            else []
        )

    @app.get("/api/observe/day/{date}")
    def api_observe_day(date: str) -> dict:
        from dataclasses import asdict, is_dataclass

        errors: list[str] = []
        state = _safe(
            lambda: _day_state(store, output_dir, date, kernel_state),
            {"events": []},
            errors,
        )
        events = state.get("events", [])
        issue = next(
            (
                str(event.get("obj_id", "")).split(":")[-1]
                for event in events
                if event.get("kind") == "candidate"
                and str(event.get("obj_id", "")).startswith("ticket:")
            ),
            None,
        )
        plan = (
            _safe(lambda: observe_repo.latest_capital_plan(issue), None, errors)
            if observe_repo and issue
            else None
        )
        if plan is not None and not isinstance(plan, dict):
            plan = asdict(plan) if is_dataclass(plan) else dict(plan)
        view = day_view(events=events, plan=plan)
        view["errors"] = errors
        return view

    @app.get("/observe")
    def observe_page(request: Request):
        return templates.TemplateResponse(
            request,
            "decision/observe/panorama.html",
            {"title": "RSI 观察台"},
        )

    @app.get("/observe/exp/{exp_id}")
    def observe_exp_page(request: Request, exp_id: str):
        return templates.TemplateResponse(
            request,
            "decision/observe/exp.html",
            {"title": f"实验 {exp_id}", "exp_id": exp_id},
        )

    @app.get("/observe/day/{date}")
    def observe_day_page(request: Request, date: str):
        return templates.TemplateResponse(
            request,
            "decision/observe/day.html",
            {"title": f"过程 {date}", "date": date},
        )

    # ── 过程回放（阶段三 Task 3）：讨论变成事件，事件变成回放 ───────────
    @app.get("/replay")
    def replay_page(request: Request, date: str):
        """当天全过程重放：与工作台同一份合并流（内核判读/实票 + 文件事件）。只读。

        ⚠️只读文件流是不够的——判读与实票活在内核态里，2026-09-18 在真 26129 上
        表现为回放里「实票（无）」。
        """
        events = _day_state(store, output_dir, date, kernel_state)["events"]
        # 内核事件（判读/实票，无 seq）在先，文件事件按 seq 在后＝当天的真实先后；
        # attention 是议程项不是过程，回放里只会变成一行裸 kind。
        events = [e for e in events if e.get("kind") != "attention"]
        events = ([e for e in events if e.get("seq") is None]
                  + sorted((e for e in events if e.get("seq") is not None),
                           key=lambda e: e["seq"]))
        return templates.TemplateResponse(
            request, "decision/replay.html",
            {"title": f"回放 {date}", "date": date, "events": events})

    @app.get("/replay.md")
    def replay_markdown(date: str) -> Any:
        """同一份回放的 Markdown 形态,直接贴进复盘。"""
        from fastapi.responses import PlainTextResponse

        from nutmeg.decision.workbench_export import events_to_markdown

        events = _day_state(store, output_dir, date, kernel_state)["events"]
        return PlainTextResponse(
            events_to_markdown(output_dir, date, events=events),
            media_type="text/markdown")

    @app.get("/objects")
    def objects_page(request: Request):
        from nutmeg.decision.ontology import (
            Factor,
            FactorVerdict,
            League,
            Read,
            Settlement,
            Team,
            Ticket,
        )
        counts = {c.__name__: len(store.load(c)) for c in
                  (Match, MarketSnapshot, Read, Factor, Ticket,
                   Settlement, FactorVerdict, Team, League)}
        return templates.TemplateResponse(
            request, "decision/objects.html", {"title": "对象浏览器", "counts": counts})

    @app.get("/calibration")
    def calibration_page(request: Request):
        from nutmeg.decision.ontology import FactorVerdict
        return templates.TemplateResponse(
            request, "decision/calibration.html",
            {"title": "校准台", "verdicts": [v.to_dict() for v in store.load(FactorVerdict)]})

    @app.get("/ledger")
    def ledger_page(request: Request):
        from nutmeg.decision.ontology import Settlement
        return templates.TemplateResponse(
            request, "decision/ledger.html",
            {"title": "账本", "settlements": [s.to_dict() for s in store.load(Settlement)]})

    # ── 实票登记（「没入账 = 没打」的界面入口） ──────────────────────────
    # 数据根在 output_dir 的上一级:betslips.jsonl 与 scoreboard.json 同级,
    # 因为票面跨渠道(jczq/renjiu/shengfucai),不属于任何单一渠道目录。
    def _data_dir() -> Path:
        return Path(output_dir).parent

    def _betslip_view():
        from nutmeg.decision.betslip import load_slips

        zh = {"jczq": "竞彩", "renjiu": "任九", "shengfucai": "胜负彩"}
        slips = load_slips(_data_dir())
        rows = []
        for s in sorted(slips, key=lambda x: (x.placed_at, x.slip_id), reverse=True):
            row = s.to_dict()
            row["channel_zh"] = zh.get(s.channel, s.channel)
            rows.append(row)
        return {
            "title": "实票登记",
            "slips": rows,
            "total_stake": sum(s.stake_yuan for s in slips if s.purchased),
            "missing_scheme": sum(1 for s in slips if s.purchased and not s.scheme_no),
        }

    @app.get("/betslips")
    def betslips_page(request: Request):
        return templates.TemplateResponse(
            request, "decision/betslips.html", _betslip_view())

    @app.post("/action/register-betslip")
    def register_betslip(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.betslip import (
            BetSlip,
            BetslipError,
            SlipLeg,
            parse_faces_row,
            register_slip,
        )

        try:
            channel = str(payload.get("channel") or "renjiu")
            if channel == "jczq":
                # 竞彩串关有过关方式/让球线/多市场,表单撑不住——显式拒绝而不是半途登记
                # 一张缺腿的票:半张票入账比不入账更糟,复盘时看不出它是残缺的。
                raise BetslipError("竞彩串关请用 CLI：nutmeg betslip register --channel jczq")
            faces = parse_faces_row(str(payload.get("faces") or ""))
            fair_path = Path(output_dir).parent / "zucai" / \
                f"{payload.get('issue')}-prep-revision.json"
            fair: dict = {}
            if fair_path.exists():
                import json as _json
                records = _json.loads(fair_path.read_text("utf-8")).get("records") or {}
                fair = {k: v.get("fair_had") for k, v in records.items()}
            legs = [
                SlipLeg(
                    key=no, market="had",
                    selections=tuple(
                        {"3": "home", "1": "draw", "0": "away"}[c] for c in f),
                    fair=fair.get(no))
                for no, f in sorted(faces.items(), key=lambda kv: int(kv[0]))
            ]
            slip = BetSlip(
                slip_id=str(payload.get("slip_id") or "").strip(), channel=channel,
                placed_at=str(payload.get("placed_at") or "").strip(), legs=legs,
                multiplier=int(payload.get("multiplier") or 1),
                issue=str(payload.get("issue") or "").strip(),
                scheme_no=str(payload.get("scheme_no") or "").strip(),
                purchased=not payload.get("trial"),
                note=str(payload.get("note") or "").strip(), faces=faces)
            return {"ok": True, "summary": register_slip(_data_dir(), slip)}
        except (BetslipError, KeyError, ValueError) as error:
            # 登记被拒要说清是哪一条纪律拒的——静默失败会让人以为票已入账。
            return {"ok": False, "error": str(error)}

    return app
