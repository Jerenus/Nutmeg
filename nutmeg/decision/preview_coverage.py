"""买前预审覆盖率（2026-11-13，版图第 2 版拓展 2）：实购票里，开球前留过同一张预审痕的占比。

系统的目标是少亏，预审是唯一的机器否决（V1/V2 + 刹车）；26160 期三张实票买前没走预审，
复盘才补登。这本账只回答一件事：这个月的实票，有几张在开球前审过。**只读，不拦登记。**

口径（两处近似，读数时要知道）：
- 购买时刻不入账，「买前」以票内最早开球为界；缺开球时刻的旧票不做时刻比较。
- 竞彩的预审痕只记场次、不记选项：按「同一天、同一组场次」算审过；足彩按「同期、同票面」。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.bj_time import parse_bj
from nutmeg.decision.day_paths import PREVIEWS


def load_previews(data_dir: Path | str) -> list[dict]:
    """全部预审痕；每行补上它所在的日目录 `day`（竞彩场次编号每周重复，要靠日子区分）。"""
    rows: list[dict] = []
    for path in sorted((Path(data_dir) / "daily").glob(f"*/{PREVIEWS}")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append({**row, "day": path.parent.name})
    return rows


def _faces(faces: dict | None) -> dict[str, str]:
    return {str(k): "".join(sorted(str(v))) for k, v in (faces or {}).items()}


def _same_ticket(slip, preview: dict) -> bool:
    if preview.get("channel") != slip.channel:
        return False
    if slip.channel == "jczq":
        return (preview.get("day") == str(slip.placed_at)[:10]
                and set(preview.get("keys") or []) == {leg.key for leg in slip.legs})
    return (str(preview.get("issue") or "") == str(slip.issue)
            and _faces(preview.get("faces")) == _faces(slip.faces))


def _before_kickoff(slip, preview: dict) -> bool:
    kickoff = parse_bj(getattr(slip, "first_kickoff", ""))
    at = parse_bj(preview.get("at"))
    return kickoff is None or (at is not None and at <= kickoff)


def summarize(slips: list, previews: list[dict]) -> dict:
    """{n, covered, missing:[slip_id…]}：`slips` 只传实购票。"""
    missing = [s.slip_id for s in slips
               if not any(_same_ticket(s, p) and _before_kickoff(s, p) for p in previews)]
    return {"n": len(slips), "covered": len(slips) - len(missing), "missing": missing}


def month(data_dir: Path | str, month: str) -> dict:
    from nutmeg.decision.betslip import load_slips

    slips = [s for s in load_slips(data_dir)
             if s.purchased and str(s.placed_at)[:7] == month]
    return summarize(slips, load_previews(data_dir))


def line(cov: dict | None) -> str:
    """月账里的一行。算不出要写明，不能读成「都审过」。"""
    if not cov or cov.get("_error"):
        return f"**买前预审**：算不出——{(cov or {}).get('_error', '缺数据')}"
    if not cov["n"]:
        return "**买前预审**：本月没有实购票"
    text = f"**买前预审**：实购 {cov['n']} 张，开球前审过 {cov['covered']}/{cov['n']}"
    if cov["missing"]:
        shown = "、".join(cov["missing"][:6])
        more = f" 等 {len(cov['missing'])} 张" if len(cov["missing"]) > 6 else ""
        text += f"；没有同票面预审痕：{shown}{more}"
    return text
