"""决策树样本表构建器（2026-10-19，Jun 要求「历史数据修复」）。

只做三件事：取数、对齐、确定性派生。**不做新的取证**——每一格都来自当时落盘的文件，
并带 provenance（来源文件 / 采集时刻 / 是否早于开球）。看过赛果再补写的研究不进本表。

输出：
  experiments/decision-samples-v1.jsonl   一行一场（按内核 match_id 去重，竞彩∪足彩）
  experiments/decision-samples-v1.coverage.md  每列的非空数与起止日期

用法：uv run python experiments/decision_samples_build.py [--from 2026-05-18] [--to 2026-10-18]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import Counter
from datetime import datetime

D = ".nutmeg-data"
FACES = ("3", "1", "0")
KEY = {"3": "home", "1": "draw", "0": "away"}


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def tri(d):
    """{home,draw,away} 或 {3,1,0} → {3,1,0} 浮点；百分制自动归一。"""
    if not isinstance(d, dict):
        return None
    out = {}
    for f in FACES:
        v = d.get(f, d.get(KEY[f], d.get(f"fair_{KEY[f]}")))
        if v is None:
            return None
        out[f] = float(v)
    s = sum(out.values())
    if s > 1.5:  # 百分制
        out = {k: v / 100 for k, v in out.items()}
    return out


def devig(odds):
    o = tri({k: odds.get(k) for k in ("home", "draw", "away")}) if isinstance(odds, dict) else None
    if not o or min(o.values()) <= 0:
        return None
    inv = {k: 1 / v for k, v in o.items()}
    s = sum(inv.values())
    return {k: v / s for k, v in inv.items()}


def fav_of(m):
    return max(m, key=m.get) if m else None


def prospective(captured, kickoff):
    if not captured or not kickoff:
        return None
    try:
        c = datetime.fromisoformat(str(captured).replace("Z", "+00:00"))
        k = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if c.tzinfo is None and k.tzinfo is not None:
            c = c.replace(tzinfo=k.tzinfo)
        if k.tzinfo is None and c.tzinfo is not None:
            k = k.replace(tzinfo=c.tzinfo)
        return c < k
    except Exception:
        return None


def hole_from_research(rs, fav_side):
    """新旧两种 hole_location 都折算成 {side_raw, rel(fav/dog/both/none), unit, priced_in}。"""
    h = rs.get("hole_location") or rs.get("_hole") or {}
    if not isinstance(h, dict):
        return None
    if "side" in h:  # 新 schema（2026-09-26 起）
        side, unit, priced = h.get("side"), h.get("unit"), h.get("priced_in")
    else:  # 旧 schema：{opponent: unit|null, anchor: unit|null}
        opp, anc = h.get("opponent"), h.get("anchor")
        if opp and anc:
            side, unit = "both", f"{anc}/{opp}"
        elif opp:
            side, unit = "underdog", opp
        elif anc:
            side, unit = "anchor", anc
        else:
            side, unit = "none", "none"
        priced = h.get("priced_in")
    rel = side
    if side in ("home", "away"):
        rel = (
            "fav"
            if (side == "home" and fav_side == "3") or (side == "away" and fav_side == "0")
            else "dog"
        )
    elif side == "anchor":
        rel = "fav"
    elif side == "underdog":
        rel = "dog"
    return {
        "side_raw": side,
        "rel": rel,
        "unit": unit,
        "priced_in": priced,
        "schema": "v2" if "side" in h else "v1",
    }


def research_block(rs, fav_side, kickoff):
    if not rs:
        return None
    st = rs.get("stance") or {}
    sb = rs.get("strength_balance") or {}
    d3 = rs.get("death_three_proofs") or {}
    up = (
        sb.get("underdog_path") or rs.get("underdog_path") or {}
    )  # 契约位置在 strength_balance 下（09-26 起）
    lq = rs.get("license_questions") or {}
    rub = (rs.get("rubric") or {}).get("items") or {}
    cap = rs.get("captured_at") or rs.get("researched_at")
    # 翻车面标签：strength_balance.underdog_path.strength（09-26 起契约字段）；
    # 09-26 前的旧研究没有这一块，才用牌照 q2_route 作代理（机械派生，upset_label_src 标明）
    if up.get("strength"):
        label, label_src = up.get("strength"), "underdog_path.strength"
    elif "q2_route" in lq:
        label, label_src = (
            ("real" if lq.get("q2_route") else "weak"),
            "derived:license_questions.q2_route",
        )
    else:
        label, label_src = None, None
    return {
        "schema": "codex"
        if "my_action" in rs
        else ("v0" if "collapse_two_columns" in rs else ("v1" if "stance" not in rs else "v2")),
        "captured_at": cap,
        "prospective": prospective(cap, kickoff),
        "anchor_side": rs.get("anchor_side") or rs.get("anchor"),
        "anchor_integrity": rs.get("anchor_integrity"),
        "hole": hole_from_research(rs, fav_side),
        "verdict": sb.get("verdict"),
        "stance_face": st.get("face"),
        "stance_cover": st.get("cover"),
        "stance_structure": st.get("structure"),
        "stance_alt": st.get("alt_face"),
        "market_read": st.get("market_read"),
        "confidence": st.get("confidence", rs.get("confidence")),
        "tilt_zeroed": st.get("tilt_zeroed"),
        "license_questions": {
            k: lq.get(k)
            for k in (
                "q1_spine",
                "q2_route",
                "q3a_opponent_scores",
                "q3b_opponent_takes_points",
                "q4_no_context_flag",
            )
        }
        if lq
        else None,
        "death_proofs": {
            f: (d3.get(KEY[f]) or {}).get("proof_count") or (d3.get(KEY[f]) or {}).get("proofs_met")
            for f in FACES
        }
        if d3
        else None,
        "directional_flags": rs.get("directional_flags"),
        "nondirectional_flags": rs.get("nondirectional_flags"),
        "crash_markers": rs.get("crash_markers"),
        "team_tags": rs.get("team_tags"),
        "upset_label": label,
        "upset_label_src": label_src,
        "underdog_path_side": up.get("side"),
        "underdog_routes": (up.get("routes") or [])[:4],
        "rubric": {
            k: {
                "p": v.get("p"),
                "answer": v.get("answer"),
                "abstain": v.get("abstain"),
                "tier": v.get("source_tier"),
            }
            for k, v in rub.items()
        }
        if rub
        else None,
        "rubric_abstain_n": sum(1 for v in rub.values() if v.get("abstain")) if rub else None,
        "premise_corrections_n": len(rs.get("premise_corrections") or []),
        "schedule": rs.get("schedule"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default="2026-05-18")
    ap.add_argument("--to", dest="d1", default="2026-10-18")
    a = ap.parse_args()

    R = load(f"{D}/jczq/jc-results.json") or {}
    OFF = load(f"{D}/zucai/official-results.json") or {}
    rows = {}  # key → row
    by_date_names = {}  # (date, home2, away2) → key for zucai dedup
    titan_index = {}  # titan007 match_id → key（竞彩∪足彩去重的第二把钥匙）

    # ---------------- 竞彩板 ----------------
    for day in sorted(os.listdir(f"{D}/jczq/daily")):
        if not (a.d0 <= day <= a.d1):
            continue
        d = f"{D}/jczq/daily/{day}"
        res = R.get(day) or {}
        co = load(f"{d}/closing_odds.json") or {}
        bo = load(f"{d}/bold_odds.json") or {}
        # 体彩板面：队名 / 联赛 / 开球 / 体彩 HAD 赔率
        # （05-18 起每天都有，是 09-19 前唯一的队名来源）
        sp = {}
        sm = load(f"{d}/sporttery_markets.json") or {}
        for blk in sm.get("matchInfoList") or []:
            for y in blk.get("subMatchList") or []:
                c = y.get("matchNumStr")
                if not c:
                    continue
                had = y.get("had") or {}
                try:
                    hadp = (
                        devig(
                            {
                                "home": float(had.get("h")),
                                "draw": float(had.get("d")),
                                "away": float(had.get("a")),
                            }
                        )
                        if had.get("h")
                        else None
                    )
                except Exception:
                    hadp = None
                sp[c] = {
                    "home": y.get("homeTeamAbbName"),
                    "away": y.get("awayTeamAbbName"),
                    "league": y.get("leagueAbbName"),
                    "kickoff": f"{y.get('matchDate')}T{y.get('matchTime')}+08:00"
                    if y.get("matchDate") and y.get("matchTime")
                    else None,
                    "had": hadp,
                    "had_updated": f"{had.get('updateDate')} {had.get('updateTime')}"
                    if had.get("updateDate")
                    else None,
                    "titan": None,
                }
        lb = load(f"{d}/jczq-legs-base.json")
        legs = (lb.get("legs") or lb) if isinstance(lb, dict) else {}
        if isinstance(legs, list):
            legs = {(lg.get("code") or lg.get("key")): lg for lg in legs}
        rd = load(f"{d}/reads.json")
        reads = rd if isinstance(rd, list) else (list(rd.values()) if isinstance(rd, dict) else [])
        mid2code = {
            v.get("match_id"): k
            for k, v in legs.items()
            if isinstance(v, dict) and v.get("match_id")
        }
        reads_by_code = {}
        for x in reads:
            if not isinstance(x, dict):
                continue
            c = x.get("code") or mid2code.get(x.get("match_id"))
            if c:
                reads_by_code[c] = x
        tl = load(f"{d}/team-load.json")
        load_by = {}
        trows = (tl or {}).get("rows") or []
        for r in trows.values() if isinstance(trows, dict) else trows:
            if isinstance(r, dict):
                load_by[r.get("key", "").split("-")[-1]] = r
                if r.get("match_id"):
                    load_by[r["match_id"]] = r
        ov = Counter()
        if os.path.exists(f"{d}/overrides.jsonl"):
            for line in open(f"{d}/overrides.jsonl", encoding="utf-8"):
                try:
                    o = json.loads(line)
                    ov[str(o.get("match") or o.get("code") or "").split()[0]] += 1
                except Exception:
                    pass
        pm_by = {}
        pm = load(f"{d}/polymarket.json")
        if pm and pm.get("snapshots"):
            snap = pm["snapshots"][-1]
            prow = snap.get("rows") or {}
            items = (
                prow.items()
                if isinstance(prow, dict)
                else [((r or {}).get("code") or (r or {}).get("key"), r) for r in prow]
            )
            for c, r in items:
                if not isinstance(r, dict) or not c:
                    continue
                pm_by[str(c).split("-")[-1]] = {
                    "volume": r.get("volume"),
                    "volume24h": r.get("volume24hr"),
                    "rank": r.get("rank"),
                    "pm": tri(r.get("probs")) if r.get("probs") else None,
                    "vs_market_pp": r.get("vs_market_pp"),
                    "fetched_at": snap.get("fetched_at"),
                }
        codes = set(res) | set(co) | set(legs) | set(reads_by_code) | set(bo)
        for code in sorted(c for c in codes if c and re.match(r"周[一二三四五六日]\d{3}$", c)):
            leg = legs.get(code) or {}
            s_ = sp.get(code) or {}
            kickoff = leg.get("kickoff_bj") or s_.get("kickoff")
            mid = leg.get("match_id") or (reads_by_code.get(code) or {}).get("match_id")
            key = mid or f"{day}|{code}"
            row = rows.setdefault(
                key,
                {
                    "key": key,
                    "match_id": mid,
                    "date": day,
                    "jczq_code": code,
                    "zucai": None,
                    "home": leg.get("home_team") or s_.get("home"),
                    "away": leg.get("away_team") or s_.get("away"),
                    "competition": leg.get("competition") or s_.get("league"),
                    "kickoff": kickoff,
                    "src": ["jczq"],
                },
            )
            if s_.get("had"):
                row["price_sporttery"] = {
                    "fair": s_["had"],
                    "updated": s_.get("had_updated"),
                    "src": "sporttery_markets.had",
                }
            titan = (co.get(code) or {}).get("match_id")
            if titan:
                row["titan_id"] = str(titan)
                titan_index[str(titan)] = key
            # 赛果
            rr = res.get(code)
            if isinstance(rr, dict) and rr.get("ft_home") is not None:
                row["result"] = {
                    "ft": [rr["ft_home"], rr["ft_away"]],
                    "ht": [rr.get("ht_home"), rr.get("ht_away")],
                    "face": "3"
                    if rr["ft_home"] > rr["ft_away"]
                    else ("1" if rr["ft_home"] == rr["ft_away"] else "0"),
                    "src": "jc-results",
                }
            # 价格：终盘/开盘（titan007 sharp）、读判时（15 家）
            c = (co.get(code) or {}).get("sharp") or {}
            if c:
                row["price_closing"] = {
                    "fair": devig(c.get("odds")),
                    "opening": devig(c.get("opening_odds")),
                    "books": c.get("bookmaker_count"),
                    "fetched_at": (co.get(code) or {}).get("fetched_at"),
                    "src": "closing_odds.sharp",
                }
            b = (bo.get(code) or {}).get("match_winner") or {}
            if b:
                row["price_read_time"] = {
                    "fair": tri(b.get("fair_probability")),
                    "opening": devig(b.get("opening_odds")),
                    "books": b.get("bookmaker_count"),
                    "src": "bold_odds",
                }
            # 判读 belief / 市场 prior
            x = reads_by_code.get(code)
            if x and x.get("belief"):
                row["belief"] = {
                    "system": tri(x["belief"]),
                    "market": tri(x.get("prior")),
                    "judge": x.get("judge"),
                    "tier": x.get("judgment_tier"),
                    "made_at": x.get("made_at"),
                    "prospective": prospective(x.get("made_at"), kickoff),
                    "src": "reads.json",
                }
            # 研究原件
            rs = load(f"{d}/research-{code}.json")
            m = (
                row.get("belief", {}).get("market")
                or (row.get("price_read_time") or {}).get("fair")
                or (row.get("price_closing") or {}).get("fair")
            )
            fav = fav_of(m)
            if rs:
                row["research"] = research_block(rs, fav, kickoff)
                row["research"]["src"] = f"jczq/daily/{day}/research-{code}.json"
            elif leg.get("_hole") or leg.get("anchor_integrity"):
                row["research"] = research_block(
                    {
                        **leg,
                        "hole_location": leg.get("_hole"),
                        "stance": leg.get("research_stance") or leg.get("stance") or {},
                        "death_three_proofs": leg.get("_d3") or {},
                    },
                    fav,
                    kickoff,
                )
                row["research"]["src"] = f"jczq/daily/{day}/jczq-legs-base.json"
            rb = load(f"{d}/rubric-{code}.json")
            if rb and rb.get("kappa") is not None:
                row["reader_b"] = {
                    "kappa": rb.get("kappa"),
                    "at": rb.get("at"),
                    "prospective": rb.get("prospective"),
                }
            if code in load_by or (mid and mid in load_by):
                r = load_by.get(code) or load_by.get(mid)
                row["load"] = {
                    "home": r.get("home_load"),
                    "away": r.get("away_load"),
                    "rest_diff": r.get("rest_diff"),
                    "load_diff_14": r.get("load_diff_14"),
                    "flags": r.get("flags"),
                    "captured_at": r.get("captured_at"),
                }
            if code in pm_by:
                row["polymarket"] = pm_by[code]
            if ov.get(code):
                row["overrides_n"] = ov[code]
            if row.get("home") and row.get("away"):
                by_date_names[(day, row["home"][:2], row["away"][:2])] = key

    # ---------------- 足彩期次 ----------------
    for p in sorted(glob.glob(f"{D}/zucai/*-legs-base.json")):
        issue = os.path.basename(p)[:5]
        lb = load(p)
        legs = lb.get("legs") or lb
        legs = list(legs.values()) if isinstance(legs, dict) else legs
        iss = load(f"{D}/zucai/{issue}-issue.json") or {}
        imatch = {m.get("match_no"): m for m in iss.get("matches") or []}
        deadline = (iss.get("sale_deadline") or "")[:10]
        if not legs or not (a.d0 <= (deadline or "2026-01-01") <= a.d1):
            continue
        draw = (OFF.get(issue) or "").split()
        cm = (
            load(f"{D}/zucai/{issue}-channel-map.json")
            or load(f"{D}/zucai/{issue}-channel-map.auto.json")
            or {}
        )
        no2mid = {v: k for k, v in cm.items()} if isinstance(cm, dict) else {}
        sid = load(f"{D}/zucai/{issue}-store-ids.json") or {}
        for no, v in sid.items() if isinstance(sid, dict) else []:
            if isinstance(v, dict) and str(v.get("match_id", "")).startswith("match-"):
                no2mid.setdefault(int(no) if str(no).isdigit() else no, v["match_id"])
            elif isinstance(v, str) and v.startswith("match-"):
                no2mid.setdefault(int(no) if str(no).isdigit() else no, v)
        co = load(f"{D}/zucai/{issue}-closing-odds.json") or {}
        oi = load(f"{D}/zucai/{issue}-odds-intl.json") or {}
        intl = {m.get("match_no"): m for m in (oi.get("matches") or []) if isinstance(m, dict)}
        for k, leg in enumerate(legs, 1):
            im = imatch.get(k, {})
            date = im.get("match_date") or deadline
            kickoff = im.get("kickoff_bj")
            if kickoff and "T" not in kickoff:
                kickoff = kickoff.replace(" ", "T") + "+08:00"
            mid = leg.get("match_id") or no2mid.get(k)
            titan = str(
                (co.get(str(k)) or co.get(k) or {}).get("match_id")
                or (intl.get(k) or {}).get("titan007_match_id")
                or ""
            )
            jcode = (intl.get(k) or {}).get("jczq_match_no")
            nm_key = by_date_names.get(
                (
                    date,
                    (im.get("home_team") or leg.get("name", ""))[:2],
                    (im.get("away_team") or "")[:2],
                )
            )
            key = (
                (mid if mid in rows else None)
                or titan_index.get(titan)
                or (rows.get(f"{date}|{jcode}") or {}).get("key")
                or nm_key
                or mid
                or f"z{issue}-{k:02d}"
            )
            row = rows.get(key)
            if row is None:
                row = rows[key] = {
                    "key": key,
                    "match_id": mid,
                    "date": date,
                    "jczq_code": None,
                    "home": im.get("home_team"),
                    "away": im.get("away_team"),
                    "competition": im.get("competition"),
                    "kickoff": kickoff,
                    "src": [],
                }
            row["src"] = sorted(set(row["src"]) | {"zucai"})
            row["zucai"] = {"issue": issue, "no": k, "deadline": iss.get("sale_deadline")}
            if k <= len(draw) and draw[k - 1] in FACES and "result" not in row:
                row["result"] = {
                    "ft": None,
                    "ht": None,
                    "face": draw[k - 1],
                    "src": "zucai-official",
                }
            sysb, mkt = tri(leg.get("fair")), tri(leg.get("prior"))
            if mkt and "belief" not in row:
                row["belief"] = {
                    "system": sysb,
                    "market": mkt,
                    "judge": "zucai-legs-base",
                    "tier": leg.get("judgment_tier"),
                    "made_at": leg.get("judged_at"),
                    "prospective": None,
                    "src": f"zucai/{issue}-legs-base.json",
                }
            c = (co.get(str(k)) or co.get(k) or {}).get("sharp") or {}
            if c and "price_closing" not in row:
                row["price_closing"] = {
                    "fair": devig(c.get("odds")),
                    "opening": devig(c.get("opening_odds")),
                    "books": c.get("bookmaker_count"),
                    "fetched_at": (co.get(str(k)) or {}).get("fetched_at"),
                    "src": f"zucai/{issue}-closing-odds.sharp",
                }
            o = intl.get(k) or {}
            if o.get("micro"):
                row["intl_drift"] = {
                    kk: vv
                    for kk, vv in o["micro"].items()
                    if kk.startswith("drift") or kk == "dispersion_pp"
                }
                row["intl_drift"]["captured_at"] = oi.get("captured_at")
                if "price_closing" not in row and o.get("odds"):
                    row["price_closing"] = {
                        "fair": devig(o["odds"]),
                        "opening": devig(o.get("opening_odds")),
                        "books": o.get("books"),
                        "fetched_at": oi.get("captured_at"),
                        "src": f"zucai/{issue}-odds-intl",
                    }
            fav = fav_of(mkt or (row.get("price_closing") or {}).get("fair"))
            rs = None
            for rp in glob.glob(f"{D}/zucai/{issue}-research-m{k}.json"):
                rs = load(rp)
            if rs and "research" not in row:
                row["research"] = research_block(rs, fav, kickoff)
                row["research"]["src"] = f"zucai/{issue}-research-m{k}.json"
            elif "research" not in row and (leg.get("_hole") or leg.get("anchor_integrity")):
                row["research"] = research_block(
                    {
                        **leg,
                        "hole_location": leg.get("_hole"),
                        "stance": leg.get("research_stance") or {},
                        "death_three_proofs": {},
                    },
                    fav,
                    kickoff,
                )
                row["research"]["src"] = f"zucai/{issue}-legs-base.json"
            rb = load(f"{D}/zucai/{issue}-rubric-m{k}.json")
            if rb and rb.get("kappa") is not None and "reader_b" not in row:
                row["reader_b"] = {
                    "kappa": rb.get("kappa"),
                    "at": rb.get("at"),
                    "prospective": rb.get("prospective"),
                }

    # ---- corpus-v2 兜底（内核 forecast lane 的 belief / 赛果，05-18 起）----
    cv = load("experiments/corpus-v2.json") or {}
    for cr in cv.get("rows") or []:
        keys = [
            f"{cr.get('date')}|{tk.split('-', 3)[-1]}" for tk in (cr.get("twin_keys") or []) if tk
        ]
        if cr.get("src") == "jczq" and cr.get("key"):
            keys.append(f"{cr['date']}|{cr['key'].split('-', 3)[-1]}")
        mid = (cr.get("kernel") or {}).get("match_id")
        if mid:
            keys.append(mid)
        for k in keys:
            row = rows.get(k)
            if not row:
                continue
            if "belief" not in row and cr.get("fair") and cr.get("belief"):
                row["belief"] = {
                    "system": tri(cr["belief"]),
                    "market": tri(cr["fair"]),
                    "judge": "corpus-v2:" + str(cr.get("fair_source")),
                    "tier": None,
                    "made_at": cr.get("judged_at_declared"),
                    "prospective": cr.get("provably_prospective"),
                    "src": "experiments/corpus-v2.json",
                }
            if "result" not in row and cr.get("actual") in FACES:
                row["result"] = {
                    "ft": None,
                    "ht": None,
                    "face": cr["actual"],
                    "src": "corpus-v2.actual",
                }
            if not row.get("match_id") and mid:
                row["match_id"] = mid
            break

    # ---------------- 派生列 ----------------
    out = []
    for row in rows.values():
        m = (
            (row.get("belief") or {}).get("market")
            or (row.get("price_read_time") or {}).get("fair")
            or (row.get("price_closing") or {}).get("fair")
        )
        s = (row.get("belief") or {}).get("system")
        fav = fav_of(m)
        der = {"fav": fav, "p_fav": m[fav] if m else None}
        if m:
            p = m[fav]
            der["band"] = (
                "A≥80"
                if p >= 0.8
                else (
                    "B65–79"
                    if p >= 0.65
                    else ("b57–64" if p >= 0.57 else ("C45–56" if p >= 0.45 else "D<45"))
                )
            )
        if m and s:
            der["sys_delta_fav_pp"] = round((s[fav] - m[fav]) * 100, 2)
            der["sys_moved"] = abs(s[fav] - m[fav]) > 0.005
        pc = row.get("price_closing") or {}
        if pc.get("fair") and pc.get("opening") and fav:
            der["drift_fav_pp"] = round((pc["fair"][fav] - pc["opening"][fav]) * 100, 2)
        rs = row.get("research") or {}
        if rs.get("underdog_path_side") in ("home", "away") and fav:
            der["underdog_is_market_dog"] = (rs["underdog_path_side"] == "home") != (fav == "3")
        if rs.get("hole"):
            der["hole_rel"], der["hole_unit"], der["hole_priced"] = (
                rs["hole"]["rel"],
                rs["hole"]["unit"],
                rs["hole"]["priced_in"],
            )
        if row.get("result"):
            der["fav_hit"] = row["result"]["face"] == fav if fav else None
            der["stance_hit"] = (
                (row["result"]["face"] == rs.get("stance_face"))
                if rs.get("stance_face") in FACES
                else None
            )
        row["derived"] = der
        out.append(row)
    out.sort(
        key=lambda r: (r["date"], r.get("jczq_code") or "", (r.get("zucai") or {}).get("no") or 0)
    )
    os.makedirs("experiments", exist_ok=True)
    with open("experiments/decision-samples-v1.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---------------- 覆盖报告 ----------------
    def cov(name, pred):
        xs = [r["date"] for r in out if pred(r)]
        return f"| {name} | {len(xs)} | {min(xs) if xs else '—'} | {max(xs) if xs else '—'} |"

    lines = [
        f"# decision-samples-v1 覆盖报告（构建 {datetime.now().isoformat(timespec='minutes')}"
        f"；窗口 {a.d0}→{a.d1}）",
        "",
        f"总行数 {len(out)}（竞彩 {sum('jczq' in r['src'] for r in out)}"
        f" / 足彩 {sum('zucai' in r['src'] for r in out)}"
        f" / 两者 {sum(len(r['src']) == 2 for r in out)}）",
        "",
        "| 列 | 非空 n | 首日 | 末日 |",
        "|---|---|---|---|",
        cov("赛果 result", lambda r: r.get("result")),
        cov("终盘/开盘价 price_closing", lambda r: (r.get("price_closing") or {}).get("fair")),
        cov(
            "读判时 15 家价 price_read_time", lambda r: (r.get("price_read_time") or {}).get("fair")
        ),
        cov("体彩 HAD 价 price_sporttery", lambda r: (r.get("price_sporttery") or {}).get("fair")),
        cov("队名 home/away", lambda r: r.get("home") and r.get("away")),
        cov("belief.market", lambda r: (r.get("belief") or {}).get("market")),
        cov("belief.system ≠ market", lambda r: (r.get("derived") or {}).get("sys_moved")),
        cov("research（任一 schema）", lambda r: r.get("research")),
        cov("research.anchor_side", lambda r: (r.get("research") or {}).get("anchor_side")),
        cov(
            "research.anchor_integrity", lambda r: (r.get("research") or {}).get("anchor_integrity")
        ),
        cov(
            "research.hole（v1 旧 schema）",
            lambda r: ((r.get("research") or {}).get("hole") or {}).get("schema") == "v1",
        ),
        cov(
            "research.hole（v2 side/unit/priced）",
            lambda r: ((r.get("research") or {}).get("hole") or {}).get("schema") == "v2",
        ),
        cov("research.verdict（强弱天平）", lambda r: (r.get("research") or {}).get("verdict")),
        cov("research.stance_face", lambda r: (r.get("research") or {}).get("stance_face")),
        cov(
            "research.license_questions",
            lambda r: (r.get("research") or {}).get("license_questions"),
        ),
        cov("research.death_proofs", lambda r: (r.get("research") or {}).get("death_proofs")),
        cov(
            "research.upset_label（原字段）",
            lambda r: (r.get("research") or {}).get("upset_label_src") == "underdog_path.strength",
        ),
        cov(
            "research.upset_label（q2_route 代理）",
            lambda r: str((r.get("research") or {}).get("upset_label_src", "")).startswith(
                "derived"
            ),
        ),
        cov("research.rubric r1", lambda r: (r.get("research") or {}).get("rubric")),
        cov(
            "research.prospective=True",
            lambda r: (r.get("research") or {}).get("prospective") is True,
        ),
        cov("reader_b.kappa", lambda r: r.get("reader_b")),
        cov("intl_drift（足彩国际盘位移）", lambda r: r.get("intl_drift")),
        cov("polymarket", lambda r: r.get("polymarket")),
        cov("load（损耗台账）", lambda r: r.get("load")),
        cov("overrides_n", lambda r: r.get("overrides_n")),
        "",
        "## 行数按月",
        "",
    ]
    bym = Counter(r["date"][:7] for r in out)
    lines += [f"- {k}: {v}" for k, v in sorted(bym.items())]
    sch = Counter((r.get("research") or {}).get("schema") for r in out if r.get("research"))
    lines += [
        "",
        f"research schema 分布：{dict(sch)}",
        "",
        "## 纪律",
        "",
        "- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，"
        "None＝缺采集时刻或开球时刻。",
        "- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；"
        "`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。",
        "- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。",
    ]
    with open("experiments/decision-samples-v1.coverage.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
