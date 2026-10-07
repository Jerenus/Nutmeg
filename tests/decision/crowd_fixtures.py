"""人群层测试共用：假 zgzcw 文档、假官方奖金缓存、合成历史。"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from nutmeg.decision.crowd_source import fetch_issue

# 14 场：(联赛, 主, 客, (主,平,客) 欧赔)
BOARD_ROWS = [
    ("英超", f"主{i}", f"客{i}", odds)
    for i, odds in enumerate([
        (1.50, 4.20, 6.50), (2.40, 3.30, 3.00), (3.10, 3.20, 2.40), (1.80, 3.60, 4.50),
        (2.10, 3.30, 3.60), (2.90, 3.10, 2.60), (1.30, 5.50, 9.00), (2.60, 3.10, 2.90),
        (2.00, 3.40, 3.80), (3.50, 3.40, 2.10), (1.65, 3.90, 5.20), (2.30, 3.20, 3.30),
        (2.80, 3.00, 2.75), (1.95, 3.50, 3.90),
    ], start=1)
]


def zg_doc(rows=BOARD_ROWS) -> dict:
    return {"matchInfo": [
        {"leageName": lg, "hostName": h, "guestName": a, "europeSp": f"{o[0]} {o[1]} {o[2]}",
         "yapan": "0.90 半球 0.90"}
        for lg, h, a, o in rows
    ]}


def write_prizes(zdir: Path, issues: dict[str, dict]) -> None:
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / "official-prizes.json").write_text(
        json.dumps({"source": "test", "issues": issues}, ensure_ascii=False), encoding="utf-8")


def seed_history(zdir: Path, *, first: int = 26001, n: int = 40, gamma: float = -0.3,
                 seed: int = 3) -> list[str]:
    """合成 n 期：赛果按市场概率抽样，奖金 = exp(-5 + S + gamma·X_draw + 噪声)。"""
    # crowd_model 在 Task 3 才有；放函数内，Task 1 的测试只用到 zg_doc。
    from nutmeg.decision.crowd_model import IssueObs, excess, surprise
    from nutmeg.decision.crowd_source import load_board

    rng = random.Random(seed)
    trigger = {"field": "face", "op": "==", "v": "1"}
    prizes, issues = {}, []
    for k in range(n):
        issue = str(first + k)
        fetch_issue(zdir, issue, fetcher=lambda url: zg_doc())
        _, board = load_board(zdir, issue)
        results = []
        for m in board:
            u, acc = rng.random(), 0.0
            for face in ("3", "1", "0"):
                acc += m.p[face]
                if u <= acc:
                    results.append(face)
                    break
            else:
                results.append("0")
        obs = IssueObs(issue, surprise(board, tuple(results)), 0.0, tuple(board), tuple(results))
        log_prize = -5 + obs.s + gamma * excess(trigger, obs) + rng.gauss(0, 0.05)
        prize = round(math.exp(log_prize) * 1e4, 2)
        prizes[issue] = {"results": " ".join(results),
                         "renjiu": {"stake_count": 10, "stake_amount": prize}}
        issues.append(issue)
    write_prizes(zdir, prizes)
    return issues
