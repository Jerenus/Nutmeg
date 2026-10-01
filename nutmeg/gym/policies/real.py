"""真票回放：`betslips.jsonl` 里实购的票原样回放（竞彩按下单日、足彩按期次）。

验收门 `gym verify` 也走这里：gym 的结算必须复现记分牌上的 9 月净额。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.betslip import BetSlip
from nutmeg.gym.board import JczqBoard, ZucaiIssue
from nutmeg.gym.policy import Ctx, register

LEDGER = "betslips.jsonl"


def load_real_slips(data_dir: Path) -> list[BetSlip]:
    path = Path(data_dir) / LEDGER
    if not path.exists():
        return []
    slips = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            slip = BetSlip.from_dict(json.loads(line))
            if slip.purchased:
                slips.append(slip)
    return slips


@register
class Real:
    name = "real"
    version = "v1"
    channels = ("jczq", "renjiu", "shengfucai")

    def decide(self, board: JczqBoard | ZucaiIssue, ctx: Ctx) -> list[BetSlip]:
        data_dir = ctx.extra.get("data_dir")
        if data_dir is None:
            return []
        slips = load_real_slips(Path(data_dir))
        if isinstance(board, JczqBoard):
            return [s for s in slips if s.channel == "jczq" and s.placed_at[:10] == board.day]
        return [s for s in slips if s.channel in ("renjiu", "shengfucai")
                and str(s.issue) == board.issue]
