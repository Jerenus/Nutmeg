"""基线：永远空仓。regret 的零点。"""
from __future__ import annotations

from nutmeg.gym.policy import register


@register
class Flat:
    name = "flat"
    version = "v1"
    channels = ("jczq", "renjiu", "shengfucai")

    def decide(self, board, ctx):
        return []
