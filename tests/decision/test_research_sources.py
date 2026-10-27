"""研究引用制 + 覆盖门（2026-10-27 探照灯 P1/P2）：只算来源与覆盖，不碰判断。"""
from nutmeg.decision.research_sources import (
    attach_sources,
    coverage_mark,
    evidence_sources,
    extract_urls,
    probe_sources,
    research_coverage,
    site_of,
)

SRC = {"captured_at": "2026-10-27T09:00:00+08:00", "source_tier": "press"}


def test_extract_urls_takes_full_and_bare_site_paths_but_not_bare_domains():
    text = ("搜狐 sohu.com/a/1090953957（引国安官宣）；https://www.arsenal.com/news/x?y=1。"
            "spotvnews.co.kr 另一说")
    assert extract_urls(text) == ["https://sohu.com/a/1090953957",
                                  "https://www.arsenal.com/news/x?y=1"]
    assert extract_urls(None) == [] and extract_urls("") == []
    assert site_of("https://www.arsenal.com/news/x") == "arsenal.com"


def test_evidence_sources_counts_only_active_fact_items_and_events():
    research = {
        "rubric": {"items": {
            "F_absence_home": {"answer": "yes", "p": 0.9, "abstain": False,
                               "source": "https://club.example/news/1", **SRC},
            "F_absence_away": {"answer": "no", "p": 0.2, "abstain": False,
                               "source": "https://press.example/2", **SRC},      # 答否：不计
            "F_suspension": {"answer": "away", "p": 0.8, "abstain": False,
                             "source": "据报道", **SRC},                          # 无 URL
            "S_spine_intact": {"answer": "yes", "p": 0.7, "abstain": False,
                               "source": "club.example/squad", **SRC},
            "S_draw_mode": {"answer": "yes", "p": 0.6, "abstain": False, "source": ""},  # 不要来源
        }},
        "strength_balance": {"events": [
            {"event": "a", "source": "https://press.example/3"},
            {"event": "b", "source": "主帅发布会"},
        ]},
        "premise_corrections": [{"evidence": "https://league.example/table"}],
        "sources_consulted": [{"url": "https://club.example/news/1"},
                              {"url": "https://other.example/p"}],
    }
    s = evidence_sources(research)
    assert s["items_active"] == 3 and s["items_with_url"] == 2
    assert s["events"] == 2 and s["events_with_url"] == 1
    assert s["consulted"] == 2 and s["declared"] is True
    assert s["urls"] == ["https://club.example/news/1", "https://club.example/squad",
                         "https://press.example/3", "https://league.example/table",
                         "https://other.example/p"]
    assert s["sites"] == ["club.example", "league.example", "other.example", "press.example"]


def test_attach_sources_records_probe_results_without_touching_judgment():
    research = {"stance": {"face": "3"},
                "strength_balance": {"events": [{"event": "a", "source": "https://x.example/1"}]}}
    seen = []

    def probe(urls):
        seen.append(list(urls))
        return {u: {"ok": True, "status": 200, "error": ""} for u in urls}

    summary = attach_sources(research, probe=probe)
    assert seen == [["https://x.example/1"]]
    assert summary["probe_ok"] == 1 and research["evidence_sources"]["probe_ok"] == 1
    assert research["stance"] == {"face": "3"}
    assert "probe" not in attach_sources({"stance": {}}, probe=probe)       # 没 URL 不回抓


def test_probe_sources_never_raises_on_dead_hosts():
    out = probe_sources(["https://nonexistent.invalid/page"], timeout=0.5)
    assert out["https://nonexistent.invalid/page"]["ok"] is False
    assert out["https://nonexistent.invalid/page"]["status"] is None
    assert probe_sources([]) == {}


def _covered():
    from nutmeg.decision.rubric_items import FACT_ITEMS, ITEMS

    items = {k: {"answer": "yes" if ITEMS[k].type == "noul" else "home", "abstain": False,
                 "source": f"https://s{i}.example/{k}", **SRC}
             for i, k in enumerate(FACT_ITEMS)}
    return {
        "rubric": {"items": items},
        "stance": {"falsifier": "若客队主力门将首发则本判断作废"},
        "stop_rule": {"counter_searched": True, "counter_note": "搜了「客队 伤愈 复出」，无新证",
                      "reason": "coverage"},
    }


def test_coverage_requires_all_three_gates_and_reports_each():
    research = _covered()
    cov = research_coverage(research, raw_items=research["rubric"]["items"])
    assert cov["converged"] is True and cov["stop_reason"] == "coverage"
    assert cov["facts_answered"] == "7/7" and cov["urls"] == 7 and cov["sites"] == 7
    assert coverage_mark(cov) == "✓"

    missing = _covered()
    cov = research_coverage(missing, raw_items=["F_absence_home"])
    assert cov["facts_ok"] is False and cov["converged"] is False
    assert cov["facts_answered"] == "1/7" and coverage_mark(cov) == "◇"

    no_counter = _covered()
    no_counter["stop_rule"]["counter_note"] = ""
    cov = research_coverage(no_counter, raw_items=no_counter["rubric"]["items"])
    assert cov["counter_searched"] is False and cov["converged"] is False

    thin = _covered()
    for raw in thin["rubric"]["items"].values():
        raw["source"] = "https://one.example/same"
    cov = research_coverage(thin, raw_items=thin["rubric"]["items"])
    assert cov["sources_ok"] is False and cov["sites"] == 1


def test_coverage_stop_reason_is_budget_after_a_retry_and_undeclared_without_stop_rule():
    research = _covered()
    cov = research_coverage(research, raw_items=research["rubric"]["items"], retried=True)
    assert cov["stop_reason"] == "budget" and cov["stop_reason_declared"] == "coverage"
    assert cov["retried"] is True
    bare = {"stance": {"falsifier": "x" * 12}}
    cov = research_coverage(bare, raw_items=[])
    assert cov["stop_reason"] == "undeclared" and cov["converged"] is False
    assert coverage_mark(None) == "—"
