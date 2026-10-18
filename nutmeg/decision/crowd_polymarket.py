"""Polymarket 关注度（2026-10-09）。

设计稿：docs/superpowers/specs/2026-10-09-polymarket-attention-design.md。

**测量仪**：把我方场次对到 Polymarket 对阵，落成交量 / 三向归一价 / 与市场基线差 / 本板关注度名次。
只展示、只记账：会话粗测里名气热门不比市场更易翻车（高关注 n=181 +3.5pp），所以这里不给任何权重；
奖池角度（人群多买名气热门）交给人群假说 CR-cand-4，结果角度交给 F17。
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from nutmeg.data.prices import devig
from nutmeg.decision.bj_time import bj_iso, parse_bj
from nutmeg.decision.files import read_json

SHOW_MIN_VOLUME = 20_000.0         # 展示与走势只对「有量」的场（Jun 2026-10-09）
FACES = ("home", "draw", "away")
_STOP = frozenset({
    "fc", "cf", "sc", "sv", "bv", "ac", "as", "afc", "cd", "ca", "rc", "club", "de", "del",
    "la", "le", "the", "and", "sk", "fk", "bk", "ik", "vfb", "vfl", "tsg", "ssc", "us", "ss",
    "ogc", "rcd", "ud", "sd", "cp", "ec", "se", "calcio", "will", "win", "end", "draw", "vs",
    "in", "on", "a",
})


def _tokens(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    words = re.split(r"[^a-z0-9]+", plain.lower())
    return [w for w in words if len(w) >= 2 and not w.isdigit() and w not in _STOP]


def _score(names: list[str], side: str) -> int:
    """我方英文名与对方一侧的重合度：我方**每个**关键词（≥3 字母）都要在对方找到
    （相同或 ≥4 字母前缀），
    得分＝关键词数；≤4 字母全大写别名按首字母缩写或整词比。"""
    side_tokens = _tokens(side)
    side_set = set(side_tokens)
    initials = "".join(t[0] for t in side_tokens)
    best = 0
    for name in names:
        bare = re.sub(r"[^A-Za-z]", "", name)
        if name.isupper() and 2 <= len(bare) <= 4:
            if bare.lower() in side_set or bare.lower() == initials:
                best = max(best, 1)
            continue
        keys = {t for t in _tokens(name) if len(t) >= 3}
        if keys and all(any(_same(k, t) for t in side_tokens) for k in keys):
            best = max(best, len(keys))
    return best


def _same(ours: str, theirs: str) -> bool:
    """相同，或一方是另一方 ≥4 字母的前缀（Lyon ↔ Lyonnais）。"""
    if ours == theirs:
        return True
    short, long_ = sorted((ours, theirs), key=len)
    return len(short) >= 4 and long_.startswith(short)


def side_matches(names: list[str], side: str) -> bool:
    return _score(names, side) > 0


@dataclass
class Namer:
    """我方中文队名 → 英文名候选：中译英别名表（竞彩国际赔率对号同一张）＋ 种子实体英文名。"""

    cn2en: dict[str, str]
    resolve: Callable[[str], str | None]
    seed_en: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def default(cls) -> Namer:
        from nutmeg.data.team_aliases import load_national_team_aliases, load_team_aliases
        from nutmeg.decision.entities import load_seed_entities
        from nutmeg.decision.team_load import default_resolver

        cn2en = {k: v for k, v in {**load_national_team_aliases(), **load_team_aliases()}.items()
                 if not str(k).startswith("_")}
        teams, _ = load_seed_entities()
        seed_en = {t.team_id: [n for n in (t.name_en, *t.aliases) if n and n.isascii()]
                   for t in teams}
        return cls(cn2en=cn2en, resolve=default_resolver(), seed_en=seed_en)

    def english(self, *cn_names: str) -> list[str]:
        out: list[str] = []
        for cn in cn_names:
            if not cn:
                continue
            for name in (self.cn2en.get(cn), *self.seed_en.get(self.resolve(cn) or "", [])):
                if name and name not in out:
                    out.append(name)
        return out


def match_event(namer: Namer, home_cn: list[str], away_cn: list[str], day: str,
                events: list[dict]) -> dict | None:
    """两边都对上、结束日与 `day` 相差 ≤1 天、且唯一 → 该事件；否则 None（不猜）。"""
    home, away = namer.english(*home_cn), namer.english(*away_cn)
    if not home or not away:
        return None
    on = date.fromisoformat(day[:10])
    hits = []
    for ev in events:
        try:
            end = date.fromisoformat(str(ev.get("end"))[:10])
        except ValueError:
            continue
        if abs((end - on).days) > 1:
            continue
        straight = _score(home, ev["home"]) and _score(away, ev["away"])
        swapped = _score(home, ev["away"]) and _score(away, ev["home"])
        if straight or swapped:
            hits.append(ev)
    return hits[0] if len(hits) == 1 else None


def faces_from_markets(event: dict, home: list[str], away: list[str]) -> dict:
    """三个二元市场 → {home/draw/away: {bid, ask, mid, token}}，按问题里点名的球队归面。"""
    out: dict[str, dict] = {}
    for market in event.get("markets") or []:
        question = market.get("question") or ""
        if "draw" in question.lower():
            face = "draw"
        else:
            sh, sa = _score(home, question), _score(away, question)
            if sh == sa:
                continue
            face = "home" if sh > sa else "away"
        bid, ask = market.get("bid"), market.get("ask")
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        out[face] = {"bid": bid, "ask": ask, "mid": mid, "token": market.get("token"),
                     "volume": market.get("volume"), "volume24hr": market.get("volume24hr"),
                     "condition_id": market.get("condition_id"),
                     "last_trade": market.get("last_trade")}
    return out


LOPSIDED_SHARE = 0.8          # 单一市场占事件成交 ≥80%
FLAT_PP = 1.0                 # 三面走势都在 ±1pp 内＝「价不动」
MONEY_MIN_USD = 1000.0        # 逐笔净额 <$1k 不读方向


def money_direction(flow: dict) -> dict | None:
    """逐笔 → 钱去了哪一面（2026-10-18 Jun「标明资金去的队伍」）。

    每面净额 = 买Yes − 卖Yes − 买No + 卖No
    （买 No 桑德兰＝押伯恩茅斯或平，所以记在桑德兰面的负号上）。
    `face`＝净额最大且 ≥$1k 的面；`against`＝净额最小且 ≤−$1k 的面；都没有 → None。"""
    net = {f: round(v.get("buy_yes", 0.0) - v.get("sell_yes", 0.0) - v.get("buy_no", 0.0)
                    + v.get("sell_no", 0.0), 2) for f, v in flow.items() if v}
    if not net:
        return None
    top, low = max(net, key=net.get), min(net, key=net.get)
    out = {"face": top if net[top] >= MONEY_MIN_USD else None,
           "usd": net[top] if net[top] >= MONEY_MIN_USD else None,
           "against": low if net[low] <= -MONEY_MIN_USD else None,
           "against_usd": net[low] if net[low] <= -MONEY_MIN_USD else None}
    return out if out["face"] or out["against"] else None


def is_lopsided(faces: dict, trend_pp: dict | None, volume: float) -> bool:
    """「富勒姆型」形状判据（26144 场 2：$213k 整板最高、钱压一面、价不动）：
    事件有量 ∧ 单一市场占三市场 ≥80% ∧ 三面走势全在 ±1pp。只标形状，不推概率。"""
    vols = [float((faces.get(f) or {}).get("volume") or 0.0) for f in FACES]
    total = sum(vols)
    if volume < SHOW_MIN_VOLUME or total <= 0 or not trend_pp or len(trend_pp) < 3:
        return False
    return max(vols) / total >= LOPSIDED_SHARE and all(abs(v) <= FLAT_PP for v in trend_pp.values())


def board_rows(namer: Namer, matches: list[dict], events: list[dict], *,
               trend: Callable[[str], tuple[float | None, float | None]] | None = None,
               flow: Callable[[str], dict] | None = None) -> dict:
    """我方一块板（`[{key, home[], away[], kickoff, fair}]`）→ {key: Polymarket 行}。

    对不上的场不出行。`flow`（2026-10-18）：有量的场按三个市场的 conditionId 取逐笔合计，
    落 `flow[face]`、`money_to`；`lopsided` 标「富勒姆型」形状。"""
    rows: dict[str, dict] = {}
    for m in matches:
        kickoff = parse_bj(m.get("kickoff"))
        if kickoff is None:
            continue
        ev = match_event(namer, m["home"], m["away"], kickoff.date().isoformat(), events)
        if ev is None:
            continue
        faces = faces_from_markets(ev, namer.english(*m["home"]), namer.english(*m["away"]))
        mids = {f: (faces.get(f) or {}).get("mid") for f in FACES}
        probs = (devig({f: 1 / mids[f] for f in FACES})
                 if all(v and v > 0 for v in mids.values()) else None)
        fair = m.get("fair") or {}
        row = {"event_id": ev["id"], "title": ev.get("title"), "volume": ev.get("volume") or 0.0,
               "liquidity": ev.get("liquidity"), "volume24hr": ev.get("volume24hr"),
               "faces": faces, "probs": probs, "kickoff": bj_iso(m["kickoff"]),
               "vs_market_pp": ({f: round((probs[f] - float(fair[f])) * 100, 1) for f in FACES}
                                if probs and all(f in fair for f in FACES) else None)}
        if trend is not None and row["volume"] >= SHOW_MIN_VOLUME:
            row["trend_pp"] = {}
            for f in FACES:
                token = (faces.get(f) or {}).get("token")
                first, last = trend(token) if token else (None, None)
                if first is not None and last is not None:
                    row["trend_pp"][f] = round((last - first) * 100, 1)
        if flow is not None and row["volume"] >= SHOW_MIN_VOLUME:
            row["flow"] = {f: flow(cid) for f in FACES
                           if (cid := (faces.get(f) or {}).get("condition_id"))}
            row["money_to"] = money_direction(row["flow"])
        row["lopsided"] = is_lopsided(faces, row.get("trend_pp"), row["volume"])
        rows[str(m["key"])] = row
    for rank, key in enumerate(sorted(rows, key=lambda k: -rows[k]["volume"]), start=1):
        rows[key]["rank"] = rank
    return rows


def last_rows(path: Path) -> dict:
    """最后一张快照的逐场行（初判包展示用）。"""
    snaps = (read_json(path, {}) or {}).get("snapshots") or []
    return (snaps[-1].get("rows") or {}) if snaps else {}


def brief_cell(row: dict | None) -> str:
    """初判包「关注度」一格：只对成交 ≥$20k 的场——`PM$80k 73/16/11 主+3.1`（只看不拨动）。"""
    if not row or (row.get("volume") or 0) < SHOW_MIN_VOLUME:
        return ""
    text = f"PM${row['volume'] / 1000:.0f}k"
    probs = row.get("probs")
    if probs:
        text += " " + "/".join(f"{probs[f] * 100:.0f}" for f in FACES)
    diff = row.get("vs_market_pp") or {}
    if diff:
        face = max(FACES, key=lambda f: abs(diff.get(f) or 0.0))
        text += f" {dict(home='主', draw='平', away='客')[face]}{diff[face]:+.1f}"
    money = row.get("money_to") or {}
    cn = dict(home='主', draw='平', away='客')
    if money.get("face"):
        text += f" 钱→{cn[money['face']]}${money['usd'] / 1000:.1f}k"
    elif money.get("against"):
        text += f" 钱反{cn[money['against']]}"
    if row.get("lopsided"):
        text += " ⚑单向价不动"
    return text


def write_snapshot(path: Path, header: dict, rows: dict, *, fetched_at: str,
                   meta: dict | None = None) -> Path:
    """快照只追加（同 zgzcw 人群底座）。"""
    path = Path(path)
    doc = read_json(path, {}) or {}
    doc.update(header)
    doc.setdefault("snapshots", []).append({"fetched_at": fetched_at, **(meta or {}),
                                            "rows": rows})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def attention_for_issue(zdir: Path, issue: str) -> dict[int, tuple[float, int]]:
    """人群层用：最后一张快照 → {场号: (成交量千美元, 本期名次)}。"""
    snaps = (read_json(Path(zdir) / f"{issue}-polymarket.json", {}) or {}).get("snapshots") or []
    if not snaps:
        return {}
    out = {}
    for no, row in (snaps[-1].get("rows") or {}).items():
        if row.get("volume") is not None and row.get("rank") is not None:
            out[int(no)] = (round(float(row["volume"]) / 1000, 3), int(row["rank"]))
    return out


def _pre_kickoff_row(path: Path, key: str) -> dict | None:
    best = None
    for snap in (read_json(path, {}) or {}).get("snapshots") or []:
        row = (snap.get("rows") or {}).get(key)
        fetched, kickoff = parse_bj(snap.get("fetched_at")), parse_bj((row or {}).get("kickoff"))
        if row and fetched and kickoff and fetched < kickoff:
            best = {**row, "fetched_at": snap["fetched_at"]}
    return best


def attach_polymarket(rows: list[dict], data_dir: Path) -> int:
    """语料 v2：把开球前最后一张快照里的该场行挂到行顶层 `polymarket`（F17 结账用）。"""
    data_dir = Path(data_dir)
    attached = 0
    for row in rows:
        key = str(row.get("key") or "")
        if row.get("src") == "jczq" and len(key) > 11:
            found = _pre_kickoff_row(data_dir / "jczq" / "daily" / key[:10] / "polymarket.json",
                                     key[11:])
        elif row.get("src") == "zucai" and "-" in key:
            issue, no = key.split("-", 1)
            found = _pre_kickoff_row(data_dir / "zucai" / f"{issue}-polymarket.json", no)
        else:
            continue
        if found:
            row["polymarket"] = found
            attached += 1
    return attached


# ── 驱动：按日 / 按期抓快照，历史回补 ─────────────────────────────────────────


def fetch_events(fetch, end_min: str, end_max: str, *, closed: bool = False) -> list[dict]:
    """足球白名单系列在结束日窗口内的对阵（归一后）。"""
    from nutmeg.data.polymarket import normalize_event, series_events, soccer_series

    out = []
    for series_id in soccer_series(fetch).values():
        for ev in series_events(fetch, series_id, closed=closed, end_min=end_min,
                                end_max=end_max):
            norm = normalize_event(ev)
            if norm is not None:
                out.append(norm)
    return out


def _window(kickoffs: list[str]) -> tuple[str, str] | None:
    days = sorted(d.date() for d in (parse_bj(k) for k in kickoffs) if d is not None)
    if not days:
        return None
    return ((days[0] - timedelta(days=1)).isoformat(), (days[-1] + timedelta(days=2)).isoformat())


def _zgzcw_full_names(zdir: Path, issue: str) -> dict[int, tuple[str, str]]:
    snaps = (read_json(zdir / f"{issue}-zgzcw.json", {}) or {}).get("snapshots") or []
    rows = ((snaps[-1].get("raw") or {}).get("matchInfo") or []) if snaps else []
    return {no: (str(r.get("hostNameFull") or r.get("hostName") or ""),
                 str(r.get("guestNameFull") or r.get("guestName") or ""))
            for no, r in enumerate(rows, start=1)}


def _zgzcw_board_matches(zdir: Path, issue: str) -> list[dict]:
    """期次文件缺失（26070 之前）时用 zgzcw 快照：简称 + 全称、开球时间、去水市场概率。"""
    snaps = (read_json(zdir / f"{issue}-zgzcw.json", {}) or {}).get("snapshots") or []
    rows = ((snaps[-1].get("raw") or {}).get("matchInfo") or []) if snaps else []
    out = []
    for no, r in enumerate(rows, start=1):
        try:
            h, d, a = (float(x) for x in str(r.get("europeSp") or "").split())
            fair = devig({"home": h, "draw": d, "away": a})
        except ValueError:
            fair = {}
        out.append({"key": str(no),
                    "home": [str(r.get("hostName") or ""), str(r.get("hostNameFull") or "")],
                    "away": [str(r.get("guestName") or ""), str(r.get("guestNameFull") or "")],
                    "kickoff": str(r.get("gameStartDate") or ""), "fair": fair})
    return out


def zucai_board_matches(data_dir: Path, issue: str) -> list[dict]:
    """足彩期次 → 对号输入（500 简称 + zgzcw 全称都给 Namer 试）。"""
    zdir = Path(data_dir) / "zucai"
    matches = (read_json(zdir / f"{issue}-issue.json", {}) or {}).get("matches") or []
    if not matches:
        return _zgzcw_board_matches(zdir, issue)
    store = read_json(zdir / f"{issue}-store-ids.json", {}) or {}
    full = _zgzcw_full_names(zdir, issue)
    out = []
    for m in matches:
        no = int(m["match_no"])
        fh, fa = full.get(no, ("", ""))
        out.append({"key": str(no), "home": [m.get("home_team") or "", fh],
                    "away": [m.get("away_team") or "", fa], "kickoff": m.get("kickoff_bj"),
                    "fair": (store.get(str(no)) or {}).get("fair") or {}})
    return out


def jczq_board_matches(data_dir: Path, day: str) -> list[dict]:
    legs = (read_json(Path(data_dir) / "jczq" / "daily" / day / "jczq-legs-base.json", {})
            or {}).get("legs") or {}
    return [{"key": code, "home": [leg.get("home_team") or ""],
             "away": [leg.get("away_team") or ""], "kickoff": leg.get("kickoff_bj"),
             "fair": leg.get("fair") or {}} for code, leg in legs.items()]


def _trend(fetch):
    from nutmeg.data.polymarket import price_trend

    return lambda token: price_trend(fetch, token)


def _flow(fetch):
    from nutmeg.data.polymarket import trade_flow

    return lambda condition_id: trade_flow(fetch, condition_id)


def snapshot_issue(data_dir: Path, issue: str, *, fetch, now: str,
                   namer: Namer | None = None, with_flow: bool = False) -> Path | None:
    matches = zucai_board_matches(data_dir, issue)
    window = _window([m["kickoff"] for m in matches])
    if window is None:
        return None
    events = fetch_events(fetch, *window)
    rows = board_rows(namer or Namer.default(), matches, events, trend=_trend(fetch),
                      flow=_flow(fetch) if with_flow else None)
    return write_snapshot(Path(data_dir) / "zucai" / f"{issue}-polymarket.json",
                          {"issue": issue}, rows, fetched_at=now)


def snapshot_day(data_dir: Path, day: str, *, fetch, now: str,
                 namer: Namer | None = None, with_flow: bool = False) -> dict:
    """并集池的一天：竞彩当日板 + 当天截止的足彩期次（与 `research refresh` 同一口径）。"""
    from nutmeg.decision.zucai_identity import closing_issues

    data_dir = Path(data_dir)
    namer = namer or Namer.default()
    out: dict = {"jczq": None, "zucai": {}}
    matches = jczq_board_matches(data_dir, day)
    window = _window([m["kickoff"] for m in matches])
    if window is not None:
        rows = board_rows(namer, matches, fetch_events(fetch, *window), trend=_trend(fetch),
                          flow=_flow(fetch) if with_flow else None)
        out["jczq"] = str(write_snapshot(data_dir / "jczq" / "daily" / day / "polymarket.json",
                                         {"day": day}, rows, fetched_at=now))
    for issue, _doc in closing_issues(data_dir / "zucai", day):
        path = snapshot_issue(data_dir, issue, fetch=fetch, now=now, namer=namer,
                              with_flow=with_flow)
        if path is not None:
            out["zucai"][issue] = str(path)
    return out


def _closed_cache(data_dir: Path, fetch, end_min: str, end_max: str) -> list[dict]:
    """已结束对阵缓存（`zucai/polymarket-closed.json`）：窗口没被覆盖才去拉，拉回来合并。"""
    path = Path(data_dir) / "zucai" / "polymarket-closed.json"
    doc = read_json(path, {}) or {}
    covered = doc.get("covered") or []
    if not any(lo <= end_min and end_max <= hi for lo, hi in covered):
        events = {e["id"]: e for e in doc.get("events") or []}
        for ev in fetch_events(fetch, end_min, end_max, closed=True):
            events[ev["id"]] = {k: ev[k] for k in ("id", "title", "end", "home", "away",
                                                   "volume")}
        doc = {"covered": [*covered, [end_min, end_max]], "events": list(events.values())}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return [e for e in doc.get("events") or [] if end_min <= e["end"] <= end_max]


def backfill(data_dir: Path, issues: list[str], *, fetch, now: str,
             namer: Namer | None = None) -> dict[str, int]:
    """历史期次 → 一张 `source=closed_backfill` 的快照（成交量＝终场总成交；名次口径稳健）。"""
    data_dir = Path(data_dir)
    namer = namer or Namer.default()
    boards = {issue: zucai_board_matches(data_dir, issue) for issue in issues}
    window = _window([m["kickoff"] for ms in boards.values() for m in ms])
    if window is None:
        return {}
    events = _closed_cache(data_dir, fetch, *window)
    out = {}
    for issue, matches in boards.items():
        rows = board_rows(namer, matches, events)
        for row in rows.values():
            row.pop("faces", None)
            row.pop("probs", None)
            row.pop("vs_market_pp", None)
        write_snapshot(data_dir / "zucai" / f"{issue}-polymarket.json", {"issue": issue}, rows,
                       fetched_at=now, meta={"source": "closed_backfill"})
        out[issue] = len(rows)
    return out
