"""竞彩虚拟规则赛 CLI。只读写 `jczq/arena/`，不碰实票和判断层。"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli

arena_app = _cli.typer.Typer(help="竞彩虚拟规则赛：虚拟单，不进净值")
_cli.app.add_typer(arena_app, name="arena")

_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_DAY = _cli.typer.Option(None, "--day", help="板面日，默认今天（北京时间）")
_WINDOW = _cli.typer.Option("dev", "--window", help="dev | sealed")
_RULE = _cli.typer.Option(None, "--rule", help="规则 JSON")
_RULE_REQ = _cli.typer.Option(..., "--rule", help="规则 JSON")
_SEASON = _cli.typer.Option("S1", "--season")
_REVIEW = _cli.typer.Option(..., "--review", help="评审结论，一句话")
_OUT = _cli.typer.Option(..., "--out", help="开发包目录")
_MONTH = _cli.typer.Option(None, "--month", help="YYYY-MM，默认本月")


def _now() -> datetime:
    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ)


def _plain(odds: dict) -> dict:
    """titan 返回 MarketOdds 数据类，统一成 build_legs 读的字典。"""
    return {code: {market: dataclasses.asdict(item) for market, item in row.items()}
            for code, row in odds.items()}


def _stances(data_dir: Path, day: str) -> dict[str, str]:
    from nutmeg.decision.files import read_json

    doc = read_json(data_dir / "jczq" / "daily" / day / "jczq-legs-base.json", {}) or {}
    return {code: str((leg.get("stance") or {}).get("face"))
            for code, leg in (doc.get("legs") or {}).items()
            if (leg.get("stance") or {}).get("face") is not None}


@arena_app.command("init")
def arena_init(season: str = _SEASON, data_dir: Path = _DATA_DIR) -> None:
    """写入基线和研究席位，已存在的跳过。"""
    from nutmeg.decision.arena.baseline import baseline_rules
    from nutmeg.decision.arena.ledger import add_rule, load_rules

    known = {r["id"] for r in load_rules(data_dir)}
    fresh = [r for r in baseline_rules() if r["id"] not in known]
    for rule in fresh:
        add_rule(data_dir, season, rule)
    _cli.typer.echo(f"新增 {len(fresh)} 条，活跃 {len(load_rules(data_dir))} 条")


@arena_app.command("freeze")
def arena_freeze(day: str | None = _DAY, data_dir: Path = _DATA_DIR) -> None:
    """抓实时体彩价和国际盘，冻结当日虚拟票与地板。失败不补票。"""
    from nutmeg.decision.arena.freeze import freeze_day
    from nutmeg.decision.market_data import fetch_sporttery_value_with_fallback
    from nutmeg.services.jczq_titan007_odds import collect_bold_odds_titan007_live

    now = _now()
    day = day or now.date().isoformat()
    value, source = fetch_sporttery_value_with_fallback()
    odds = _plain(collect_bold_odds_titan007_live(value, run_date=day))
    result = freeze_day(data_dir, day, value, odds, now=now, source=source,
                        stances=_stances(data_dir, day))
    _cli.typer.echo(json.dumps(result, ensure_ascii=False))


@arena_app.command("settle")
def arena_settle(data_dir: Path = _DATA_DIR) -> None:
    from nutmeg.decision.arena.settle import settle_pending

    result = settle_pending(data_dir, _now().isoformat(timespec="seconds"))
    _cli.typer.echo(json.dumps(result, ensure_ascii=False))


@arena_app.command("board")
def arena_board(month: str | None = _MONTH, data_dir: Path = _DATA_DIR) -> None:
    from nutmeg.decision.arena.board import build_board

    _cli.typer.echo(str(build_board(data_dir, month or _now().strftime("%Y-%m"))))


@arena_app.command("backtest")
def arena_backtest(rule: Path | None = _RULE, window: str = _WINDOW,
                   data_dir: Path = _DATA_DIR) -> None:
    """回放一条规则；不给 --rule 就回放全部基线。选手只许用 dev 窗口。"""
    from nutmeg.decision.arena.backtest import DEV, SEALED, history_days, summarize
    from nutmeg.decision.arena.baseline import baseline_rules
    from nutmeg.decision.arena.rules import validate_rule

    rules = [json.loads(rule.read_text("utf-8"))] if rule else baseline_rules()
    days = history_days(data_dir, *{"dev": DEV, "sealed": SEALED}[window])
    for item in rules:
        errors = validate_rule(item)
        if errors:
            _cli.typer.echo(f"不合规：{'；'.join(errors)}")
            raise _cli.typer.Exit(code=1)
        _cli.typer.echo(json.dumps(summarize(item, days), ensure_ascii=False))


@arena_app.command("dev-pack")
def arena_dev_pack(out: Path = _OUT, data_dir: Path = _DATA_DIR) -> None:
    from nutmeg.decision.arena.backtest import dev_pack

    _cli.typer.echo(str(dev_pack(data_dir, out)))


@arena_app.command("admit")
def arena_admit(rule: Path = _RULE_REQ, review: str = _REVIEW,
                season: str = _SEASON, data_dir: Path = _DATA_DIR) -> None:
    """过封存验证的规则入赛。不过就退出 1，不入库。"""
    from nutmeg.decision.arena.backtest import SEALED, check_admission, history_days
    from nutmeg.decision.arena.ledger import add_rule
    from nutmeg.decision.arena.rules import validate_rule

    doc = json.loads(rule.read_text("utf-8"))
    errors = validate_rule(doc)
    if errors:
        _cli.typer.echo(f"不合规：{'；'.join(errors)}")
        raise _cli.typer.Exit(code=1)
    verdict = check_admission(doc, history_days(data_dir, *SEALED))
    _cli.typer.echo(json.dumps(verdict, ensure_ascii=False))
    if not verdict["admitted"]:
        raise _cli.typer.Exit(code=1)
    add_rule(data_dir, season, doc | {"review": review, "sealed": verdict})
