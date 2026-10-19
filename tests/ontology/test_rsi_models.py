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


def _falsifier(bound: str, direction: str, t: float = 0.0) -> Falsifier:
    return Falsifier.from_dict({"metric": "m", "stratum": "pooled", "n_min": 60,
                                "bound": bound, "threshold_pp": t, "direction": direction})


def test_falsifier_honours_the_registered_bound_like_the_frozen_text():
    # 2026-10-19 Jun 裁「冻结原文为准」：F14「CI 下界 ≤0 即证伪」——bound=ci_lower 时下界
    # 落在门槛下就是证伪，没有「跨线」可言（2026-10-19 前代码不读 bound，F14 首看被判 inconclusive）
    lower = _falsifier("ci_lower", "lt_means_falsified")
    assert lower.evaluate(n_cum=77, ci_low=-3.61, ci_high=14.05) is Verdict.FALSIFIED
    assert lower.evaluate(n_cum=77, ci_low=0.49, ci_high=13.75) is Verdict.SURVIVED
    # bound=ci_upper：上界 < t 证伪、下界 ≥ t 成立、其余跨线（F9「ci_upper < 0 即证伪」）
    upper = _falsifier("ci_upper", "lt_means_falsified")
    assert upper.evaluate(n_cum=71, ci_low=-1.77, ci_high=0.23) is Verdict.INCONCLUSIVE
    assert upper.evaluate(n_cum=71, ci_low=-1.77, ci_high=-0.1) is Verdict.FALSIFIED
    # gt + ci_upper：F16/F17「CI 上界 > 0 即证伪」——上界不过 0 就是成立
    gt_upper = _falsifier("ci_upper", "gt_means_falsified")
    assert gt_upper.evaluate(n_cum=150, ci_low=-9.0, ci_high=0.5) is Verdict.FALSIFIED
    assert gt_upper.evaluate(n_cum=150, ci_low=-9.0, ci_high=-0.5) is Verdict.SURVIVED
    # gt + ci_lower：F19「CI 下界 > 0 即证伪」；上界 ≤ 0 成立；其余跨线
    gt_lower = _falsifier("ci_lower", "gt_means_falsified")
    assert gt_lower.evaluate(n_cum=60, ci_low=0.4, ci_high=9.0) is Verdict.FALSIFIED
    assert gt_lower.evaluate(n_cum=60, ci_low=-9.0, ci_high=-0.4) is Verdict.SURVIVED
    assert gt_lower.evaluate(n_cum=60, ci_low=-3.0, ci_high=3.0) is Verdict.INCONCLUSIVE


def test_distance_reads_the_registered_bound():
    lower = _falsifier("ci_lower", "lt_means_falsified")
    assert lower.distance_pp(ci_low=1.5, ci_high=9.0) == 1.5     # 下界离门槛 1.5pp
    gt_upper = _falsifier("ci_upper", "gt_means_falsified")
    assert gt_upper.distance_pp(ci_low=-9.0, ci_high=-2.0) == 2.0


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


def test_frozen_hash_unchanged_for_docs_without_crowd_fields():
    import hashlib
    import json
    from pathlib import Path

    from nutmeg.ontology.actions.models import canonical_json
    from nutmeg.ontology.rsi.models import FROZEN_FIELDS, frozen_hash

    for path in sorted(Path("experiments/registry").glob("[!_C]*.json")):
        doc = json.loads(path.read_text("utf-8"))
        old = hashlib.sha256(canonical_json({k: doc.get(k) for k in FROZEN_FIELDS})
                             .encode("utf-8")).hexdigest()
        assert frozen_hash(doc) == old, path.name


def test_frozen_hash_covers_crowd_fields_when_present():
    from nutmeg.ontology.rsi.models import frozen_hash

    base = {"exp_id": "CR1", "claim": "c", "trigger": {"field": "face", "op": "==", "v": "1"},
            "crowd_bias": "over", "label_cn": "x",
            "replay_window": {"issue_from": "1", "issue_to": "2"}}
    flipped = dict(base, trigger={"field": "face", "op": "==", "v": "3"})
    assert frozen_hash(base) != frozen_hash(flipped)
    assert frozen_hash(base) == frozen_hash(dict(base, psychology="随便改"))
