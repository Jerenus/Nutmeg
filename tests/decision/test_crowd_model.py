from nutmeg.decision.crowd_model import (
    IssueObs,
    bucket_triggers,
    excess,
    fit_gamma,
    grade_crowd,
    load_observations,
    nominate,
)
from nutmeg.decision.crowd_source import parse_zgzcw
from tests.decision.crowd_fixtures import seed_history, zg_doc

DRAW = {"field": "face", "op": "==", "v": "1"}


def test_excess_is_realised_minus_market_expected():
    board = tuple(parse_zgzcw(zg_doc()))
    results = tuple(["1"] * 3 + ["3"] * 11)
    obs = IssueObs("x", 0.0, 0.0, board, results)
    expected = 3 - sum(m.p["1"] for m in board)
    assert abs(excess(DRAW, obs) - expected) < 1e-9
    void = IssueObs("x", 0.0, 0.0, board, tuple(["*"] + list(results[1:])))
    assert abs(excess(DRAW, void) - (2 - sum(m.p["1"] for m in board[1:]))) < 1e-9


def test_fit_recovers_known_gamma(tmp_path):
    seed_history(tmp_path, n=60, gamma=-0.3)
    fit = fit_gamma(load_observations(tmp_path), DRAW, boots=400)
    assert fit.n == 60 and abs(fit.gamma + 0.3) < 0.05 and fit.ci_high < 0


def test_window_filter_and_requirements(tmp_path):
    issues = seed_history(tmp_path, n=10)
    obs = load_observations(tmp_path, window={"issue_from": issues[2], "issue_to": issues[5]})
    assert [o.issue for o in obs] == issues[2:6]


def test_grade_sign_follows_crowd_bias(tmp_path):
    seed_history(tmp_path, n=40, gamma=-0.3)
    doc = {"exp_id": "CR9", "trigger": DRAW, "crowd_bias": "over",
           "window": {"issue_from": "26001", "issue_to": "26999"},
           "replay_window": {"issue_from": "26001", "issue_to": "26020"}}
    g = grade_crowd(doc, tmp_path, mode="prospective", boots=300)
    assert g.n_cum == 40 and g.metric_value_pp > 0 and g.ci_low_pp > 0   # over + γ<0 → 方向成立
    assert g.ci_low_pp <= g.metric_value_pp <= g.ci_high_pp
    r = grade_crowd(doc, tmp_path, mode="replay", boots=300)
    assert r.n_cum == 20 and r.inputs_hash != g.inputs_hash
    doc["crowd_bias"] = "under"
    assert grade_crowd(doc, tmp_path, mode="prospective", boots=300).ci_high_pp < 0


def test_grade_with_too_few_issues_is_flat(tmp_path):
    seed_history(tmp_path, n=2)
    doc = {"exp_id": "CR9", "trigger": DRAW, "crowd_bias": "over",
           "window": {"issue_from": "26001", "issue_to": "26999"}, "replay_window": {}}
    g = grade_crowd(doc, tmp_path, mode="prospective")
    assert g.n_cum == 2 and (g.metric_value_pp, g.ci_low_pp, g.ci_high_pp) == (0.0, 0.0, 0.0)


def test_replay_without_window_has_no_sample(tmp_path):
    seed_history(tmp_path, n=10)
    doc = {"exp_id": "CR9", "trigger": DRAW, "crowd_bias": "over",
           "window": {"issue_from": "26001", "issue_to": "26999"}, "replay_window": None}
    assert grade_crowd(doc, tmp_path, mode="replay").n_cum == 0


def test_bucket_grammar_has_48_buckets():
    assert len(bucket_triggers()) == 48


def test_nominate_finds_planted_draw_effect_and_skips_registered(tmp_path):
    seed_history(tmp_path, n=60, gamma=-0.4)
    obs = load_observations(tmp_path)
    # top=48：只验「植入的平局效应被提名且方向对」，不赌它在 |γ| 排序里排第一
    # （各面 X 之和恒为 0，主/客桶会带出相关的伪信号）。
    cands = nominate(obs, existing={}, top=48, boots=300)
    draw = [c for c in cands if c["trigger"] == DRAW]
    assert draw and draw[0]["crowd_bias"] == "over"
    assert draw[0]["evidence"]["buckets_scanned"] == 48
    again = nominate(obs, existing={"CR1": DRAW}, top=48, boots=300)
    assert all(c["trigger"] != DRAW for c in again)
