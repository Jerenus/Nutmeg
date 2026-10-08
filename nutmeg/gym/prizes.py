"""官方奖金缓存（gym 的派奖源）：gameNo=90 历史页一次抓 N 期，含作废场（*）与逗号数字。

磁盘上此前只有 26112 存过奖金；gym 结算足彩必须有当期每注奖金，缺就跳过不猜。
`zucai_official.parse_draw` 遇到 `*` 会按"宁死不猜"抛错（结算纪律），这里的缓存要把作废场
也装下——作废场在官方规则里每个面都算中，派奖算得出来。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.zucai_official import _num, fetch_history

CACHE = "official-prizes.json"
VALID = {"3", "1", "0", "*"}


def _prize(rows, level: str | None = None) -> dict | None:
    for row in rows or []:
        if level is None or row.get("prizeLevel") == level:
            count, amount = _num(row.get("stakeCount")), _num(row.get("stakeAmount"))
            if count is not None and amount is not None:
                return {"stake_count": int(count), "stake_amount": amount}
    return None


def parse_item(item: dict) -> tuple[str, dict] | None:
    """官方 list 条目 → (期号, 缓存行)；未开奖/串不合法 → None。"""
    codes = str(item.get("lotteryDrawResult") or "").split()
    if len(codes) != 14 or any(c not in VALID for c in codes):
        return None
    levels = item.get("prizeLevelList") or []
    return str(item.get("lotteryDrawNum")), {
        "draw_date": str(item.get("lotteryDrawTime") or "")[:10],
        "sale_end": item.get("lotterySaleEndtime"),
        "results": " ".join(codes),
        "void_matches": [i + 1 for i, c in enumerate(codes) if c == "*"],
        "renjiu": _prize(item.get("prizeLevelListRj")),
        "sfc_first": _prize(levels, "一等奖"),
        "sfc_second": _prize(levels, "二等奖"),
        "sale_amount_sfc": _num(item.get("totalSaleAmount")),
        "sale_amount_rj": _num(item.get("totalSaleAmountRj")),
    }


def load_prizes(zucai_dir: Path) -> dict[str, dict]:
    path = Path(zucai_dir) / CACHE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("issues") or {}
    except ValueError:
        return {}


def build_prize_cache(zucai_dir: Path, *, fetcher=None, page_size: int = 130) -> Path:
    """抓官方历史并与已有缓存合并（同期号以新抓为准），落 `<zucai_dir>/official-prizes.json`。"""
    payload = fetch_history(page_size=page_size, fetcher=fetcher, timeout=30.0)
    issues = load_prizes(zucai_dir)
    for item in (payload.get("value") or {}).get("list") or []:
        parsed = parse_item(item)
        if parsed:
            issues[parsed[0]] = parsed[1]
    path = Path(zucai_dir) / CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source": f"sporttery gameNo=90 getHistoryPageListV1 (pageSize={page_size})",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": "results 含 * 作废场；renjiu/sfc_* 为每注奖金(元)与中奖注数；sale_* 为销量(元)",
        "issues": dict(sorted(issues.items())),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
