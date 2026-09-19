"""Pure validation for constitutional and standing Zucai capital caps."""
from __future__ import annotations

DAY_CAP_YUAN = 2000
ZUCAI_TOTAL_CAP_YUAN = 1600
RENJIU_CAP_YUAN = 1200
SHENGFUCAI_BASELINE_YUAN = 400


class CapError(ValueError):
    pass


def validate_caps(caps: dict, *, jczq_used_today: int) -> None:
    renjiu = int(caps.get("renjiu", 0))
    shengfucai = int(caps.get("shengfucai", 0))
    total = int(caps.get("total", 0))
    if renjiu + shengfucai != total:
        raise CapError(f"合计 {total} != renjiu {renjiu} + shengfucai {shengfucai}")
    if renjiu > RENJIU_CAP_YUAN:
        raise CapError(f"renjiu 帽 {renjiu} > 常设行权 {RENJIU_CAP_YUAN}")
    if total > ZUCAI_TOTAL_CAP_YUAN:
        raise CapError(f"足彩合计 {total} > 宪法 {ZUCAI_TOTAL_CAP_YUAN:,}")
    if total + jczq_used_today > DAY_CAP_YUAN:
        raise CapError(
            f"日帽：足彩 {total} + 竞彩已登记 {jczq_used_today} > {DAY_CAP_YUAN}"
        )
