"""对外只读导出（设计 §10）：只呈现 P1–P4 的产物，不重做分析；守则以代码强制。"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from nutmeg.decision.day_paths import BRIEF, DECISIONS, day_dir
from nutmeg.decision.files import read_json

SCRUB_FORBIDDEN = (".nutmeg-data", "discussion", "timeline", "user-override")
"""裸词 override 会误伤记分牌链名 strict_ruling_vs_override；要拦的是内部行权旗。"""
TEMPLATES = Path(__file__).resolve().parents[1] / "interfaces" / "web" / "templates" / "site"


class PublishError(RuntimeError):
    pass


def _match(m: dict) -> dict:
    read, audit, logic = m.get("read") or {}, m.get("audit") or {}, m.get("logic") or {}
    return {
        "code": m.get("code"), "name": m.get("name"), "competition": m.get("competition"),
        "kickoff": (m.get("kickoff_bj") or "")[11:16],
        "fair": (m.get("market") or {}).get("fair"),
        "drift_pp": (m.get("market") or {}).get("drift_pp"),
        "tier": (m.get("labels") or {}).get("judgment_tier"), "ladder": m.get("ladder"),
        "judge": read.get("judge"), "confidence": read.get("confidence"),
        "research_status": (m.get("research") or {}).get("status"),
        "prospective": (m.get("research") or {}).get("prospective"),
        "logic": logic.get("text") if logic.get("status") == "ok" else None,
        "expressions": {k: f"{v['faces']} {'✗' if v.get('blocking') else '✓'}"
                        for k, v in audit.items() if isinstance(v, dict) and "faces" in v},
    }


def _slips(rows: list[dict]) -> list[dict]:
    """公开页只放票面与审票结论，不放备注（备注可能含内部路径/行权旗）。"""
    return [{k: s.get(k) for k in ("slip_id", "channel", "stake_yuan", "p_all", "ratio",
                                   "vetoed", "purchased", "text")} for s in rows]


def public_view(*, data_dir: Path, root: Path, date: str) -> dict:
    out = day_dir(data_dir, date)
    brief = read_json(out / BRIEF,
                      {"jczq": {"matches": [], "counts": {}}, "zucai": {}, "rsi": None})
    decisions = read_json(out / DECISIONS, [])
    tallies = read_json(root / "experiments" / "scoreboard-tallies.json",
                    {"chains": {}, "coverage": {}})
    z = brief.get("zucai") or {}
    return {
        "date": date, "generated_at": brief.get("generated_at"),
        "counts": brief.get("jczq", {}).get("counts", {}),
        "matches": [_match(m) for m in brief.get("jczq", {}).get("matches", [])],
        "account": (brief.get("account") or {}).get("line"),
        "jczq_brief": brief.get("jczq", {}).get("brief"),
        "jczq_slips": _slips(brief.get("jczq", {}).get("slips") or []),
        "zucai": {"issue": z.get("issue"), "sale_deadline": z.get("sale_deadline"),
                  "wind": (z.get("tiers") or {}).get("wind"),
                  "brief": z.get("brief"),
                  "draft": [{k: d.get(k) for k in ("label", "channel", "stake_yuan", "notes",
                                                   "p_all", "ratio", "vetoed", "faces")}
                            for d in z.get("draft") or []],
                  "slips": _slips(z.get("slips") or []),
                  "plan_status": "已登记实票" if any(
                      s.get("purchased") for s in z.get("slips") or []) else "未登记"},
        "rsi_pending": len((brief.get("rsi") or {}).get("human_actions") or []),
        "decisions": {"open": sum(1 for d in decisions if d.get("status") == "open"),
                      "total": len(decisions)},
        "record": {"chains": [{"name": k, **v} for k, v in (tallies.get("chains") or {}).items()],
                   "coverage": tallies.get("coverage") or {}},
    }


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES)),
                        autoescape=select_autoescape(["html"]))


def publish_day(*, data_dir: Path, root: Path, date: str, out_dir: Path) -> dict:
    view = public_view(data_dir=data_dir, root=root, date=date)
    env = _env()
    days = sorted(p.name for p in (Path(data_dir) / "daily").glob("20*")
                  if (p / BRIEF).exists())[-30:]
    pages = {
        Path(date) / "index.html": env.get_template("day.html").render(v=view),
        Path("index.html"): env.get_template("index.html").render(v=view, days=days),
        Path("method.html"): env.get_template("method.html").render(v=view),
        Path("record.html"): env.get_template("record.html").render(v=view),
    }
    for rel, html in pages.items():
        for bad in SCRUB_FORBIDDEN:
            if bad in html:
                raise PublishError(f"{rel}: 输出含禁用文本 {bad!r}")
        target = Path(out_dir) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    return {"date": date, "pages": len(pages), "matches": len(view["matches"])}
