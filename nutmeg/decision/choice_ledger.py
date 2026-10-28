"""选择账（2026-10-26 迭代设计 Tier 4 #16）：每期三列同钱账——Jun 实票 / 机器默认 / 退役形。

人性博弈定案（2026-10-06）写的「偏离付代价」至今只在复盘散文里；这里把 26136 起每期按**同钱口径**
摆成三列，攒到 20 期（≈2026-11-10）再读，不据单期学面。只读：登记簿、记分牌 `tickets`、
`<期>-draft.json`、`<期>-packet.md`、官方奖金缓存；不写任何落盘、不估任何数。

- Jun 实票：`betslip` purchased 的任九/胜负彩票；派奖取记分牌 `tickets[期].slips`（`retro encode`
  已按官方单注奖金结过），未派奖＝待。
- 机器默认：`<期>-draft.json` 的「初稿」任九候选（gym `zucai_draft` 策略回放的是同一处方点；
  这里直接读当期落盘，避免 legs-base 事后改动）；分析包写「机器默认空仓」的期＝0 投入 0 净值。
- 退役形：丢光 C 档形。10-25 起 draft.json 带 `drop_c` 候选（落盘）；更早的期用 `drop_c_reference`
  从当期 legs-base 重建（只用赛前 belief，不用赛果），标「重建」。
- 同钱：按 Jun 当期实际投入等额买（倍数＝投入 // 票价，不足一注按一注）；Jun 空仓的期按 1 倍。
- 派奖：`gym.payout.settle_zucai` × 官方奖金缓存（与 gym 同一推导）；官方未出＝待。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.account import _is_pending, _settled_rows, _slip_stake
from nutmeg.decision.betslip import BetSlip, load_slips
from nutmeg.decision.files import read_json

ZUCAI_CHANNELS = ("renjiu", "shengfucai")
FLAT_MARKERS = ("机器默认空仓", "默认空仓")
DRAFT_LABEL = "初稿"


def shape_of(faces: dict[str, str]) -> str:
    n = {1: 0, 2: 0, 3: 0}
    for f in faces.values():
        n[len(str(f))] = n.get(len(str(f)), 0) + 1
    parts = [f"{n[1]}单" if n[1] else "", f"{n[2]}双" if n[2] else "", f"{n[3]}包" if n[3] else ""]
    return "".join(p for p in parts if p) or "—"


def same_money_multiplier(jun_stake: float, form_stake: float) -> int:
    """同钱倍数：Jun 投入 // 票价，不足一注按一注；Jun 空仓（0）也按 1 倍给参考。"""
    if form_stake <= 0:
        return 1
    return max(1, int(jun_stake // form_stake))


def jun_column(data_dir: Path, issue: str) -> dict:
    settled = _settled_rows(Path(data_dir))
    slips = [s for s in load_slips(data_dir, issue=issue)
             if s.purchased and s.channel in ZUCAI_CHANNELS]
    col = {"n": len(slips), "stake": 0.0, "payout": 0.0, "pending": 0, "hits": 0,
           "p_sum": 0.0, "p_missing": 0, "ids": []}
    for s in slips:
        row = settled.get(s.slip_id)
        col["stake"] += _slip_stake(s, row)
        col["ids"].append(s.slip_id)
        p = s.hit_probability
        if p is None:
            col["p_missing"] += 1
        else:
            col["p_sum"] += p
        if _is_pending(row):
            col["pending"] += 1
        else:
            col["payout"] += float(row["payout"])
            col["hits"] += int(float(row["payout"]) > 0)
    col["net"] = None if col["pending"] else round(col["payout"] - col["stake"], 2)
    return col


def _draft_candidates(data_dir: Path, issue: str) -> list[dict]:
    doc = read_json(Path(data_dir) / "zucai" / f"{issue}-draft.json", {}) or {}
    return [c for c in doc.get("candidates") or [] if c.get("faces")]


def machine_is_flat(data_dir: Path, issue: str) -> bool:
    """分析包 §0/§2 写了「机器默认空仓」的期。只认文本事实，不推断。"""
    path = Path(data_dir) / "zucai" / f"{issue}-packet.md"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return any(m in text for m in FLAT_MARKERS)


def machine_form(data_dir: Path, issue: str) -> dict | None:
    """当期落盘的「初稿」任九候选 → {faces, stake_yuan, p_all, source}；没有 → None。"""
    for c in _draft_candidates(data_dir, issue):
        if c.get("label") == DRAFT_LABEL and c.get("channel") == "renjiu":
            return {"faces": {str(k): str(v) for k, v in c["faces"].items()},
                    "stake_yuan": float(c["stake_yuan"]), "p_all": c.get("p_all"),
                    "source": "draft.json"}
    return None


def drop_c_form(data_dir: Path, issue: str, *, cap_yuan: int = 800) -> dict | None:
    """丢光 C 档形：优先 draft.json 的 drop_c 候选（落盘）；否则从 legs-base 重建（标 重建）。"""
    for c in _draft_candidates(data_dir, issue):
        if c.get("rule") == "drop_c" and c.get("channel") == "renjiu":
            return {"faces": {str(k): str(v) for k, v in c["faces"].items()},
                    "stake_yuan": float(c["stake_yuan"]), "p_all": c.get("p_all"),
                    "source": "draft.json"}
    from nutmeg.decision.zucai_draft import drop_c_reference, load_board

    try:
        legs = load_board(Path(data_dir), issue)
    except (FileNotFoundError, ValueError, KeyError):
        return None
    ref = drop_c_reference(legs, channel="renjiu", cap_yuan=cap_yuan)
    if not ref:
        return None
    return {"faces": ref["faces"], "stake_yuan": float(ref["stake_yuan"]),
            "p_all": ref.get("p_all"), "source": "重建"}


def settle_form(form: dict | None, issue_obj, *, jun_stake: float) -> dict:
    """同钱口径结一张形：{shape, stake, p, payout, net, k, source}；缺奖金/赛果 → payout None。"""
    if form is None:
        return {"shape": None}
    from nutmeg.gym.payout import settle_zucai

    k = same_money_multiplier(jun_stake, form["stake_yuan"])
    slip = BetSlip(slip_id="choice", channel="renjiu", placed_at="", legs=[], multiplier=k,
                   issue=str(getattr(issue_obj, "issue", "")), faces=form["faces"])
    s = settle_zucai(slip, issue_obj) if issue_obj is not None else {"stake": slip.stake_yuan,
                                                                        "payout": None}
    payout = s.get("payout")
    stake = s.get("stake") or slip.stake_yuan
    return {"shape": shape_of(form["faces"]), "stake": stake, "k": k, "p": form.get("p_all"),
            "payout": payout, "net": None if payout is None else round(payout - stake, 2),
            "hits": s.get("first_notes"), "source": form.get("source")}


def issue_row(issue: str, *, jun: dict, machine: dict, drop_c: dict, flat: bool) -> dict:
    if flat and machine.get("shape") is not None:
        machine = {**machine, "flat": True, "form_stake": machine["stake"], "stake": 0,
                   "net": 0.0, "payout": 0.0, "hits": 0}
    return {"issue": issue, "jun": jun, "machine": machine, "drop_c": drop_c}


def build_choices(data_dir: Path, *, start: str, end: str | None = None) -> dict:
    from nutmeg.gym.board import load_zucai_issue

    data_dir = Path(data_dir)
    # 以 issue.json 为准（gym 的 list_issues 只列有官方奖金的期，26150 这种待开奖的期会漏）
    issues = sorted(p.name.split("-")[0] for p in (data_dir / "zucai").glob("*-issue.json")
                    if p.name.split("-")[0].isdigit())
    issues = [i for i in issues if i >= start and (end is None or i <= end)]
    rows = []
    for issue in issues:
        try:
            zi = load_zucai_issue(data_dir, issue)
        except (FileNotFoundError, ValueError, KeyError):
            zi = None
        jun = jun_column(data_dir, issue)
        rows.append(issue_row(
            issue, jun=jun,
            machine=settle_form(machine_form(data_dir, issue), zi, jun_stake=jun["stake"]),
            drop_c=settle_form(drop_c_form(data_dir, issue), zi, jun_stake=jun["stake"]),
            flat=machine_is_flat(data_dir, issue)))
    return {"start": start, "end": end, "rows": rows}


def _money(v) -> str:
    return "待" if v is None else f"{v:+,.0f}"


def _pct(p) -> str:
    return "—" if p is None else f"{p * 100:.1f}%"


def _form_cells(col: dict) -> str:
    if col.get("shape") is None:
        return "无 | | | | "
    if col.get("flat"):
        return (f"空仓（{col['shape']} ¥{col['form_stake']:,.0f}×0） | 0 | "
                f"{_pct(col.get('p'))} | — | 0")
    hits = "待" if col.get("payout") is None else str(col.get("hits") or 0)
    src = "" if col.get("source") == "draft.json" else f"·{col.get('source')}"
    return (f"{col['shape']}{src} ×{col['k']} | {col['stake']:,.0f} | {_pct(col.get('p'))} | "
            f"{hits} | {_money(col.get('net'))}")


def render_choices(report: dict) -> str:
    rows = report["rows"]
    lines = [f"# 选择账 · {report['start']}–{report['end'] or rows[-1]['issue'] if rows else ''}"
             "（同钱三列：Jun 实票 / 机器默认 / 退役形·丢光 C 档）", "",
             "| 期 | Jun 张/投入/P 和/中/净 | 机器默认 形 | 投入 | P | 中 | 净 "
             "| 退役形 形 | 投入 | P | 中 | 净 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    tot = {"jun_stake": 0.0, "jun_net": 0.0, "jun_p": 0.0, "jun_hits": 0, "jun_pending": 0,
           "m_stake": 0.0, "m_net": 0.0, "m_p": 0.0, "m_hits": 0, "m_n": 0,
           "d_stake": 0.0, "d_net": 0.0, "d_p": 0.0, "d_hits": 0, "d_n": 0}
    notes: list[str] = []
    for r in rows:
        j, m, d = r["jun"], r["machine"], r["drop_c"]
        if j["n"] == 0:
            jun_cell = "空仓"
        else:
            p_sum = f"{j['p_sum']:.2f}" + (f"（{j['p_missing']} 张无 P）" if j["p_missing"] else "")
            hits = "待" if j["pending"] else str(j["hits"])
            jun_cell = (f"{j['n']} 张 ¥{j['stake']:,.0f} / P {p_sum} / 中 {hits} / "
                        f"{_money(j['net'])}")
        lines.append(f"| {r['issue']} | {jun_cell} | {_form_cells(m)} | {_form_cells(d)} |")
        tot["jun_stake"] += j["stake"]
        tot["jun_p"] += j["p_sum"]
        tot["jun_hits"] += j["hits"]
        if j["net"] is None and j["n"]:
            tot["jun_pending"] += 1
        else:
            tot["jun_net"] += j["net"] or 0.0
        for key, col in (("m", m), ("d", d)):
            if col.get("shape") is None or col.get("flat"):
                if col.get("shape") is None:
                    who = "机器默认" if key == "m" else "退役形"
                    notes.append(f"{r['issue']} {who}：无落盘/无法重建")
                continue
            tot[f"{key}_n"] += 1
            tot[f"{key}_stake"] += col["stake"]
            tot[f"{key}_p"] += col.get("p") or 0.0
            if col.get("net") is not None:
                tot[f"{key}_net"] += col["net"]
                tot[f"{key}_hits"] += col.get("hits") or 0
    pend = f"（{tot['jun_pending']} 期待结未计）" if tot["jun_pending"] else ""
    lines += ["",
              f"**合计** Jun 投入 ¥{tot['jun_stake']:,.0f}、P 之和 {tot['jun_p']:.2f}、中 "
              f"{tot['jun_hits']} 张、净 {tot['jun_net']:+,.0f}{pend}"
              f"｜机器默认 {tot['m_n']} 期出票 投入 ¥{tot['m_stake']:,.0f}、"
              f"P 之和 {tot['m_p']:.2f}、中 {tot['m_hits']} 注、净 {tot['m_net']:+,.0f}"
              f"｜退役形 {tot['d_n']} 期 投入 ¥{tot['d_stake']:,.0f}、"
              f"P 之和 {tot['d_p']:.2f}、中 {tot['d_hits']} 注、净 {tot['d_net']:+,.0f}",
              "",
              "口径：Jun 列＝登记簿实购任九/胜负彩 × 记分牌派奖（官方单注奖金）；"
              "机器默认＝当期 draft.json「初稿」任九候选，分析包写「机器默认空仓」的期记 0；"
              "退役形＝丢光 C 档形（draft.json drop_c 候选，没有的期从 legs-base 赛前 belief "
              "重建，标「重建」）；形列按 Jun 当期投入等额买（×k 倍，不足一注按一注，"
              "Jun 空仓期 ×1 作参考）；净值待官方奖金的期标「待」不计入合计。"]
    if notes:
        lines += ["", "算不出的格：" + "；".join(notes)]
    return "\n".join(lines)
