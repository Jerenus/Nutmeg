"""传统足彩备料 —— 14:00 定时任务的产出物。

**这份东西只备料,不判读。** 它输出事实(对阵/盘口/去水 fair)与确定性算术
(DC 比分矩阵、进球带、净胜分布、让球三路),以及**纯机械可算**的筛选清单;
旗、共振级、四级动作阶梯、票面一律留空,标注「待判读」。

为什么刻意留空(26102 复盘落库的理由):
  1. SOP 本体规定判断永不入脚本;
  2. 一份看起来完整的"初稿"会锚定后续判读——26102 的根因之一正是
     "错误的出发点掩盖更好的选项",预生成结论会让判读从做减法开始;
  3. 14:00 的盘不是终盘(26102 实测 09:18→15:11 有 4 条 1.0-1.7pp 的确认位移),
     此刻定下的任何"面"都必须复核。

18:30 的 revision slot 不重判,只把当日 afternoon 快照当基线做位移 diff ——
**位移窗口由我们自己的两次快照定义**,不依赖任何外部"开盘"源。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

STRONG_ANCHOR_TOP1 = 0.70
"""翻车场候选门槛(SOP p 条)。⚠️这里只筛 fair,『是否带方向性旗』必须人判。"""

COINFLIP_TOP1 = 0.45
"""方向抛硬币门槛(SOP h 条)。"""

MOVE_PP = 1.0
"""位移 diff 的报告门槛(pp)。低于此视为噪音,不进 diff 表。"""


# ---------------------------------------------------------------------------
# 足彩场次 ↔ 体彩 matchNum 对齐
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    return "".join((name or "").split())


def _name_match(a: str, b: str) -> bool:
    """队名相容:归一后相等,或一方是另一方的前缀。

    体彩不同接口对同一支队给的名字长度不一(板面 `homeTeamAllName` 是全名,
    赛果接口会截断成"克里斯蒂"/"哈尔姆斯"),足彩页又是第三套写法。前缀相容
    覆盖截断这一类差异;长度 <2 的前缀不算,免得"国际"匹配上所有队。
    """
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and long.startswith(short)


def board_rows(sporttery_value: dict) -> list[dict]:
    """摊平体彩板面(一个文件可能含多个业务日)。"""
    rows = []
    for day in sporttery_value.get("matchInfoList") or []:
        for row in day.get("subMatchList") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def alias_resolver():
    """中文队名 → API-Football 英文名。复用采集侧那张表,不另造一套模糊匹配。

    足彩页与体彩板面对同一支队的中文写法常不同(埃因霍温 / PSV埃因霍温、
    萨堡 / 萨尔普斯堡),而这两种写法在别名表里都指向同一个英文名 ——
    **别名表本来就是这个问题的现成答案**,自造前缀规则只会漏。
    """
    from nutmeg.decision.identity import norm_team
    from nutmeg.services.jczq_apifootball_odds import load_team_aliases

    table = {norm_team(k): v for k, v in load_team_aliases().items()
             if not str(k).startswith("_")}

    def resolve(name: str) -> str | None:
        return table.get(norm_team(name or ""))

    return resolve


def _same_team(zname: str, bname: str, resolve) -> bool:
    za, zb = resolve(zname), resolve(bname)
    if za and zb:
        return za == zb          # 两边都能解析 → 别名表说了算
    return _name_match(zname, bname)   # 有一边没入表 → 退回字面相容


def align_to_sporttery(zucai_matches: list[dict], sporttery_value: dict,
                       *, resolve=None) -> dict:
    """{match_no: matchNum} + 未对齐清单。

    未对齐 = 该场拿不到体彩 ttg 形状约束(DC 只能固定 ρ 拟),也拿不到让球线。
    这不是致命伤(had fair 仍来自国际盘),但必须**报出来**——静默降级正是
    8/04 整板丢锚而无人知的形状。注意有些场次是**真的不在竞彩板上**
    (如英联赛杯),那属于事实而非缺陷,同样要显式列出来。
    """
    if resolve is None:
        resolve = alias_resolver()
    rows = board_rows(sporttery_value)
    mapping: dict[int, str] = {}
    unmatched: list[dict] = []
    ambiguous: list[dict] = []
    for zm in zucai_matches:
        no = int(zm.get("match_no") or 0)
        home, away = zm.get("home_team") or "", zm.get("away_team") or ""
        cands = [r for r in rows
                 if _same_team(home, r.get("homeTeamAllName")
                               or r.get("homeTeamAbbName") or "", resolve)
                 and _same_team(away, r.get("awayTeamAllName")
                                or r.get("awayTeamAbbName") or "", resolve)]
        nums = sorted({str(c.get("matchNum")) for c in cands})
        if len(nums) == 1:
            mapping[no] = nums[0]
        elif not nums:
            unmatched.append({"match_no": no, "home": home, "away": away,
                              "competition": zm.get("competition")})
        else:
            ambiguous.append({"match_no": no, "home": home, "away": away,
                              "candidates": nums})
    return {"mapping": mapping, "unmatched": unmatched, "ambiguous": ambiguous}


# ---------------------------------------------------------------------------
# 体彩池 → 去水 fair
# ---------------------------------------------------------------------------

def sporttery_pools(row: dict) -> dict:
    """从一行体彩板面取 ttg 去水 fair、让球线、had 更新日(陈盘检测用)。"""
    from nutmeg.decision.market_data import devig

    rec: dict = {"ttg": None, "hhad_line": None, "had_date": None}
    ttg = row.get("ttg") or {}
    keys = [(f"s{k}", f"total_{k}") for k in range(8)]
    odds = {dst: float(ttg[src]) for src, dst in keys if ttg.get(src)}
    if len(odds) == 8:
        rec["ttg"] = devig(odds)
    hh = row.get("hhad") or {}
    if hh.get("goalLine"):
        rec["hhad_line"] = hh["goalLine"]
    rec["had_date"] = (row.get("had") or {}).get("updateDate")
    return rec


def euro_fair(odds_row: dict) -> dict | None:
    """国际均值欧赔 → 去水 fair。缺任一路返回 None(整场丢锚)。"""
    from nutmeg.decision.market_data import devig

    try:
        raw = {k: float(odds_row[k]) for k in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError):
        return None
    if any(v <= 1.0 for v in raw.values()):
        return None
    return devig(raw)


# ---------------------------------------------------------------------------
# 机械筛选(纯算术,不含判断)
# ---------------------------------------------------------------------------

def _top1(fair: dict) -> tuple[str, float]:
    face = max(fair, key=lambda k: fair[k])
    return face, fair[face]


def screens(records: dict) -> dict:
    """只算三件可算的事,外加两张"丢了什么"的清单。

    ⚠️`strong_anchors` 是**候选池不是结论**:SOP p 条的翻车场判据是
    「fair top1 ≥70% ∧ 带任何方向性旗」,而"有没有旗"必须人判。
    """
    strong, coinflip, fat_draw, no_euro, no_ttg = [], [], [], [], []
    for no, rec in sorted(records.items(), key=lambda kv: int(kv[0])):
        if not rec.get("fair_had"):
            no_euro.append({"match_no": int(no), "name": rec["name"]})
            continue
        if not rec.get("ttg_anchor"):
            no_ttg.append({"match_no": int(no), "name": rec["name"]})
        face, p = _top1(rec["fair_had"])
        item = {"match_no": int(no), "name": rec["name"], "face": face,
                "top1": round(p, 4)}
        if p >= STRONG_ANCHOR_TOP1:
            strong.append(item)
        if p < COINFLIP_TOP1:
            coinflip.append(item)
        fat_draw.append({"match_no": int(no), "name": rec["name"],
                         "draw": round(rec["fair_had"]["draw"], 4)})
    strong.sort(key=lambda x: -x["top1"])
    coinflip.sort(key=lambda x: x["top1"])
    fat_draw.sort(key=lambda x: -x["draw"])
    return {
        "strong_anchors": strong,
        "coinflip": coinflip,
        "fattest_draws": fat_draw[:5],
        "missing_euro_anchor": no_euro,
        "missing_ttg_anchor": no_ttg,
    }


# ---------------------------------------------------------------------------
# 备料主流程
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrepInputs:
    issue: str
    run_date: str
    slot: str
    zucai_dir: Path
    output_dir: Path


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text("utf-8"))


def board_dates(run_date: str, matches: list[dict]) -> list[str]:
    """一期 14 场常横跨两个体彩业务日,且足彩的 match_date 与体彩业务日不总相等
    (深夜场归前一日)。故取 run_date ∪ 各场 match_date,再各向前后扩一天。"""
    base = {run_date} | {str(m.get("match_date")) for m in matches if m.get("match_date")}
    out: set[str] = set()
    for d in base:
        try:
            day = date.fromisoformat(d)
        except (TypeError, ValueError):
            continue
        for offset in (-1, 0, 1):
            out.add((day + timedelta(days=offset)).isoformat())
    return sorted(out)


def load_boards(output_dir: Path, run_date: str, matches: list[dict]) -> dict:
    """合并相关业务日的体彩板面。缺哪天就少哪天,不报错(缺口由对齐清单点名)。"""
    merged: list[dict] = []
    seen: set[str] = set()
    for d in board_dates(run_date, matches):
        path = Path(output_dir) / "daily" / d / "sporttery_markets.json"
        if not path.exists():
            continue
        for row in board_rows(_load(path)):
            num = str(row.get("matchNum"))
            if num not in seen:
                seen.add(num)
                merged.append(row)
    return {"matchInfoList": [{"subMatchList": merged}]}


def build_prep(inputs: PrepInputs, *, captured_at: str | None = None) -> dict:
    """组装备料包。读已落盘的 issue/odds/体彩板面,不打网。"""
    from nutmeg.decision.dcfit import fit_match

    zdir, issue = Path(inputs.zucai_dir), inputs.issue
    issue_doc = _load(zdir / f"{issue}-issue.json")
    odds_name = f"{issue}-odds-revision.json" if inputs.slot == "revision" \
        else f"{issue}-odds.json"
    odds_doc = _load(zdir / odds_name)
    odds_by_no = {int(r["match_no"]): r for r in odds_doc.get("matches") or []}

    # titan007 国际欧赔(decision-fetch-zucai-intl 的产物)——**只补充不替换**。
    # 基线 fair_had 仍来自 500.com;直接换掉会静默改变足彩判读层的输入分布,那属
    # 判据变更,须先有证据再由用户裁定(与竞彩换源同一条规矩)。文件缺失是常态
    # (没跑过 / 全场对不上 titan007 板面),那时 intl 一律 None。
    intl_by_no: dict[int, dict] = {}
    intl_path = zdir / f"{issue}-odds-intl.json"
    if intl_path.exists():
        try:
            intl_by_no = {
                int(r["match_no"]): r
                for r in (_load(intl_path).get("matches") or [])
            }
        except (OSError, ValueError, KeyError, TypeError):
            intl_by_no = {}

    matches = issue_doc.get("matches") or []
    board_value = load_boards(Path(inputs.output_dir), inputs.run_date, matches)
    rows_by_num = {str(r.get("matchNum")): r for r in board_rows(board_value)}
    align = align_to_sporttery(matches, board_value)

    records: dict[str, dict] = {}
    for zm in matches:
        no = int(zm.get("match_no") or 0)
        name = f"{zm.get('home_team')}-{zm.get('away_team')}"
        rec: dict = {
            "name": name,
            "league": zm.get("competition"),
            "kickoff_bj": zm.get("kickoff_bj"),
            "match_date": zm.get("match_date"),
            "sporttery_match_num": align["mapping"].get(no),
        }
        fair = euro_fair(odds_by_no.get(no) or {})
        rec["fair_had"] = {k: round(v, 4) for k, v in fair.items()} if fair else None
        rec["intl"] = intl_by_no.get(no)
        pools = sporttery_pools(rows_by_num.get(align["mapping"].get(no) or "", {}))
        rec["sporttery_had_date"] = pools["had_date"]
        rec["hhad_line"] = pools["hhad_line"]
        if fair:
            rec.update(fit_match(fair, ttg_fair=pools["ttg"],
                                 hhad_line=pools["hhad_line"]))
        else:
            rec["ttg_anchor"] = False
        records[str(no)] = rec

    return {
        "issue": issue,
        "run_date": inputs.run_date,
        "slot": inputs.slot,
        "captured_at": captured_at or datetime.now().isoformat(timespec="seconds"),
        "n_matches": len(matches),
        "alignment": {"unmatched": align["unmatched"], "ambiguous": align["ambiguous"]},
        "records": records,
        "screens": screens(records),
        "judgment": None,   # ← 判读层刻意留空;由主循环 Claude 产出,不由本任务生成
    }


def diff_prep(base: dict, later: dict, *, threshold_pp: float = MOVE_PP) -> dict:
    """两次快照的 fair 位移(pp)。只报超过门槛的面,不重判、不给结论。"""
    moves = []
    for no, rec in sorted(later.get("records", {}).items(), key=lambda kv: int(kv[0])):
        old = (base.get("records", {}).get(no) or {}).get("fair_had")
        new = rec.get("fair_had")
        if not old or not new:
            continue
        deltas = {k: (new[k] - old[k]) * 100 for k in ("home", "draw", "away")}
        if max(abs(v) for v in deltas.values()) < threshold_pp:
            continue
        moves.append({"match_no": int(no), "name": rec["name"],
                      "delta_pp": {k: round(v, 1) for k, v in deltas.items()},
                      "fair_now": new})
    moves.sort(key=lambda m: -max(abs(v) for v in m["delta_pp"].values()))
    return {"issue": later.get("issue"), "base_slot": base.get("slot"),
            "later_slot": later.get("slot"),
            "base_captured_at": base.get("captured_at"),
            "later_captured_at": later.get("captured_at"),
            "threshold_pp": threshold_pp, "n_moved": len(moves), "moves": moves}


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def render_brief(prep: dict) -> str:
    """人读的备料 brief(Markdown)。判读区域是显式的空表,不是省略。"""
    L: list[str] = []
    L.append(f"# 传统足彩 {prep['issue']} · 备料底座({prep['slot']})")
    L.append("")
    L.append(f"快照 {prep['captured_at']} ｜ 业务日 {prep['run_date']} ｜ "
             f"{prep['n_matches']} 场")
    L.append("")
    L.append("> **本文件只含事实与确定性算术。** 旗 / 共振级 / 动作阶梯 / 票面 "
             "全部留空,由主循环判读产出。14:00 的盘不是终盘,出票前必须复核位移。")
    L.append("")

    al = prep["alignment"]
    if al["unmatched"] or al["ambiguous"]:
        L.append("## ⚠️ 对齐缺口(这些场丢体彩 ttg 形状约束与让球线)")
        for u in al["unmatched"]:
            L.append(f"- 场{u['match_no']} {u['home']}-{u['away']}:体彩板面未找到")
        for a in al["ambiguous"]:
            L.append(f"- 场{a['match_no']} {a['home']}-{a['away']}:多个候选 "
                     f"{'/'.join(a['candidates'])}")
        L.append("")

    intl_rows = [(no, r) for no, r in sorted(prep["records"].items(),
                                             key=lambda kv: int(kv[0]))
                 if r.get("intl")]
    if intl_rows:
        L.append("## 国际欧赔(titan007 锐盘共识) — 补充口径,基线仍是 500.com")
        L.append("")
        L.append("| 场 | 对阵 | 500 基线 fair | 007 fair | 最大差 pp | 开盘位移 pp "
                 "| 跨家分歧 pp | 家 | 对齐来源 |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for no, rec in intl_rows:
            intl = rec["intl"]
            base = rec.get("fair_had") or {}
            f = intl.get("fair") or {}
            micro = intl.get("micro") or {}
            fmt = lambda d: ("/".join(f"{(d.get(k) or 0) * 100:.0f}"    # noqa: E731
                                      for k in ("home", "draw", "away"))
                             if d else "—")
            gap = ("—" if not base or not f else
                   f"{max(abs((base.get(k) or 0) - (f.get(k) or 0)) for k in f) * 100:.2f}")
            L.append(
                f"| {no} | {rec['name']} | {fmt(base)} | {fmt(f)} | {gap} "
                f"| {micro.get('drift_pp', '—')} | {micro.get('dispersion_pp', '—')} "
                f"| {intl.get('books', '—')} | {intl.get('jczq_match_no') or '—'} |"
            )
        missing = [no for no, r in sorted(prep["records"].items(),
                                          key=lambda kv: int(kv[0]))
                   if not r.get("intl")]
        if missing:
            L.append("")
            L.append(f"> 场 {'、'.join(missing)} 无国际共识——足彩含竞彩不卖的场次,"
                     f"titan007 板面上没有,这些腿仍只有 500.com 单源。")
        L.append("")
        L.append("> 开盘位移是**旧源结构性拿不到**的量(API-Football 基础 /odds 无初赔,"
                 "drift 在那边恒为 0)。方向与阈值未定,三个对应因子在 probation,"
                 "待双轴校准——**不要拿它当已定判据**。")
        L.append("")

    sc = prep["screens"]
    if sc["missing_euro_anchor"]:
        L.append("## ⚠️ 丢国际欧赔锚(prior 退化,必须人工补)")
        for m in sc["missing_euro_anchor"]:
            L.append(f"- 场{m['match_no']} {m['name']}")
        L.append("")

    L.append("## 逐场底座")
    L.append("")
    L.append("| 场 | 赛事 | 对阵 | 开球 | fair 主/平/客 | 模态比分 | 大2.5 | 让球线 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for no in sorted(prep["records"], key=int):
        r = prep["records"][no]
        f = r.get("fair_had")
        fair_s = (f"{f['home']*100:.1f}/{f['draw']*100:.1f}/{f['away']*100:.1f}"
                  if f else "— 丢锚")
        top = r.get("top_scores") or []
        top_s = " ".join(f"{s}({p*100:.0f}%)" for s, p in top[:2]) if top else "—"
        o25 = f"{r['over25']*100:.0f}%" if r.get("over25") is not None else "—"
        stale = " ⚠️陈盘" if r.get("sporttery_had_date") and \
            r["sporttery_had_date"] != prep["run_date"] else ""
        L.append(f"| {no} | {r.get('league') or ''} | {r['name']}{stale} | "
                 f"{r.get('kickoff_bj') or ''} | {fair_s} | {top_s} | {o25} | "
                 f"{r.get('hhad_line') or '—'} |")
    L.append("")

    L.append("## 机械筛选(候选池,不是结论)")
    L.append("")
    L.append(f"**强锚 top1 ≥{STRONG_ANCHOR_TOP1:.0%}** —— 翻车场**候选**;"
             "是否成为翻车场取决于『带不带方向性旗』,那一步必须人判:")
    L.extend([f"- 场{s['match_no']} {s['name']} → {s['face']} {s['top1']*100:.1f}%"
              for s in sc["strong_anchors"]] or ["- (无)"])
    L.append("")
    L.append(f"**方向抛硬币 top1 <{COINFLIP_TOP1:.0%}** —— SOP h 条建议换进球轴:")
    L.extend([f"- 场{s['match_no']} {s['name']} → top1 仅 {s['top1']*100:.1f}%"
              for s in sc["coinflip"]] or ["- (无)"])
    L.append("")
    L.append("**平局面值最肥的 5 场**(奖池均分下全包优先序参考):")
    L.extend([f"- 场{s['match_no']} {s['name']} → 平 {s['draw']*100:.1f}%"
              for s in sc["fattest_draws"]])
    if sc["missing_ttg_anchor"]:
        L.append("")
        L.append("**无体彩 ttg 形状约束(DC 仅固定 ρ 拟合,进球带精度下降)**:")
        L.extend([f"- 场{m['match_no']} {m['name']}" for m in sc["missing_ttg_anchor"]])
    L.append("")

    L.append("## 判读(待主循环填写)")
    L.append("")
    L.append("| 场 | 旗 | 共振级 | 动作 | 选面 | 依据 |")
    L.append("|---|---|---|---|---|---|")
    for no in sorted(prep["records"], key=int):
        L.append(f"| {no} |  |  |  |  |  |")
    L.append("")
    return "\n".join(L)


def render_diff(diff: dict) -> str:
    L = [f"# {diff['issue']} · 盘口位移复核({diff['base_slot']} → {diff['later_slot']})",
         "",
         f"基线 {diff['base_captured_at']} → 现在 {diff['later_captured_at']} ｜ "
         f"门槛 {diff['threshold_pp']}pp ｜ 超门槛 {diff['n_moved']} 条",
         "",
         "> 只报位移,不重判。位移本身不是理由——急动先查因(临场情报→改,纯噪音→守)。",
         ""]
    if not diff["moves"]:
        L.append("**无超过门槛的位移。**")
        return "\n".join(L)
    L.append("| 场 | 对阵 | Δ主 | Δ平 | Δ客 | 现 fair 主/平/客 |")
    L.append("|---|---|---|---|---|---|")
    for m in diff["moves"]:
        d, f = m["delta_pp"], m["fair_now"]
        L.append(f"| {m['match_no']} | {m['name']} | {d['home']:+.1f} | "
                 f"{d['draw']:+.1f} | {d['away']:+.1f} | "
                 f"{f['home']*100:.1f}/{f['draw']*100:.1f}/{f['away']*100:.1f} |")
    return "\n".join(L)


def heartbeat_line(prep: dict | None, gate_status: str, *,
                   today: date | None = None) -> str:
    """Telegram 一行。无期日也发 —— 不说话的任务和死掉的任务无法区分。"""
    if prep is None:
        return f"🌙 足彩备料 {today or date.today()}:{gate_status}"
    sc = prep["screens"]
    bits = [f"📋 足彩 {prep['issue']} 备料完成({prep['slot']})",
            f"{prep['n_matches']} 场"]
    if sc["missing_euro_anchor"]:
        bits.append(f"⚠️丢锚 {len(sc['missing_euro_anchor'])} 场")
    if prep["alignment"]["unmatched"] or prep["alignment"]["ambiguous"]:
        n = len(prep["alignment"]["unmatched"]) + len(prep["alignment"]["ambiguous"])
        bits.append(f"⚠️未对齐 {n} 场")
    bits.append(f"强锚候选 {len(sc['strong_anchors'])}")
    bits.append("判读待主循环")
    return " ｜ ".join(bits)


# ---------------------------------------------------------------------------
# 编排(CLI 胶水)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrepResult:
    status: str          # prepared | no_issue | gate_failed | fetch_failed
    summary: str
    issue: str | None = None
    prep_path: Path | None = None
    brief_path: Path | None = None
    diff_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in {"prepared", "no_issue"}


SLOT_ORDER = ("morning", "afternoon", "revision")
"""备料槽位顺序。morning(11:00) 是 2026-09-11 新增的**早刷新**槽。

出生事故 26122：14:00 才第一次刷新盘口，导致当天 8 场判读用的是**前一天(09-10)的
体彩 HAD**。读判在 14:00 冻结，也就是说冻结用的基线比冻结晚了一天——
"陈盘"不是数据缺失，是**判读建立在过期价格上**却没人喊。"""


def _previous_slot(issue: str, slot: str, zdir: Path) -> str | None:
    """本 slot 之前最近的、已经落盘的槽位（用于位移 diff 的基线）。"""
    if slot not in SLOT_ORDER:
        return None
    for earlier in reversed(SLOT_ORDER[:SLOT_ORDER.index(slot)]):
        if (zdir / f"{issue}-prep-{earlier}.json").exists():
            return earlier
    return None


def _notify(body: str, *, stage: str, business_key: str, attachments=(),
            notification_service=None) -> None:
    from nutmeg.notifications.models import NotificationRequest, semantic_fingerprint
    from nutmeg.notifications.wiring import build_notification_service

    service = notification_service or build_notification_service()
    service.publish(NotificationRequest(
        kind=f"zucai.prep.{stage}",
        business_key=business_key,
        stage=stage,
        semantic_fingerprint=semantic_fingerprint({"stage": stage, "body": body}),
        subject=f"足彩备料 {business_key}",
        caption=body,
        body=body,
        attachments=tuple(attachments),
    ))


def run_zucai_prep(
    *,
    run_date: str | None = None,
    slot: str = "afternoon",
    issue: str | None = None,
    zucai_dir: Path = Path(".nutmeg-data/zucai"),
    output_dir: Path = Path(".nutmeg-data/jczq"),
    live_fetch: bool = True,
    dispatch: bool = False,
    gate_fetcher=None,
    notification_service=None,
) -> PrepResult:
    """备料任务主入口(14:00 afternoon / 18:30 revision)。

    门控:``issue`` 显式给出则跳过探测(手动补跑);否则探在售期,今天不是截止日
    就只发心跳。**任何一条路径都会说话** —— 无期、探测失败、抓取失败各有文案。
    """
    from nutmeg.decision.zucai_gate import gate as gate_fn

    today = date.fromisoformat(run_date) if run_date else date.today()
    run_date = today.isoformat()

    if issue is None:
        insale, status = gate_fn(today=today, fetcher=gate_fetcher)
        if insale is None:
            line = heartbeat_line(None, status, today=today)
            if dispatch:
                _notify(line, stage=f"{slot}.gate-failed", business_key=run_date,
                        notification_service=notification_service)
            return PrepResult(status="gate_failed", summary=line)
        if not insale.is_sale_day(today):
            line = heartbeat_line(None, status, today=today)
            if dispatch:
                _notify(line, stage=f"{slot}.no-issue", business_key=run_date,
                        notification_service=notification_service)
            return PrepResult(status="no_issue", summary=line, issue=insale.issue)
        issue = insale.issue

    if live_fetch:
        from nutmeg.decision.zucai_insale import fetch_and_write
        try:
            written = fetch_and_write(Path(zucai_dir), slot=slot, today=today)
            if written["issue"] != issue:
                raise ValueError(f"在售期已切换:期望 {issue},实抓 {written['issue']}")
        except Exception as exc:      # noqa: BLE001 — 抓取失败要说话,不要静默
            line = f"⚠️ 足彩 {issue} 备料抓取失败({slot}):{exc}"
            if dispatch:
                _notify(line, stage=f"{slot}.fetch-failed", business_key=run_date,
                        notification_service=notification_service)
            return PrepResult(status="fetch_failed", summary=line, issue=issue)

    prep = build_prep(PrepInputs(issue=issue, run_date=run_date, slot=slot,
                                 zucai_dir=Path(zucai_dir),
                                 output_dir=Path(output_dir)))
    zdir = Path(zucai_dir)
    zdir.mkdir(parents=True, exist_ok=True)
    prep_path = zdir / f"{issue}-prep-{slot}.json"
    brief_path = zdir / f"{issue}-prep-{slot}.md"
    prep_path.write_text(json.dumps(prep, ensure_ascii=False, indent=1), "utf-8")
    brief_path.write_text(render_brief(prep), "utf-8")

    diff_path = None
    line = heartbeat_line(prep, "", today=today)
    base_slot = _previous_slot(issue, slot, zdir)
    if base_slot:
        base_path = zdir / f"{issue}-prep-{base_slot}.json"
        diff = diff_prep(_load(base_path), prep)
        diff_path = zdir / f"{issue}-diff-{base_slot}-{slot}.md"
        diff_path.write_text(render_diff(diff), "utf-8")
        line += f" ｜ 位移超门槛 {diff['n_moved']} 条(vs {base_slot})"
    elif slot != SLOT_ORDER[0]:
        line += " ｜ ⚠️无更早 slot 基线,跳过位移 diff"

    if dispatch:
        _notify(line, stage=slot, business_key=f"{issue}-{slot}",
                notification_service=notification_service)
    return PrepResult(status="prepared", summary=line, issue=issue,
                      prep_path=prep_path, brief_path=brief_path,
                      diff_path=diff_path)
