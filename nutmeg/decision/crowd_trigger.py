"""人群假说的触发谓词：封闭字段集，粒度 = (场, 面)。不在集合里的字段一律拒绝（登记时就炸）。"""
from __future__ import annotations

from nutmeg.decision.crowd_source import FACES, CrowdMatch

FIELDS = frozenset({"face", "p_face", "p_home", "p_draw", "p_away", "fav_face", "is_fav",
                    "league", "league_group", "board_hot_count"})
OPS = frozenset({">=", "<=", "==", "in", "not_in"})
MAX_DEPTH = 2
HOT = 0.65


def validate(node: dict, depth: int = 0) -> None:
    if not isinstance(node, dict) or not node:
        raise ValueError(f"trigger 节点必须是非空对象：{node!r}")
    for key in ("all", "any"):
        if key in node:
            if depth >= MAX_DEPTH:
                raise ValueError(f"trigger 嵌套超过 {MAX_DEPTH} 层")
            kids = node[key]
            if not isinstance(kids, list) or not kids:
                raise ValueError(f"{key} 必须是非空列表")
            for kid in kids:
                validate(kid, depth + 1)
            return
    if "not" in node:
        if depth >= MAX_DEPTH:
            raise ValueError(f"trigger 嵌套超过 {MAX_DEPTH} 层")
        validate(node["not"], depth + 1)
        return
    if set(node) != {"field", "op", "v"}:
        raise ValueError(f"叶子必须恰为 field/op/v：{node!r}")
    if node["field"] not in FIELDS:
        raise ValueError(f"未知字段 {node['field']!r}；可用 {sorted(FIELDS)}")
    if node["op"] not in OPS:
        raise ValueError(f"未知运算符 {node['op']!r}；可用 {sorted(OPS)}")
    if node["op"] in ("in", "not_in") and not isinstance(node["v"], list):
        raise ValueError("in/not_in 的 v 必须是列表")


def facts(match: CrowdMatch, face: str, board: list[CrowdMatch]) -> dict:
    """(场, 面) 的可触发事实；概率单位 %。"""
    return {
        "face": face,
        "p_face": round(100 * match.p[face], 2),
        "p_home": round(100 * match.p["3"], 2),
        "p_draw": round(100 * match.p["1"], 2),
        "p_away": round(100 * match.p["0"], 2),
        "fav_face": match.fav_face,
        "is_fav": face == match.fav_face,
        "league": match.league,
        "league_group": match.league_group,
        "board_hot_count": sum(1 for m in board if max(m.p.values()) >= HOT),
    }


def evaluate(node: dict, f: dict) -> bool:
    if "all" in node:
        return all(evaluate(kid, f) for kid in node["all"])
    if "any" in node:
        return any(evaluate(kid, f) for kid in node["any"])
    if "not" in node:
        return not evaluate(node["not"], f)
    left, op, v = f[node["field"]], node["op"], node["v"]
    if op == ">=":
        return left >= v
    if op == "<=":
        return left <= v
    if op == "==":
        return left == v
    if op == "in":
        return left in v
    return left not in v


def fires(trigger: dict, board: list[CrowdMatch]) -> list[tuple[int, str]]:
    return [(m.no, face) for m in board for face in FACES
            if evaluate(trigger, facts(m, face, board))]
