"""分析包旁车 `zucai/<期>-packet.json` 的读取（2026-10-27 产品形态第 1 阶段）。

§1 决策表的档 / 六条件 k/n / 默认 / 死门 / 停售前拿不到 / §1c / §1d 和 §2 主形只由
`/zucai-packet` 产出（六条件计数在代码里没有实现，页面绝不自算）；旁车是同一张表的结构化
副本。缺文件或缺字段写进 `errors` 让页面显示，从不抛——缺旁车不该让期页打不开。

## 旁车契约（`/zucai-packet` 出 A 三屏时用 Write 同写；改 §1 表必须同改旁车）

散文格怎么填以 `.claude/commands/zucai-packet.md` 为准，这里只定结构。文字格照抄 packet.md
那一格（可去掉加粗）；没有就给 `null`，不补算、不编。

**面的写法**：一律是 3/1/0 的不重复组合、按 `310` 顺序（`"3"` `"31"` `"30"` `"10"` `"310"`；
平负写 `"10"` 不写 `"01"`）。读取器逐个核对，不合规的写进 `errors`。

顶层：

- `issue` str 期号；`built_at` str ISO 时间带 +08:00（A 三屏出齐的时刻）。
- `default` {`action`: `"空仓"` | `"出票"`, `reason`: str}——§0/§2 的机器默认（如
  「许可证层：许可胆 0；账房越线 ¥690；刹车档」）。
- `rows` list，14 行（一场一行，见下）。
- `main_shape` {`label`, `faces`, `price`?, `p`?, `note`?}——§2 主形。**机器默认空仓时仍给字典
  主形**（§3b 差异格的对照对象）。`label` 如 `"W4 4单5双"`；`faces` {场号 str: 面}，丢的场不写
  （任九 9 个键，胜负彩 14 个）；`price` 元（int），`p` P(全对) 小数（0.0784），都是出包时
  `betslip preview` 的数，页面审票以 `/api/precheck` 重算为准。
- `alternatives` list，元素同 `main_shape` 再加 `role`：`"替代"`（命中/奖金装置，§2 那一张）|
  `"丢光C档"`（固定并排的对照形）| `"参考"`（并排表里其余形，可不写）。替代排第一个。
- `signed_bold` list of {`no`, `face`, `note`?}——§2 胆表里 Jun 签过的博胆；A 三屏出齐时恒为 `[]`。

每行（`rows[i]`）：

- 必填：`no` str 场号；`tier` `"A"|"B"|"b"|"C"|"D"`（按系统最大面切；锚方是客队也只写档）；
  `default` 任九默认面（单 `"3"`、双 `"31"`、全包 `"310"`、丢 `"丢"`）；`k` / `n` int——B/b 档
  六条件（n=6），C 档五条件（n=5），A 档七项（n=7）。**D 档 `k`/`n` 为 `null`**（表里是「—」），
  只有 D 档可缺。
- `cond` str 条件格逐条明细（「① ✗ 近 2 场失 7 ② ✓ …」）；`sfc_default` 胜负彩默认面，D 档
  「丢（任九）／胜负彩 31」写 `default: "丢", sfc_default: "31"`，与任九相同或未写给 `null`；
  `default_note` 默认动作格面以外的话（「盖平（研究 cover 1）」「标缺 ①④」「规则 b 不触发」）。
- `anchor` 锚方中轴；`hole` 洞在谁·单位（「锚方·门将·价内」）；`flip` 翻车面·标签（「卡利亚里·
  弱·价内·低位+定位球 → 1(19)」）；`consistency` 一致性（同向/中性/打架，可带括号说明）；
  `crowd` 人群格（无写 `null`）；`dead` 死门 P（「排 0 10」）；`converged` bool，
  `false`＝◇研究未收敛（10-27 覆盖门，只展示；没核给 `null`）。
- `watch` 赛前看谁；`lineup_at` 首发大约几点出（"HH:MM"，北京时间）；`lineup_before_close` bool
  首发是否停售前可见；`unknowable` 停售前拿不到的信息（§2 胆表那一格；不在胆表的行可 `null`）。
- `c1` §1c 翻车面解读那一行 {`path` 弱方·标签·价态 → 面(P)，`move` 弱方固定招，`q3a` 弱方能进球，
  `fav` 热门零封/失球，`weak_check` 标弱三项加查（标真实给 `null`）}；**D 档 `c1` 为 `null`**。
- `d1` §1d 结构对准那一行 {`cell` 格（档·洞位·价态·标签·单位），`layer` 落到哪层（照抄，如
  「档×洞位×价态」「五维全格」），`n` int，`open` 热/平/冷 「16/2/2」，`hot_pct` 热门开出 int，
  `p1` 市场 p1 int，`diff` 差 int（pp，可负）}；D 档也写。

页面只读这个文件，从不从 packet.md 散文反解析，也不重算许可证。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.betslip import BetslipError, parse_faces
from nutmeg.decision.files import read_json

REQUIRED = ("tier", "k", "n", "default")
NOT_SCORED = ("k", "n")
"""D 档不数条件：这两项可为 null。"""


def _face_error(face) -> str | None:
    """合规返回 None，否则返回该写成的规范面（不可解析时原样）。"""
    try:
        canon = parse_faces(str(face))
    except BetslipError:
        return str(face)
    return None if canon and canon == face else (canon or str(face))


def load_packet(data_dir: Path, issue: str) -> dict:
    name = f"{issue}-packet.json"
    doc = read_json(Path(data_dir) / "zucai" / name, None)
    if not isinstance(doc, dict):
        return {"issue": issue, "rows": [], "by_no": {}, "main_shape": None,
                "alternatives": [], "default": None, "signed_bold": [],
                "errors": [f"缺 {name}（/zucai-packet 未出旁车）"]}
    errors = []
    rows = sorted((r for r in doc.get("rows") or [] if isinstance(r, dict) and r.get("no")),
                  key=lambda r: int(r["no"]))
    for r in rows:
        need = [k for k in REQUIRED if not (r.get("tier") == "D" and k in NOT_SCORED)]
        missing = [k for k in sorted(need) if r.get(k) is None]
        if missing:
            errors.append(f"场 {r['no']} 缺字段：{'、'.join(missing)}")
        for key, what in (("default", "默认面"), ("sfc_default", "胜负彩默认面")):
            d = r.get(key)
            if d is not None and d != "丢" and (want := _face_error(d)) is not None:
                errors.append(f"场 {r['no']} {what} {d} 应写 {want}")
    alternatives = doc.get("alternatives") or []
    for shape in [doc.get("main_shape"), *alternatives]:
        if not isinstance(shape, dict):
            continue
        for no, face in (shape.get("faces") or {}).items():
            if (want := _face_error(face)) is not None:
                errors.append(f"{shape.get('label')} 场 {no} 面 {face} 应写 {want}")
    return {"issue": issue, "rows": rows, "by_no": {r["no"]: r for r in rows},
            "main_shape": doc.get("main_shape"), "alternatives": alternatives,
            "default": doc.get("default"), "signed_bold": doc.get("signed_bold") or [],
            "built_at": doc.get("built_at"), "errors": errors}


def check_delivery(data_dir: Path, issue: str) -> dict:
    """只读核验 A 三屏核心产物结构；不判许可、不审事实、不代表 B/C/D 完成。"""
    from nutmeg.decision.zucai_auto_judgment import market_gaps

    zdir = Path(data_dir) / "zucai"
    packet = load_packet(data_dir, issue)
    errors = list(packet["errors"])
    expected = {str(i) for i in range(1, 15)}
    nos = [str(r["no"]) for r in packet["rows"]]
    if len(nos) != len(set(nos)):
        errors.append("决策表场号重复")
    if set(nos) != expected:
        errors.append("决策表必须覆盖 1–14 场且不重复")
    for row in packet["rows"]:
        missing = [k for k in ("anchor", "hole", "flip", "cond", "watch", "d1")
                   if not row.get(k)]
        if row.get("tier") != "D" and not row.get("c1"):
            missing.append("c1")
        if missing:
            errors.append(f"场 {row['no']} 取证/分表缺：{'、'.join(missing)}")
    if not packet.get("default"):
        errors.append("缺机器默认及理由")
    shape = packet.get("main_shape")
    if not shape:
        errors.append("缺字典主形（默认空仓也应展示参考）")
    for candidate in ([shape] if shape else []) + packet["alternatives"]:
        faces = candidate.get("faces") or {}
        if len(faces) not in (9, 14) or not set(faces) <= expected:
            errors.append(f"{candidate.get('label', '主形')} 票面须为任九9场或胜负彩14场")
        if candidate.get("price") is None or candidate.get("p") is None:
            errors.append(f"{candidate.get('label', '主形')} 缺价格/P核算")
    if not any(s.get("role") == "替代" for s in packet["alternatives"]):
        errors.append("缺替代参考票")
    for suffix in ("packet.md", "judgment-brief.md", "draft.json", "counter-matrix.md",
                   "structure-align.md", "dead-align.md", "team-load.json", "polymarket.json"):
        path = zdir / f"{issue}-{suffix}"
        if not path.exists() or not path.stat().st_size:
            errors.append(f"缺产物 {path.name}")
    # 与自动转录使用同一研究定位（含并集竞彩），不要求复制研究文件。
    from nutmeg.decision.zucai_auto_judgment import _jczq_research_by_match_id, _research_path
    from nutmeg.decision.zucai_identity import load_channel_map

    doc = read_json(zdir / f"{issue}-issue.json", {}) or {}
    day = str(doc.get("sale_deadline") or "")[:10]
    mapped = {no: mid for mid, no in load_channel_map(zdir, issue).items()}
    jczq = _jczq_research_by_match_id(Path(data_dir), day) if day else {}
    missing_research = [no for no in sorted(expected, key=int)
                        if not _research_path(zdir, issue, no, mapped, jczq)]
    if missing_research:
        errors.append("缺逐场研究：" + ",".join(missing_research))
    gaps = market_gaps(issue=issue, data_dir=data_dir)
    store = read_json(zdir / f"{issue}-store-ids.json", {}) or {}
    for no in sorted(expected - set(store), key=int):
        gaps.setdefault(no, "缺 store-ids")
    if gaps:
        errors.append("市场输入缺口：" + "; ".join(f"场{n} {r}" for n, r in gaps.items()))
    return {"issue": issue, "ready": not errors, "errors": errors,
            "scope": ("A 三屏核心产物结构；事实、统计口径与页面仍须人工核验；"
                      "不表示桥/实购/复盘已完成")}
