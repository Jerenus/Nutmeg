"""Workshop UI — 判读工作台(spec 2026-07-07-workshop-ui-design.md)。

独立 FastAPI 应用。判断永不在此:当日场次/快照/已提交 Read 只从内核读侧来
(``decision_web_kernel``),界面只渲染 agent 判断(workbench 事件)+ 人的手记、候选与实票登记。
2026-10-08 第二轮瘦身:旧 DecisionStore 九对象读侧(批准/拒绝 Read、确认 legs、SOP 任务栏、
对象浏览器/校准台/账本)随停写的 v1 JSONL 一起退役。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nutmeg.decision.observe_history import factor_history, rule_changes, run_git, trace_day
from nutmeg.decision.workbench import read_events


def _day_state(output_dir, date: str, kernel_state=None) -> dict[str, Any]:
    """当日状态。内核读侧(见 decision_web_kernel)是唯一权威:matches / snapshots / reads
    全部来自内核,文件事件(追问线程、手记、候选)与内核合成的议程项合并。
    没注入内核读侧(测试、离线)时只有文件事件——**不双写、不混读**,M5 禁无声双权威。"""
    if kernel_state is None:
        return {"date": date, "matches": [], "snapshots": [], "reads": [],
                "events": read_events(output_dir, date)}
    kernel = kernel_state(date)
    return {
        "date": date,
        "matches": kernel["matches"],
        "snapshots": kernel["snapshots"],
        "reads": kernel["reads"],
        "events": read_events(output_dir, date) + kernel["events"],
    }


def create_decision_app(*, output_dir, kernel_state=None,
                        zucai_dir=None, observe_repo=None,
                        data_dir=None, launchctl=None, git=None,
                        web_password: str = "") -> FastAPI:
    app = FastAPI(title="Nutmeg 判读工作台")
    web_root = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=web_root / "templates")
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    # 静态资源带 mtime 版本号：2026-09-18 加 renderSlip 后浏览器仍跑旧 app.js，右栏空着——
    # 硬刷新才出来。没有版本号的 <script src> 等于让用户替我们清缓存。
    _assets = [
        web_root / "static" / "decision" / name
        for name in ("app.js", "observe.js", "observe.css", "day.js", "runs.js", "runs.css",
                     "issue.js", "issue.css", "jczq.js", "jczq.css", "shell.css",
                     "ledger.js", "ledger.css", "lab.js", "lab.css", "corrections.js",
                     "corrections.css", "inbox.js", "inbox.css", "pwa.js")
    ]
    _mtimes = [asset.stat().st_mtime for asset in _assets if asset.exists()]
    templates.env.globals["asset_v"] = str(int(max(_mtimes))) if _mtimes else "0"
    # 手机访问（2026-10-29 Task 9.3）：Tailscale serve 把本机 :8787 发布到自己的 tailnet，页面
    # 有了真域名。所有写入都是同源 fetch；带 Origin 的写请求必须与 Host 同源，别的站点里的表单
    # 打不进账本。没有 Origin 的（CLI、测试、curl）照旧放行。
    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
            if origin.split("://", 1)[-1] != host:
                return JSONResponse({"detail": f"跨站写请求被拒：Origin {origin} ≠ {host}"},
                                    status_code=403)
        return await call_next(request)

    # 对校园网开放时的密码门（2026-10-30）：只有给了密码才装；本机访问不过门。见 decision_web_auth。
    if web_password:
        from nutmeg.interfaces.decision_web_auth import register_password_gate

        register_password_gate(app, web_password)

    @app.get("/manifest.webmanifest")
    def manifest() -> JSONResponse:
        icons = "/static/decision/icons/"
        return JSONResponse({
            "name": "Nutmeg 决策台", "short_name": "Nutmeg", "lang": "zh",
            "start_url": "/day", "scope": "/", "display": "standalone",
            "background_color": "#FFFFFF", "theme_color": "#FFFFFF",
            "icons": [
                {"src": icons + "icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": icons + "icon-512.png", "sizes": "512x512", "type": "image/png"},
                {"src": icons + "icon-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "maskable"},
            ],
        }, media_type="application/manifest+json")

    app.state.output_dir = Path(output_dir)
    # 足彩物料目录：默认与 betslips.jsonl 同级的 .nutmeg-data/zucai（见 decision-web CLI）。
    app.state.zucai_dir = Path(zucai_dir) if zucai_dir else Path(output_dir).parent / "zucai"
    # 当日页（设计 2026-09-22-daily-operator-surface §7）：数据根默认 output_dir 的上一级。
    app.state.data_dir = Path(data_dir) if data_dir else Path(output_dir).parent
    if launchctl is None:
        from nutmeg.decision.ops_status import launchctl_list as launchctl
    app.state.launchctl = launchctl
    # 历史三页（设计 §10）：git log 可注入，测试不碰真仓。
    app.state.git = git or run_git

    @app.get("/api/workbench")
    def workbench_api(date: str) -> dict:
        return _day_state(output_dir, date, kernel_state)

    @app.get("/")
    def workbench_page(request: Request, date: str = ""):
        from datetime import date as _d
        date = date or _d.today().isoformat()
        return templates.TemplateResponse(
            request, "decision/workbench.html",
            {"title": "判读工作台",
             "state": _day_state(output_dir, date, kernel_state)})

    from datetime import date as _date

    from fastapi import Body
    from fastapi.responses import JSONResponse

    def _today() -> str:
        return _date.today().isoformat()

    from nutmeg.decision.workbench import append_user_message

    @app.post("/thread")
    def thread_post(payload: dict = Body(...)) -> Any:  # noqa: B008
        """§3.5:浏览器追问 → user_message 事件(obj_id 锚定)。终端 agent 监视
        文件后回应(写 agent_reply),浏览器经 /events 拉回。"""
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

    @app.get("/events")
    def events(date: str, since: int = 0) -> dict:
        """轮询式事件拉取(SSE 的 HTTP 后备;前端 app.js 用 EventSource 或轮询)。
        返回 since 之后的新事件与新游标。"""
        evs = read_events(output_dir, date, since=since)
        cursor = evs[-1]["seq"] if evs else since
        return {"events": evs, "cursor": cursor}

    # ── RSI 观察台：只读 API，每块数据各自降级 ─────────────────────────
    from nutmeg.decision.observe_views import (
        balance_for_issue,
        day_view,
        experiment_card,
    )

    def _safe(fn, default, errors: list[str]):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- 观察台不能因单块缺失而整页失败
            errors.append(str(exc))
            return default

    @app.get("/api/observe")
    def api_observe(as_of: str | None = None, day: str | None = None) -> dict:
        from datetime import datetime, timedelta

        from nutmeg.decision.bj_time import BJ

        now_dt = datetime.now(BJ)
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
        balance = _safe(
            lambda: balance_for_issue(app.state.zucai_dir, issue), None, errors
        )
        return {
            "as_of": now,
            "experiments": cards,
            "duties_today": duties_today,
            "duties_tomorrow": duties_tomorrow,
            "balance": balance,
            "errors": errors,
        }

    @app.get("/api/observe/exp/{exp_id}")
    def api_observe_exp(exp_id: str, as_of: str | None = None) -> list:
        from datetime import datetime

        from nutmeg.decision.bj_time import BJ

        now = as_of or datetime.now(BJ).isoformat(
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
            lambda: _day_state(output_dir, date, kernel_state),
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
            {"title": "RSI 观察台", "today": _today()},
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

    # ── 当日页：先跑完、再对话 ────────────────────────────────────────────
    # 别名：本工厂里 `day_view` 已绑定 observe_views.day_view（api_observe_day 在请求时闭包读它），
    # 同名再导入会把观察台那条路由也改指到当日页视图。
    from fastapi.responses import RedirectResponse

    from nutmeg.decision.day_session import append_discussion, read_discussion
    from nutmeg.decision.day_view import day_view as day_page_view

    def _day_payload(date: str) -> dict:
        root = Path(__file__).resolve().parents[2]
        return day_page_view(
            data_dir=app.state.data_dir, date=date,
            plists_dir=root / "ops" / "launchd", logs_dir=app.state.data_dir / "logs",
            launchctl_text=app.state.launchctl(), today=_date.today(),
        )

    @app.get("/day")
    def day_root():
        return RedirectResponse(url=f"/day/{_today()}", status_code=307)

    @app.get("/day/{date}")
    def day_page(request: Request, date: str):
        return templates.TemplateResponse(request, "decision/day.html",
                                          {"title": f"当日 {date}", "date": date})

    @app.get("/api/day/{date}")
    def day_api(date: str) -> dict:
        # 第 6 阶段：外壳 / 空仓登记 / 在售期一眼并进来；今天的待人决定按当前文件现算
        from nutmeg.interfaces.decision_web_shell import app_now, today_extras

        payload = _day_payload(date)
        extras = today_extras(app.state.data_dir, date, app_now(app),
                              decisions=payload["decisions"])
        payload["errors"] += extras.pop("errors")
        return payload | extras

    @app.post("/action/day-note")
    def day_note(payload: dict = Body(...)) -> Any:  # noqa: B008
        text = str(payload.get("text") or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)
        date = str(payload.get("date") or _today())
        append_discussion(app.state.data_dir, date, who=str(payload.get("who") or "jun"),
                          text=text, obj=str(payload.get("obj") or ""),
                          at=datetime.now().astimezone().isoformat(timespec="seconds"))
        return {"ok": True, "seq": len(read_discussion(app.state.data_dir, date))}

    # ── 作业进度页：每天一页，定时作业的计划 vs 实到 + 当日产物（只读零写）──────
    import re as _re

    from fastapi import HTTPException

    from nutmeg.decision.day_runs import day_runs

    app.state.runs_plists = Path(__file__).resolve().parents[2] / "ops" / "launchd"
    _PREVIEW_SUFFIXES = {".md", ".json", ".txt", ".log", ".jsonl"}

    def _check_date(date: str) -> str:
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise HTTPException(status_code=404, detail="日期格式应为 YYYY-MM-DD")
        return date

    @app.get("/runs")
    def runs_root(request: Request):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"/runs/{_today()}{query}", status_code=307)

    @app.get("/runs/{date}")
    def runs_page(request: Request, date: str):
        return templates.TemplateResponse(request, "decision/runs.html",
                                          {"title": f"作业进度 {_check_date(date)}",
                                           "date": date})

    @app.get("/verdict/{date}")
    def verdict_page(date: str):
        """当日判决参考页：优先给定时生成的静态页；没有就现场生成一版。"""
        from fastapi.responses import HTMLResponse

        from nutmeg.decision.verdict_page import write_verdict

        path = Path(app.state.data_dir) / "jczq" / "daily" / date / "verdict.html"
        if not path.exists():
            path = write_verdict(day=date, data_dir=Path(app.state.data_dir))
        return HTMLResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/runs/{date}")
    def runs_api(date: str) -> dict:
        return day_runs(data_dir=app.state.data_dir, plists_dir=app.state.runs_plists,
                        day=_check_date(date), now=datetime.now())

    @app.get("/api/runs-file")
    def runs_file(path: str) -> dict:
        """产物预览：只读数据根下的文本产物，不许跳出去。"""
        root = app.state.data_dir.resolve()
        target = (root / path).resolve()
        if root not in target.parents or target.suffix not in _PREVIEW_SUFFIXES:
            raise HTTPException(status_code=403, detail="只能预览数据目录里的文本产物")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")
        raw = target.read_text(encoding="utf-8", errors="replace")
        if target.suffix == ".json":
            try:
                raw = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
            except ValueError:
                pass
        limit = 60_000
        return {"path": path, "text": raw[:limit], "truncated": len(raw) > limit}

    # ── 历史三页（P5 设计 §10）：规则变更 / 因子提案史 / 昨日追溯，只读零写 ──
    _root = Path(__file__).resolve().parents[2]

    @app.get("/api/observe/rules")
    def observe_rules_api() -> list[dict]:
        return rule_changes(_root, git=app.state.git)

    @app.get("/api/observe/factors")
    def observe_factors_api() -> dict:
        return factor_history(_root)

    @app.get("/api/observe/trace/{date}")
    def observe_trace_api(date: str) -> dict:
        return trace_day(app.state.data_dir, date)

    @app.get("/observe/rules")
    def observe_rules_page(request: Request):
        return templates.TemplateResponse(request, "decision/observe/rules.html",
                                          {"title": "规则变更",
                                           "rows": rule_changes(_root, git=app.state.git)})

    @app.get("/observe/factors")
    def observe_factors_page(request: Request):
        return templates.TemplateResponse(request, "decision/observe/factors.html",
                                          {"title": "因子提案史", "hist": factor_history(_root)})

    @app.get("/observe/trace/{date}")
    def observe_trace_page(request: Request, date: str):
        return templates.TemplateResponse(request, "decision/observe/trace.html",
                                          {"title": f"追溯 {date}",
                                           "tr": trace_day(app.state.data_dir, date)})

    # ── 过程回放（阶段三 Task 3）：讨论变成事件，事件变成回放 ───────────
    @app.get("/replay")
    def replay_page(request: Request, date: str):
        """当天全过程重放：与工作台同一份合并流（内核判读/实票 + 文件事件）。只读。

        ⚠️只读文件流是不够的——判读与实票活在内核态里，2026-09-18 在真 26129 上
        表现为回放里「实票（无）」。
        """
        events = _day_state(output_dir, date, kernel_state)["events"]
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

        events = _day_state(output_dir, date, kernel_state)["events"]
        return PlainTextResponse(
            events_to_markdown(output_dir, date, events=events),
            media_type="text/markdown")

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
        from nutmeg.decision.betslip import BetslipError
        from nutmeg.decision.precheck import build_slip, register_reviewed

        try:
            channel = str(payload.get("channel") or "renjiu")
            legs = payload.get("legs")
            if channel == "jczq" and not (isinstance(legs, list) and legs
                                          and all(isinstance(x, dict) for x in legs)):
                # 竞彩串关有过关方式/让球线/多市场,自由文本撑不住——只收竞彩板生成的结构化腿;
                # 半张票入账比不入账更糟,复盘时看不出它是残缺的。
                raise BetslipError("竞彩票请从竞彩板登记：需要逐腿的场次、玩法、选项与赔率，"
                                   "网页表单不收手填的竞彩票面")
            # 与 CLI 同一条流水线（precheck）：足彩 fair 取 legs-base 判断概率，
            # 审票与止损/刹车/日帽码随票入账，偏离理由与赛前预测照收
            slip = build_slip(
                slip_id=str(payload.get("slip_id") or "").strip(), channel=channel,
                placed_at=str(payload.get("placed_at") or "").strip(),
                faces=str(payload.get("faces") or "") or None,
                legs=legs if channel == "jczq" else None,
                combo=(str(payload["combo"]) if payload.get("combo") else None),
                multiplier=int(payload.get("multiplier") or 1),
                issue=str(payload.get("issue") or "").strip(),
                scheme_no=str(payload.get("scheme_no") or "").strip(),
                trial=bool(payload.get("trial")), note=str(payload.get("note") or "").strip(),
                deviation=str(payload.get("deviation") or "").strip(),
                prediction=str(payload.get("prediction") or "").strip(), data_dir=_data_dir())
            return {"ok": True, **register_reviewed(slip, _data_dir())}
        except (BetslipError, KeyError, ValueError) as error:
            # 登记被拒要说清是哪一条纪律拒的——静默失败会让人以为票已入账。
            return {"ok": False, "error": str(error)}

    from nutmeg.interfaces.decision_web_corrections import register_corrections_routes
    from nutmeg.interfaces.decision_web_inbox import register_inbox_routes
    from nutmeg.interfaces.decision_web_issue import register_issue_routes
    from nutmeg.interfaces.decision_web_jczq import register_jczq_routes
    from nutmeg.interfaces.decision_web_lab import register_lab_routes
    from nutmeg.interfaces.decision_web_ledger import register_ledger_routes
    from nutmeg.interfaces.decision_web_shell import register_shell

    register_issue_routes(app, templates)
    register_jczq_routes(app, templates)
    register_shell(app, templates)
    register_ledger_routes(app, templates)
    register_lab_routes(app, templates)
    register_corrections_routes(app, templates)
    register_inbox_routes(app, templates)
    return app
