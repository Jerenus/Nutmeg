"""白防线（2026-11-08 Jun 批：过度防御的缩减，预警多时提醒）。

一条双（一赔 + 二赔）里一赔开出的条件概率＝p1/(p1+p2)，它就是这条双的白防率：外部 13 季逐季
成立（0.80–0.85 段实开 83.4%、价 82.3%，最差一季 80.6%），不是近期正路多的假象。Jun 49 张任九
实票里线 0.80 以上的双 24 条白防 22 条，全改单省 22%、5 次全中一次没丢
（`experiments/prescreen/2026-11-08-white-line-regime.py`、`-white-defense.py`）。

这里只做算术与提醒，不改机器默认（规则 a 的许可证没动）：
- `reference`：白防线形——从全单开始，按一赔条件从低到高补双到预算（`budget`）；线以上的场留单。
  胜负彩就是 Jun 说的「14 场正路单选起步，按翻车风险慢慢补齐」。
- 研究预警 ≥2 条的线以上场单列提醒：项目样本里这类场 n=4 白防 3 次，n 太小，不进判据。
"""
from __future__ import annotations

from nutmeg.decision.faces import CODE_OF, FACE_OF, FACES

LINE = 0.80
WARN_MIN = 2
PRICE_PER_NOTE = 2
BUDGET_YUAN = 256
"""白防线形补双补到预算为止，不补到 ¥800 帽：¥256＝字典冷板默认形 2单7双 的价（126 期回测里
¥256 的中且回本 13 次，¥512 只 10 次）；期前定额或刹车更低时取更低的。"""
_PICK = {"renjiu": 9, "shengfucai": 14}
_SIDE = {"home": "3", "away": "0"}


def ratio(belief: dict) -> tuple[str, str, float]:
    """三面概率（home/draw/away）→ (一赔码, 二赔码, p1/(p1+p2))。"""
    top, second = sorted(FACES, key=lambda f: -float(belief[f]))[:2]
    p1, p2 = float(belief[top]), float(belief[second])
    return CODE_OF[top], CODE_OF[second], round(p1 / (p1 + p2), 4)


def warnings(raw: dict) -> list[str]:
    """legs-base 一场的研究预警（与热门方向不一致的读数）。"""
    fav = ratio(raw["fair"])[0]
    stance = raw.get("research_stance") or {}
    items = (raw.get("rubric") or {}).get("items") or {}
    hole = raw.get("_hole") or {}
    out = []
    if stance.get("face") in FACE_OF and stance["face"] != fav:
        out.append("研究不站热门")
    if stance.get("structure") == "double" or stance.get("cover") in FACE_OF:
        out.append("研究开双")
    if raw.get("anchor_integrity") == "fail":
        out.append("锚方 fail")
    if _SIDE.get(hole.get("side")) == fav and hole.get("priced_in") is False:
        out.append("锚方洞未价")
    if (items.get("S_crash_candidate") or {}).get("answer") == "yes":
        out.append("崩塌候选")
    if str((items.get("M_market_read") or {}).get("answer") or "").startswith("overpriced"):
        out.append("研究读高估")
    if (raw.get("license_questions") or {}).get("q5_no_rotation_window") is False:
        out.append("轮换窗口")
    return out


def _alert(no: str, belief: dict, raw: dict) -> dict | None:
    r = ratio(belief)[2]
    flags = warnings({**raw, "fair": raw.get("fair") or belief}) if r >= LINE else []
    return {"no": no, "ratio": r, "flags": flags} if len(flags) >= WARN_MIN else None


def budget(data_dir, issue: str) -> int:
    """白防线形的预算：¥256，期前定额 / 刹车（`bankroll.issue_brake`）的单票上限更低就取它。"""
    from nutmeg.decision.bankroll import issue_brake

    brake = issue_brake(data_dir, issue) if issue else None
    return min(BUDGET_YUAN, brake["slip_yuan"]) if brake else BUDGET_YUAN


def reference(legs: dict[str, dict], *, channel: str, cap_yuan: int) -> dict | None:
    """白防线形：`legs` 是 `zucai_draft.load_board` 的板（belief / raw）。"""
    need = _PICK.get(channel)
    if not need or len(legs) < need:
        return None
    chosen = sorted(legs, key=lambda no: (-max(legs[no]["belief"].values()), int(no)))[:need]
    shares = {no: ratio(legs[no]["belief"]) for no in chosen}
    faces = {no: shares[no][0] for no in chosen}
    notes, cap_notes, left = 1, cap_yuan // PRICE_PER_NOTE, []
    for no in sorted((no for no in chosen if shares[no][2] < LINE),
                     key=lambda no: (shares[no][2], int(no))):
        if notes * 2 > cap_notes:
            left.append(no)
            continue
        faces[no] = "".join(c for c in "310" if c in shares[no][:2])
        notes *= 2
    p_all = 1.0
    for no, fs in faces.items():
        p_all *= sum(legs[no]["belief"][FACE_OF[c]] for c in fs)
    alerts = [a for no in sorted(chosen, key=int)
              if (a := _alert(no, legs[no]["belief"], legs[no].get("raw") or {}))]
    return {"faces": dict(sorted(faces.items(), key=lambda kv: int(kv[0]))), "notes": notes,
            "stake_yuan": notes * PRICE_PER_NOTE, "p_all": round(p_all, 6),
            "dropped": sorted((no for no in legs if no not in faces), key=int), "alerts": alerts,
            "note": f"帽满：线下 {len(left)} 场留单（场 {'、'.join(sorted(left, key=int))}）"
                    if left else ""}


def reminder_lines(faces: dict[str, str], fair: dict[str, dict], raw: dict[str, dict], *,
                   stake_yuan: int) -> list[str]:
    """一张足彩票的白防提醒：线以上的双值多少钱、线以上的场有没有 ≥2 条研究预警。"""
    white, alerts = [], []
    for no in sorted(faces, key=int):
        if not fair.get(no):
            continue
        top, _, r = ratio(fair[no])
        if len(faces[no]) == 2 and top in faces[no] and r >= LINE:
            white.append(f"场 {no} 双 {faces[no]}（一赔条件 {r:.2f}）")
        alert = _alert(no, fair[no], raw.get(no) or {})
        if alert:
            alerts.append(f"⚠️预警 {len(alert['flags'])} 条在线以上：场 {no}（{r:.2f}）"
                          f"{'、'.join(alert['flags'])}——单还是双，开球前复核再定")
    lines = []
    if white:
        saved = stake_yuan - stake_yuan / 2 ** len(white)
        lines.append(f"ℹ️白防线 {LINE:.2f}：{'、'.join(white)}；这几条十次约八次用不上，"
                     f"全改单省 ¥{saved:,.0f}")
    return lines + alerts


def month_cost(slips: list, results: dict[str, list[str]]) -> dict:
    """账房「白防成本」：本月足彩实票里线以上的双多花了多少钱、已结的白防了几条。"""
    out = {"slips": 0, "doubles": 0, "extra_yuan": 0.0, "settled": 0, "white": 0}
    for slip in slips:
        if slip.channel not in _PICK:
            continue
        k = 0
        for leg in slip.legs:
            if not leg.fair or len(leg.selections) != 2:
                continue
            top, _, r = ratio(leg.fair)
            if r < LINE or top not in {CODE_OF[s] for s in leg.selections}:
                continue
            k += 1
            res = results.get(str(slip.issue))
            if res:
                out["settled"] += 1
                out["white"] += res[int(leg.key) - 1] == top
        if k:
            out["slips"] += 1
            out["doubles"] += k
            out["extra_yuan"] += slip.stake_yuan - slip.stake_yuan / 2 ** k
    out["extra_yuan"] = round(out["extra_yuan"], 2)
    return out
