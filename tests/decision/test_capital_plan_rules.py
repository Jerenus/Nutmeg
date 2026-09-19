import pytest

from nutmeg.decision.capital_rules import CapError, validate_caps


def test_constitution_and_standing_override_caps():
    validate_caps(
        {"renjiu": 1200, "shengfucai": 400, "total": 1600}, jczq_used_today=0
    )
    with pytest.raises(CapError, match="renjiu"):
        validate_caps(
            {"renjiu": 1201, "shengfucai": 0, "total": 1201}, jczq_used_today=0
        )
    with pytest.raises(CapError, match="1,600"):
        validate_caps(
            {"renjiu": 1000, "shengfucai": 700, "total": 1700}, jczq_used_today=0
        )
    with pytest.raises(CapError, match="日帽"):
        validate_caps(
            {"renjiu": 1200, "shengfucai": 400, "total": 1600}, jczq_used_today=500
        )
    with pytest.raises(CapError, match="合计"):
        validate_caps(
            {"renjiu": 800, "shengfucai": 400, "total": 1000}, jczq_used_today=0
        )
