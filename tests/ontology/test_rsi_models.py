from nutmeg.ontology.rsi.models import (
    Falsifier,
    Layer,
    Tier,
    Verdict,
    frozen_hash,
    project_status,
    validate_tier_for_layer,
)

_F2 = {
    "claim": "让球线向主移动 → 主胜残差为正",
    "mechanism": "改线是承诺",
    "tier": "observation",
    "layer": "judgment",
    "population": "zucai",
    "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {
        "metric": "home_resid_pp",
        "stratum": "zucai",
        "n_min": 140,
        "bound": "ci_upper",
        "threshold_pp": 2.0,
        "direction": "lt_means_falsified",
    },
    "stop_rule": "n≥140 结账",
    "quota_slot": False,
    "buckets": ["向客 ≤-0.25", "不动 0", "向主 +0.25", "向主 ≥+0.5"],
}


def test_frozen_hash_covers_every_frozen_field_and_ignores_the_rest():
    h = frozen_hash(_F2)
    # 非冻结字段不影响
    assert frozen_hash({**_F2, "source_doc": "x.json", "rule_ids": ["C11"]}) == h
    # U5：mechanism 也冻结
    assert frozen_hash({**_F2, "mechanism": "改了"}) != h
    assert frozen_hash({**_F2, "buckets": _F2["buckets"][:-1]}) != h


def test_falsifier_reads_only_the_ci_bound_and_refuses_before_n_min():
    f = Falsifier.from_dict(_F2["falsifier"])
    # 未到期：不判
    assert f.evaluate(n_cum=139, ci_low=-1.0, ci_high=1.0) is None
    # 上界 <2 → 证伪
    assert f.evaluate(n_cum=140, ci_low=-3.0, ci_high=1.9) is Verdict.FALSIFIED
    # 下界 ≥2 → 成立
    assert f.evaluate(n_cum=140, ci_low=2.5, ci_high=9.0) is Verdict.SURVIVED
    # 跨线 → 不定
    assert f.evaluate(n_cum=140, ci_low=-1.0, ci_high=5.0) is Verdict.INCONCLUSIVE


def test_judgment_layer_cannot_be_deploy_eligible():
    validate_tier_for_layer(Tier.OBSERVATION, Layer.JUDGMENT)
    try:
        validate_tier_for_layer(Tier.DEPLOY_ELIGIBLE, Layer.JUDGMENT)
    except ValueError as exc:
        assert "judgment" in str(exc)
    else:
        raise AssertionError("判读层实验不得 deploy_eligible")


def test_status_projection_is_derived_not_stored():
    base = dict(
        n_observations=0,
        latest_prospective_n=0,
        n_min=140,
        latest_verdict=None,
        latest_deployment=None,
    )
    assert project_status(**base) == "registered"
    assert project_status(**{**base, "n_observations": 3}) == "observing"
    assert (
        project_status(**{**base, "n_observations": 12, "latest_prospective_n": 140})
        == "graded"
    )
    assert (
        project_status(
            **{
                **base,
                "n_observations": 12,
                "latest_prospective_n": 140,
                "latest_verdict": "inconclusive",
            }
        )
        == "inconclusive"
    )
    assert (
        project_status(
            **{
                **base,
                "n_observations": 12,
                "latest_prospective_n": 150,
                "latest_verdict": "survived",
                "latest_deployment": "deploy",
            }
        )
        == "deployed"
    )
