"""足彩策略：期次 → legs-base 形状 → `enumerate_frontier`（帽内 max P）→ 一张任九复式。

`enumerate_frontier` 只认 `legs[no] = {"fair": …, "face_status": {face: {"state": alive|dead}}}`，
这里把期次 fair 和策略自己的"活面"判定塞进去；strength-v2 的帽内按判断概率定结构原样复用。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip
from nutmeg.decision.structure_space import enumerate_frontier
from nutmeg.gym.board import FACES, ZucaiIssue
from nutmeg.gym.policy import Ctx, register


def frontier_legs(issue: ZucaiIssue, *, alive_of=None) -> dict[str, dict]:
    legs: dict[str, dict] = {}
    for no, m in issue.matches.items():
        alive = alive_of(m.fair) if alive_of else list(FACES)
        legs[no] = {"fair": dict(m.fair),
                    "face_status": {f: {"state": "alive" if f in alive else "dead"} for f in FACES}}
    return legs


def best_point(legs: dict[str, dict], *, channel: str, cap_yuan: int) -> dict | None:
    result = enumerate_frontier(legs, channel=channel, cap_yuan=cap_yuan, mode="belief")
    points = [p for p in result.get("points") or [] if p["stake_yuan"] <= cap_yuan]
    if not points:
        return None
    return max(points, key=lambda p: (p["p_all"], -p["stake_yuan"]))


def to_slip(issue: ZucaiIssue, point: dict, *, channel: str, tag: str) -> BetSlip:
    faces = {str(no): str(f) for no, f in point["faces"].items()}
    return BetSlip(slip_id=f"gym-{tag}-{issue.issue}", channel=channel,
                   placed_at=(issue.sale_deadline or "")[:10], legs=[], multiplier=1,
                   issue=issue.issue, faces=faces)


@register
class ZucaiMaxP:
    """全部面都活，帽内 P(全对) 最高的任九复式。"""
    name = "zucai_max_p"
    version = "v1"
    channels = ("renjiu",)

    def decide(self, issue: ZucaiIssue, ctx: Ctx) -> list[BetSlip]:
        if len(issue.matches) < 9:
            return []
        point = best_point(frontier_legs(issue), channel="renjiu", cap_yuan=ctx.cap_zucai_slip)
        return [to_slip(issue, point, channel="renjiu", tag="maxp")] if point else []


@register
class ZucaiFavSingle:
    """≥0.70 大热只留该面；<0.20 的面判死不进全包；其余按帽内 max P（#2 的结构化用法）。"""
    name = "zucai_fav_single"
    version = "v1"
    channels = ("renjiu",)
    fav = 0.70
    longshot = 0.20

    def decide(self, issue: ZucaiIssue, ctx: Ctx) -> list[BetSlip]:
        if len(issue.matches) < 9:
            return []

        def alive_of(fair: dict) -> list[str]:
            top = max(fair, key=fair.get)
            if fair[top] >= self.fav:
                return [top]
            kept = [f for f in FACES if fair[f] >= self.longshot]
            return kept or [top]

        legs = frontier_legs(issue, alive_of=alive_of)
        point = best_point(legs, channel="renjiu", cap_yuan=ctx.cap_zucai_slip)
        return [to_slip(issue, point, channel="renjiu", tag="fav")] if point else []


@register
class ZucaiPrescription:
    """有 `<期>-final-tickets.json` 的期次回放处方票。

    文件形状逐期不同，只认 tickets[].faces 与 kind/channel。
    """
    name = "zucai_prescription"
    version = "v1"
    channels = ("renjiu", "shengfucai")

    def decide(self, issue: ZucaiIssue, ctx: Ctx) -> list[BetSlip]:
        data_dir = ctx.extra.get("data_dir")
        if data_dir is None:
            return []
        path = Path(data_dir) / "zucai" / f"{issue.issue}-final-tickets.json"
        if not path.exists():
            return []
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return []
        tickets = doc.get("tickets") if isinstance(doc, dict) else None
        if not isinstance(tickets, list):
            return []
        out: list[BetSlip] = []
        for i, t in enumerate(tickets):
            faces = t.get("faces")
            if not isinstance(faces, dict) or not faces:
                continue
            kind = str(t.get("kind") or t.get("channel") or "")
            channel = ("shengfucai" if ("胜负" in kind or kind == "shengfucai" or len(faces) == 14)
                       else "renjiu")
            need = 9 if channel == "renjiu" else 14
            if len(faces) != need:
                continue
            ticket_id = t.get("id") or t.get("ticket_id") or t.get("slip_id") or i
            out.append(BetSlip(
                slip_id=f"gym-rx-{issue.issue}-{ticket_id}",
                channel=channel, placed_at=(issue.sale_deadline or "")[:10], legs=[],
                multiplier=int(t.get("multiplier") or 1), issue=issue.issue,
                faces={str(k): str(v) for k, v in faces.items()}))
        return out
