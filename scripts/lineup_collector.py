"""赛前首发采集器（真外生特征的唯一来源）

设计要点——**泄漏可证伪**：每条记录都带 `captured_at` 与 `minutes_before_kickoff`，
只有 minutes_before_kickoff > 0 的记录才可用作赛前特征。采集为 append-only，
同一场多次抓取各留一份（首发会改，早抓的那份本身也是信息）。

用法:
  uv run python scripts/lineup_collector.py scan --date 2026-09-15 --window 120
  uv run python scripts/lineup_collector.py rotation --team-id 529
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".nutmeg-data", "lineups")


def _env(key, default=""):
    v = os.environ.get(key)
    if v:
        return v
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for ln in open(p):
            if ln.strip().startswith(key + "="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return default


CALLS = {"n": 0}
MAX_CALLS = 40          # 免费档日配额有限,硬性上限,超了就停
SLEEP_S = 1.5           # 每次调用间隔,避免 429


def api(path, *, allow_fail=True):
    """带配额上限与 429 优雅降级的取数。超限返回 None 而不是崩。"""
    if CALLS["n"] >= MAX_CALLS:
        print(f"  ⚠️ 已达本次运行调用上限 {MAX_CALLS}，停止取数")
        return None
    base = _env("NUTMEG_API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io")
    req = urllib.request.Request(base.rstrip("/") + path,
                                 headers={"x-apisports-key": _env("NUTMEG_API_FOOTBALL_KEY")})
    try:
        CALLS["n"] += 1
        r = json.load(urllib.request.urlopen(req, timeout=30))
        time.sleep(SLEEP_S)
        return r
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("  ⚠️ HTTP 429 配额耗尽，本次采集提前结束（已抓到的仍已落盘）")
            CALLS["n"] = MAX_CALLS
            return None
        if allow_fail:
            print(f"  ⚠️ HTTP {e.code} {path}")
            return None
        raise


def fixtures_for(date):
    """当日赛程，落盘缓存，每天只调一次 API。"""
    cache = os.path.join(OUT, "_fixtures", f"{date}.json")
    if os.path.exists(cache):
        return json.load(open(cache)).get("response") or []
    d = api(f"/fixtures?date={date}")
    if d is None:
        return []
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(d, open(cache, "w"), ensure_ascii=False)
    return d.get("response") or []


def board_fixture_ids(issue=None):
    """当期足彩盘面的 API-Football fixture id，来自 `{issue}-af-map.json`。

    这是唯一可靠的中↔英连接点(队名匹配不可靠)。af-map 缺失时返回 None，
    调用方据此决定是放弃盘面限定还是跳过——**不猜**。
    """
    zc = os.path.join(ROOT, ".nutmeg-data", "zucai")
    files = sorted(f for f in os.listdir(zc) if f.endswith("-af-map.json"))
    if issue:
        files = [f for f in files if f.startswith(issue)]
    if not files:
        return None
    try:
        fx = json.load(open(os.path.join(zc, files[-1]))).get("fixtures") or {}
    except Exception:
        return None
    ids = {int(v) for v in fx.values() if str(v).isdigit()}
    return ids or None


def scan(date, window_min, board_only=True, issue=None):
    """抓 date 当天、距开球 window_min 分钟以内的比赛首发。

    board_only=True 时只抓当期足彩盘面上的队（免费档配额有限，不许全量扫）。
    """
    now = dt.datetime.now(dt.UTC)
    fx = fixtures_for(date)
    want = board_fixture_ids(issue) if board_only else None
    if board_only and want is None:
        print("  ⚠️ 未找到 af-map.json，无法做盘面限定。"
              "加 --all 可全量扫（会烧配额），或先跑 zucai 的身份映射生成 af-map。")
        return 0
    if want:
        print(f"  盘面限定: {len(want)} 场 (来自 af-map)")
    due, got, skipped = 0, 0, 0
    for f in fx:
        fid = f["fixture"]["id"]
        ko = dt.datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
        mins = (ko - now).total_seconds() / 60
        if not (-15 <= mins <= window_min):      # 未到窗口 或 早已开赛
            skipped += 1
            continue
        if want is not None and fid not in want:
            skipped += 1
            continue
        due += 1
        r0 = api(f"/fixtures/lineups?fixture={fid}")
        if r0 is None:
            break
        lu = r0.get("response") or []
        if not lu:
            continue
        d = os.path.join(OUT, date)
        os.makedirs(d, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        rec = {
            "fixture_id": fid,
            "kickoff_utc": f["fixture"]["date"],
            "captured_at_utc": now.isoformat(timespec="seconds"),
            "minutes_before_kickoff": round(mins, 1),   # >0 才可用作赛前特征
            "league": f["league"]["name"], "league_id": f["league"]["id"],
            "home": f["teams"]["home"]["name"], "home_id": f["teams"]["home"]["id"],
            "away": f["teams"]["away"]["name"], "away_id": f["teams"]["away"]["id"],
            "lineups": [{
                "team_id": t["team"]["id"], "team": t["team"]["name"],
                "formation": t.get("formation"),
                "coach": (t.get("coach") or {}).get("name"),
                "xi": [{"id": p["player"]["id"], "name": p["player"]["name"],
                        "pos": p["player"].get("pos"), "no": p["player"].get("number")}
                       for p in (t.get("startXI") or [])],
                "bench": [p["player"]["id"] for p in (t.get("substitutes") or [])],
            } for t in lu],
        }
        path = os.path.join(d, f"{fid}-{stamp}.json")
        json.dump(rec, open(path, "w"), ensure_ascii=False, indent=1)
        got += 1
    print(f"{date}: 窗口内 {due} 场 / 抓到首发 {got} 场 / 窗口外跳过 {skipped}")
    return got


def _history():
    """→ {team_id: [(kickoff, xi_ids, formation, minutes_before), ...]} 按时间升序"""
    h = {}
    for root, _dirs, files in os.walk(OUT):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                r = json.load(open(os.path.join(root, fn)))
            except Exception:
                continue
            for t in r.get("lineups") or []:
                h.setdefault(t["team_id"], []).append(
                    (r["kickoff_utc"], {p["id"] for p in t["xi"]},
                     t.get("formation"), r.get("minutes_before_kickoff")))
    for k in h:
        h[k].sort()
    return h


def rotation(team_id=None):
    """轮换度 = 本场首发与上一场首发的重合人数(0-11)。需累积 ≥2 场才有值。"""
    h = _history()
    ids = [team_id] if team_id else sorted(h)
    for tid in ids:
        seq = h.get(int(tid)) or []
        if len(seq) < 2:
            print(f"  team {tid}: 仅 {len(seq)} 场，需 ≥2 场才能算轮换度")
            continue
        for i in range(1, len(seq)):
            keep = len(seq[i][1] & seq[i - 1][1])
            print(f"  team {tid} {seq[i][0][:10]}  与上一场重合 {keep}/11  "
                  f"阵型 {seq[i-1][2]}→{seq[i][2]}  赛前 {seq[i][3]}分钟抓取")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "rotation", "stats", "afmap"])
    ap.add_argument("--date", default=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"))
    ap.add_argument("--window", type=int, default=120)
    ap.add_argument("--team-id")
    ap.add_argument("--issue")
    ap.add_argument("--all", action="store_true", help="不限定盘面(会烧配额)")
    a = ap.parse_args()
    if a.cmd == "scan":
        scan(a.date, a.window, board_only=not a.all, issue=a.issue)
    elif a.cmd == "afmap":
        build_af_map(a.issue)
    elif a.cmd == "rotation":
        rotation(a.team_id)
    else:
        h = _history()
        n = sum(len(v) for v in h.values())
        pre = sum(1 for v in h.values() for x in v if (x[3] or 0) > 0)
        print(f"首发库: {len(h)} 支队 / {n} 条  其中赛前抓取(可用) {pre} 条")
        ready = sum(1 for v in h.values() if len(v) >= 2)
        print(f"可算轮换度的队(≥2场): {ready}")



# ──────────────── af-map 生成（match_no → fixture_id 的唯一合法来源）────────────────
def _alias_table(zucai_dir):
    """中文队名 → 英文名/别名。递归扫所有 analysis-evidence，找带 name_zh+name_en 的实体。"""
    out = {}

    def walk(o):
        if isinstance(o, dict):
            zh, en = o.get("name_zh"), o.get("name_en")
            if isinstance(zh, str) and isinstance(en, str) and zh and en:
                out.setdefault(zh, set()).add(en)
                for al in o.get("aliases") or []:
                    if isinstance(al, str) and al.isascii():
                        out[zh].add(al)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    import glob as _g
    for p in sorted(_g.glob(os.path.join(zucai_dir, "*-analysis-evidence.json")))[-6:]:
        try:
            walk(json.load(open(p)))
        except Exception:
            pass
    return {k: sorted(v) for k, v in out.items()}


def _by_kickoff(fx, kickoff_bj, tol_min=20):
    """按北京时间开球时刻 ±tol 过滤 API-Football 赛程(其 date 为 UTC ISO)。"""
    if not kickoff_bj:
        return None
    try:
        ko = dt.datetime.fromisoformat(kickoff_bj.replace("/", "-")).replace(
            tzinfo=dt.timezone(dt.timedelta(hours=8)))
    except Exception:
        return None
    out = []
    for f in fx:
        try:
            t = dt.datetime.fromisoformat(f["fixture"]["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        if abs((t - ko).total_seconds()) <= tol_min * 60:
            out.append(f)
    return out


def _en_names(zh, alias):
    """盘面中文简称 → 候选英文名。中文侧也要模糊匹配（盘面用简称,别名表用全称）。"""
    import difflib
    if zh in alias:
        return alias[zh] + [zh]
    # 子串双向
    cand = [k for k in alias if zh in k or k in zh]
    if not cand:
        cand = difflib.get_close_matches(zh, list(alias), n=2, cutoff=0.5)
    out = []
    for k in cand:
        out += alias[k]
    return (out or []) + [zh]


def build_af_map(issue, *, write=True):
    """把某期足彩 14 场对到 API-Football fixture_id。

    匹配依据 = 比赛日期 + 双方队名的英文/别名相似度。**不做模糊猜测**：
    低于阈值的场次留空并列出，由人工补，避免身份映射错配（26111 踩过这个坑）。
    """
    import difflib
    zc = os.path.join(ROOT, ".nutmeg-data", "zucai")
    iss_doc = json.load(open(os.path.join(zc, f"{issue}-issue.json")))
    matches = iss_doc.get("matches") or []
    alias = _alias_table(zc)
    out, unresolved = {}, []
    by_date = {}
    for m in matches:
        by_date.setdefault(m.get("match_date"), []).append(m)
    for date, ms in by_date.items():
        if not date:
            continue
        # ⚠️足彩 match_date 是北京业务日, API-Football 的 date 是 UTC:
        # 北京 00:00-08:00 开球的场次落在前一个 UTC 日。必须取并集。
        try:
            prev = (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
        except Exception:
            prev = None
        fx = list(fixtures_for(date))
        if prev:
            fx += list(fixtures_for(prev))
        if not fx:
            unresolved += [str(m.get("match_no")) for m in ms]
            continue
        for m in ms:
            no = str(m.get("match_no"))
            h, a = m.get("home_team") or "", m.get("away_team") or ""
            hs, as_ = _en_names(h, alias), _en_names(a, alias)
            # ⭐先用开球时刻硬过滤(±20min)，把候选从上千场缩到个位数，再比名字
            pool = _by_kickoff(fx, m.get("kickoff_bj")) or fx
            best, score = None, 0.0
            for f in pool:
                fh = f["teams"]["home"]["name"].lower()
                fa = f["teams"]["away"]["name"].lower()
                sh = max(difflib.SequenceMatcher(None, x.lower(), fh).ratio() for x in hs)
                sa = max(difflib.SequenceMatcher(None, x.lower(), fa).ratio() for x in as_)
                s = (sh + sa) / 2
                if s > score:
                    best, score = f, s
            if best and (score >= 0.55 or (len(pool) <= 3 and score >= 0.30)):
                out[no] = best["fixture"]["id"]
            else:
                unresolved.append(no)
    if write and out:
        p = os.path.join(zc, f"{issue}-af-map.json")
        prev = {}
        if os.path.exists(p):
            try:
                prev = json.load(open(p))
            except Exception:
                pass
        prev.setdefault("issue", issue)
        prev.setdefault("fixtures", {})
        prev["fixtures"].update({k: v for k, v in out.items()})
        prev["generated_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        json.dump(prev, open(p, "w"), ensure_ascii=False, indent=1)
    print(f"{issue}: 映射成功 {len(out)}/{len(matches)} 场"
          + (f"，未解析 {sorted(unresolved)} —— 需人工补" if unresolved else ""))
    return out, unresolved

if __name__ == "__main__":
    main()
