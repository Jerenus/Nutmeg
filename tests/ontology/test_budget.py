import pytest

from nutmeg.ontology.finance.budget import validate_within_budget


def test_within_budget_passes() -> None:
    validate_within_budget(400.0, {"main": 100.0}, [{"bucket": "main", "stake": 100.0}])
    validate_within_budget(400.0, {}, [])   # empty slate is legal


def test_over_total_cap_raises() -> None:
    with pytest.raises(ValueError, match="total"):
        validate_within_budget(400.0, {}, [{"bucket": "main", "stake": 500.0}])


def test_over_bucket_cap_raises() -> None:
    with pytest.raises(ValueError, match="bucket"):
        validate_within_budget(400.0, {"main": 100.0}, [{"bucket": "main", "stake": 150.0}])
