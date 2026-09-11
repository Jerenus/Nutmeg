"""候选构造器 —— 把"换这一场还是那一场"从七轮手工比较变成一次穷举。

**Why.** `zucai-optimize` 只比较**已经写好的**版本；构票时真正的问题是"在这个框架下还有哪些
版本"。26122 当天为了回答"9·31 换成 12·31 值多少"，我手写了七轮 `versions` 列表、每轮跑一次
optimizer——**同样的确定性算术被重复表达了七次**，而每次手写都是一次抄错面集合的机会。

与 optimizer 的分工不变：**本模块只穷举人已声明的有限空间**（每场允许哪些面集合由人写死），
不发明面、不推荐、不排除。宪法第二序（帽内最大化 P）只决定**展示顺序**，不决定选择——
选择永远是 Jun 的显式裁决。

安全阀：声明空间的笛卡尔积超过 `MAX_SEARCH_SPACE` 直接抛错，而不是静默截断——
截断会让"帽内第一"变成"搜索到的第一"，那是最隐蔽的一类错误。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from itertools import product

from nutmeg.decision.betslip import (
    PRICE_PER_NOTE,
    RENJIU_PICK,
    BetslipError,
    parse_faces,
    zucai_note_count,
)

MAX_SEARCH_SPACE = 200_000
DROP = ""          # 空面集合 = 丢整场（宪法允许的唯一压缩动作）
FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}


@dataclass(frozen=True)
class Candidate:
    faces: dict[str, str]
    notes: int
    cost: int
    p_all: float
    expected_broken: float
    in_cap: bool

    @property
    def signature(self) -> str:
        """内容签名：同 P 同价时的确定性排序键（禁止用字典顺序这种隐式规则）。"""
        return "|".join(f"{k}:{v}" for k, v in sorted(self.faces.items(),
                                                      key=lambda kv: int(kv[0])))


def _coverage(fair: dict, faces: str) -> float:
    return sum(fair[FACE_KEYS[c]] for c in set(faces))


def ticket_probability(faces: dict[str, str], fair: dict[str, dict]) -> float:
    """P(票面全对) —— 单一入口，避免调用方各自连乘（26122 手算过七次）。"""
    return reduce(lambda a, b: a * b,
                  (_coverage(fair[k], v) for k, v in faces.items() if v), 1.0)


def expected_broken_legs(faces: dict[str, str], fair: dict[str, dict]) -> float:
    return round(sum(1 - _coverage(fair[k], v) for k, v in faces.items() if v), 3)


def _space_size(options: dict[str, list[str]]) -> int:
    return reduce(lambda a, b: a * b, (len(v) for v in options.values()), 1)


def enumerate_candidates(
    options: dict[str, list[str]],
    fair: dict[str, dict],
    *,
    channel: str = "renjiu",
    cap_yuan: int | None = None,
    price: int = PRICE_PER_NOTE,
) -> list[Candidate]:
    """穷举声明空间内的全部票面。

    `options` = {场次: [允许的面集合...]}，`""` 表示"丢整场"这一选项。
    返回按**帽内 P 降序 → 票价升序 → 签名升序**排序的候选（帽外候选排在帽内之后，
    仍然返回——超帽是 Jun 的行权空间，不是程序的禁区）。
    """
    size = _space_size(options)
    if size > MAX_SEARCH_SPACE:
        raise BetslipError(
            f"声明空间 {size:,} 超过上限 {MAX_SEARCH_SPACE:,}；请收窄每场的允许面集合。"
            f"（静默截断会把「帽内第一」变成「搜到的第一」）")
    keys = sorted(options, key=lambda k: int(k))
    out: list[Candidate] = []
    for combo in product(*(options[k] for k in keys)):
        faces = {k: parse_faces(f) for k, f in zip(keys, combo, strict=True)}
        picked = {k: v for k, v in faces.items() if v}
        n_picked = len(picked)
        if channel == "renjiu" and n_picked < RENJIU_PICK:
            continue
        if channel == "shengfucai" and n_picked != len(keys):
            continue
        try:
            notes = zucai_note_count(picked, channel=channel)
        except BetslipError:
            continue
        cost = notes * price
        if channel == "renjiu" and n_picked > RENJIU_PICK:
            # 复式任九：P(至少中9场) 不是单一连乘，留给专门分支；这里只报最保守的全对口径。
            p = _p_renjiu_complex(picked, fair)
        else:
            p = reduce(lambda a, b: a * b,
                       (_coverage(fair[k], v) for k, v in picked.items()), 1.0)
        broken = sum(1 - _coverage(fair[k], v) for k, v in picked.items())
        out.append(Candidate(faces=picked, notes=notes, cost=cost,
                             p_all=round(p, 6), expected_broken=round(broken, 3),
                             in_cap=(cap_yuan is None or cost <= cap_yuan)))
    out.sort(key=lambda c: (not c.in_cap, -c.p_all, c.cost, c.signature))
    return out


def _p_renjiu_complex(faces: dict[str, str], fair: dict[str, dict]) -> float:
    """任九复式：P(所选场次中至少 9 场命中)。枚举场次子集，精确不近似。"""
    keys = sorted(faces, key=lambda k: int(k))
    covs = [_coverage(fair[k], faces[k]) for k in keys]
    n = len(covs)
    total = 0.0
    for mask in range(1 << n):
        hits = [bool(mask >> i & 1) for i in range(n)]
        if sum(hits) < RENJIU_PICK:
            continue
        p = 1.0
        for i in range(n):
            p *= covs[i] if hits[i] else (1 - covs[i])
        total += p
    return total


def swap_report(base: dict[str, str], options: dict[str, list[str]],
                fair: dict[str, dict], *, channel: str = "renjiu",
                price: int = PRICE_PER_NOTE) -> list[tuple[str, Candidate]]:
    """单点替换报告：从 `base` 出发，每次只改一场，看 P 怎么动。

    这是 26122 反复问的那个问题的直接答案（"9 换 12 值多少"），而且它把**同价对比**
    摆在同一张表里——只有同价对比才能分辨"更好的结构"与"更贵的结构"。
    """
    rows: list[tuple[str, Candidate]] = []
    for match_no, allowed in sorted(options.items(), key=lambda kv: int(kv[0])):
        for faces in allowed:
            normalized = parse_faces(faces)
            if base.get(match_no, "") == normalized:
                continue
            variant = dict(base)
            if normalized:
                variant[match_no] = normalized
            else:
                variant.pop(match_no, None)
            picked = {k: v for k, v in variant.items() if v}
            if channel == "renjiu" and len(picked) != RENJIU_PICK:
                continue
            try:
                notes = zucai_note_count(picked, channel=channel)
            except BetslipError:
                continue
            p = reduce(lambda a, b: a * b,
                       (_coverage(fair[k], v) for k, v in picked.items()), 1.0)
            broken = sum(1 - _coverage(fair[k], v) for k, v in picked.items())
            label = f"场{match_no} {base.get(match_no, '丢') or '丢'}→{normalized or '丢'}"
            rows.append((label, Candidate(
                faces=picked, notes=notes, cost=notes * price, p_all=round(p, 6),
                expected_broken=round(broken, 3), in_cap=True)))
    # 两点替换：丢一场、补一场（任九必须恰好 9 场，所以"9 换 12"只能成对发生）。
    # 26122 当天真正的问题就是这一类，而单点替换在任九里根本枚举不出它。
    in_ticket = [k for k, v in base.items() if v]
    for drop in in_ticket:
        for add, allowed in sorted(options.items(), key=lambda kv: int(kv[0])):
            if add in base and base[add]:
                continue
            for faces in allowed:
                normalized = parse_faces(faces)
                if not normalized:
                    continue
                variant = {k: v for k, v in base.items() if k != drop and v}
                variant[add] = normalized
                if channel == "renjiu" and len(variant) != RENJIU_PICK:
                    continue
                try:
                    notes = zucai_note_count(variant, channel=channel)
                except BetslipError:
                    continue
                label = (f"丢场{drop}({base[drop]}) ＋ 场{add}·{normalized}")
                rows.append((label, Candidate(
                    faces=variant, notes=notes, cost=notes * price,
                    p_all=round(ticket_probability(variant, fair), 6),
                    expected_broken=expected_broken_legs(variant, fair), in_cap=True)))
    rows.sort(key=lambda r: -r[1].p_all)
    return rows


def format_candidates(cands: list[Candidate], *, cap_yuan: int | None = None,
                      limit: int = 20) -> str:
    if not cands:
        return "(声明空间内无合法候选)"
    head = [f"候选穷举：{len(cands)} 个合法票面"
            + (f"（帽 ¥{cap_yuan:,}）" if cap_yuan else "")]
    head.append(f"{'票面':<44}{'注数':>7}{'票价':>9}{'P(全对)':>10}{'期望断腿':>9}  帽内")
    for c in cands[:limit]:
        head.append(f"{c.signature[:43]:<44}{c.notes:>7,}{'¥' + format(c.cost, ','):>9}"
                    f"{c.p_all * 100:>9.2f}%{c.expected_broken:>9.2f}  "
                    f"{'是' if c.in_cap else '否'}")
    if len(cands) > limit:
        head.append(f"…… 另 {len(cands) - limit} 个未显示")
    head.append("排序 = 帽内 P 降序 → 票价升序 → 签名升序；**这是比较顺序，不是推荐**。")
    return "\n".join(head)


def format_swaps(rows: list[tuple[str, Candidate]], base_p: float,
                 *, limit: int = 15) -> str:
    if not rows:
        return "(无可比较的单点替换)"
    out = [f"单点替换报告（基准 P={base_p * 100:.2f}%）：",
           f"{'替换':<28}{'注数':>7}{'票价':>9}{'P(全对)':>10}{'ΔP':>9}"]
    for label, c in rows[:limit]:
        out.append(f"{label:<28}{c.notes:>7,}{'¥' + format(c.cost, ','):>9}"
                   f"{c.p_all * 100:>9.2f}%{(c.p_all - base_p) * 100:>+8.2f}pp")
    out.append("同价行之间才可比；票价不同的 ΔP 里混着「更贵」而不只是「更好」。")
    return "\n".join(out)
