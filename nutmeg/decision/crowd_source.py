"""足彩人群层的市场底座：中国足彩网（zgzcw）胜负彩对阵接口 → 每场市场概率与联赛。

为什么是 zgzcw（2026-10-07 勘察）：500「本站用户投注比例」列已隐藏、popularity JSON 全 404，
zgzcw `renqiInfo` 历史全空——逐场人群比例拿不到，人群改由官方奖金反推（crowd_model）。
反推要求每期同一口径的市场概率：zgzcw `europeSp` 可回取 26035 起全部期次，故全部期次统一用它
（与 500 14:00 快照逐场差最多 8pp，混源会把源差当成人群偏离）。
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nutmeg.data.http import BROWSER_UA
from nutmeg.data.prices import devig

ZGZCW_URL = "https://cp.zgzcw.com/lottery/zcplayvs.action?lotteryId=13&issue={issue}"
FACES = ("3", "1", "0")
# zgzcw 的写法（2026-10-07 回填 26035–26135 全量核对）：国际友谊 / 世欧预 / 世界杯附 等。
NATIONAL = frozenset({"友谊赛", "国际友谊", "国际赛", "欧国联", "世预赛", "世欧预", "欧预赛",
                      "亚预赛", "世界杯", "世界杯附", "欧洲杯", "亚洲杯", "美洲杯", "非洲杯",
                      "金杯赛", "亚运男足", "亚运女足"})
TOP5 = frozenset({"英超", "西甲", "德甲", "意甲", "法甲"})

Fetcher = Callable[[str], dict]


@dataclass(frozen=True)
class CrowdMatch:
    no: int
    league: str
    home: str
    away: str
    p: dict[str, float]          # {"3","1","0"} 去水市场概率，和为 1
    asian: str = ""

    @property
    def league_group(self) -> str:
        if self.league in NATIONAL:
            return "national"
        return "top5" if self.league in TOP5 else "other"

    @property
    def fav_face(self) -> str:
        return max(FACES, key=lambda f: self.p[f])


def parse_zgzcw(doc: dict) -> list[CrowdMatch]:
    """`matchInfo` 顺序即场号；`europeSp` 缺/坏的场跳过（场号不顺延）。"""
    out = []
    for no, m in enumerate(doc.get("matchInfo") or [], start=1):
        try:
            h, d, a = (float(x) for x in str(m.get("europeSp") or "").split())
            fair = devig({"3": h, "1": d, "0": a})
        except (ValueError, ZeroDivisionError):
            continue
        # zgzcw 两字联赛名常带全角空格（「德　甲」），去掉一切空白后再归组。
        out.append(CrowdMatch(no=no, league="".join(str(m.get("leageName") or "").split()),
                              home=str(m.get("hostName") or ""), away=str(m.get("guestName") or ""),
                              p=fair, asian=str(m.get("yapan") or "")))
    return out


def board_path(zdir: Path, issue: str) -> Path:
    return Path(zdir) / f"{issue}-zgzcw.json"


def _default_fetcher(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 —— 固定 https 源
        return json.loads(resp.read().decode("utf-8"))


def fetch_issue(zdir: Path, issue: str, *, fetcher: Fetcher | None = None,
                now: datetime | None = None) -> Path:
    """拉一次快照追加到 `<期>-zgzcw.json`；无可用对阵时 ValueError、不写文件。"""
    url = ZGZCW_URL.format(issue=issue)
    raw = (fetcher or _default_fetcher)(url)
    if not parse_zgzcw(raw):
        raise ValueError(f"zgzcw {issue} 无可用对阵（matchInfo 空或 europeSp 全缺）")
    path = board_path(zdir, issue)
    doc = (json.loads(path.read_text("utf-8")) if path.exists()
           else {"issue": issue, "source": url, "snapshots": []})
    at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    doc["snapshots"].append({"fetched_at": at, "raw": raw})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def load_board(zdir: Path, issue: str) -> tuple[str, list[CrowdMatch]] | None:
    """最后一张快照 → (fetched_at, 板面)；无文件/无快照 → None。"""
    path = board_path(zdir, issue)
    if not path.exists():
        return None
    snaps = json.loads(path.read_text("utf-8")).get("snapshots") or []
    if not snaps:
        return None
    return snaps[-1]["fetched_at"], parse_zgzcw(snaps[-1]["raw"])


def backfill(zdir: Path, issues: Iterable[str], *, fetcher: Fetcher | None = None,
             sleep: Callable[[float], None] = time.sleep, pause: float = 1.0) -> dict[str, str]:
    """逐期回取；已有快照跳过；单期失败只记账不中断。→ {期: ok|skip|fail: …}"""
    out: dict[str, str] = {}
    for issue in issues:
        if load_board(zdir, issue):
            out[issue] = "skip"
            continue
        try:
            fetch_issue(zdir, issue, fetcher=fetcher)
            out[issue] = "ok"
        except (OSError, ValueError) as exc:
            out[issue] = f"fail: {exc}"[:120]
        sleep(pause)
    return out
