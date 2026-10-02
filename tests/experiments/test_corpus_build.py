from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "experiments" / "corpus_build.py"
_SPEC = importlib.util.spec_from_file_location("corpus_build", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
corpus_build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(corpus_build)


def test_research_labels_flattens_controlled_hole_location():
    labels = corpus_build._research_labels(
        {
            "hole_location": {
                "unit": "attack",
                "side": "away",
                "priced_in": False,
                "detail": "客队中锋缺阵",
            }
        }
    )

    assert labels["hole_location_unit"] == "attack"
    assert labels["hole_location_side"] == "away"
    assert labels["hole_location_priced_in"] is False


def test_research_labels_does_not_guess_legacy_hole_location():
    labels = corpus_build._research_labels(
        {"hole_location": {"anchor": "attack", "opponent": "defense"}}
    )

    assert labels["hole_location_unit"] is None
    assert labels["hole_location_side"] is None
    assert labels["hole_location_priced_in"] is None


def test_research_labels_does_not_admit_legacy_free_text_unit_as_controlled():
    labels = corpus_build._research_labels(
        {
            "hole_location": {
                "unit": "defensive_spine_plus_midfield_pivot",
                "names": ["legacy player"],
                "priced": "partly priced",
            }
        }
    )

    assert labels["hole_location_unit"] is None
    assert labels["hole_location_side"] is None
    assert labels["hole_location_priced_in"] is None


def test_postmortem_labels_are_merged_as_fifth_source():
    labels = {"anchor_integrity": "pass"}
    postmortem = {
        "actual_was_excluded": True,
        "actual_face_prior": {
            "fair_pp": 20.0,
            "exclusion_tier": "灰带",
            "death_proof_count": "2/3",
            "precedent_status": "dead",
        },
    }

    assert corpus_build._merge_postmortem(labels, postmortem) == {
        "anchor_integrity": "pass",
        "postmortem": postmortem,
    }


def test_jczq_rows_loads_postmortem_as_fifth_source(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    day_dir = root / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    (root / "jc-results.json").write_text(
        json.dumps({"2026-09-19": {"周六001": {"ft_home": 1, "ft_away": 0}}}),
        encoding="utf-8",
    )
    (day_dir / "bold_odds.json").write_text(
        json.dumps(
            {
                "周六001": {
                    "match_winner": {"fair_probability": {"home": 0.5, "draw": 0.3, "away": 0.2}}
                }
            }
        ),
        encoding="utf-8",
    )
    postmortem = {"actual_was_excluded": True, "actual_face_prior": {"fair_pp": 50.0}}
    (day_dir / "postmortem-周六001.json").write_text(json.dumps(postmortem), encoding="utf-8")
    monkeypatch.setattr(corpus_build, "J", str(root))

    rows = corpus_build.jczq_rows()

    assert rows[0]["labels"]["postmortem"] == postmortem


def test_jczq_rows_marks_research_captured_before_kickoff_as_provable(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    day_dir = root / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    (root / "jc-results.json").write_text(
        json.dumps({"2026-09-19": {"周六001": {"ft_home": 1, "ft_away": 0}}}),
        encoding="utf-8",
    )
    (day_dir / "bold_odds.json").write_text(
        json.dumps(
            {
                "周六001": {
                    "match_winner": {"fair_probability": {"home": 0.5, "draw": 0.3, "away": 0.2}}
                }
            }
        ),
        encoding="utf-8",
    )
    (day_dir / "jczq-legs-base.json").write_text(
        json.dumps({"legs": {"周六001": {"kickoff_bj": "2026-09-19T20:00:00+08:00"}}}),
        encoding="utf-8",
    )
    (day_dir / "research-周六001.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-09-19T19:59:00+08:00",
                "anchor_integrity": "pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_build, "J", str(root))

    row = corpus_build.jczq_rows()[0]

    assert row["provably_prospective"] is True
    assert row["judged_at_source"] == "research.captured_at"


def test_prospective_fields_exposes_leak_and_keeps_missing_time_unknown():
    leaked = corpus_build._prospective_fields(
        judged_at="2026-09-19T20:00:00+08:00",
        kickoff_bj="2026-09-19T20:00:00+08:00",
        judged_at_source="legs-base.legs[n].judged_at",
    )
    unknown = corpus_build._prospective_fields(
        judged_at=None,
        kickoff_bj="2026-09-19T20:00:00+08:00",
        judged_at_source=None,
    )

    assert leaked == {
        "provably_prospective": False,
        "judged_at_source": "legs-base.legs[n].judged_at",
    }
    assert unknown == {"provably_prospective": None, "judged_at_source": None}


def test_judgment_entries_recognise_every_known_era_shape():
    numeric = {"1": {"action": "310", "confidence": 2, "note": "n1"}, "made_at": "x"}
    entries, source = corpus_build._judgment_entries(numeric)
    assert source == "judgment[match_no]" and entries[1]["action"] == "310"

    judgments = {"judgments": {"3": {"picks": "1/0", "confidence": 3, "reason": "r"}}}
    entries, source = corpus_build._judgment_entries(judgments)
    assert source == "judgment.judgments" and entries[3]["picks"] == "1/0"

    decisions = {"decisions": [{"match_no": "2", "ticket": "31", "conf": "3"}]}
    entries, source = corpus_build._judgment_entries(decisions)
    assert source == "judgment.decisions" and entries[2]["ticket"] == "31"

    matches = {"matches": [{"match_no": "1", "pick": "310", "flags": ["a"]}]}
    entries, source = corpus_build._judgment_entries(matches)
    assert source == "judgment.matches" and entries[1]["flags"] == ["a"]

    picks = {"picks": [{"match_no": 1, "selection": "3", "anchor_fair_had": {"3": 0.6}}]}
    entries, source = corpus_build._judgment_entries(picks)
    assert source == "judgment.picks" and entries[1]["selection"] == "3"

    prose = {"board": "一段散文", "made_at": "2026-07-26"}
    assert corpus_build._judgment_entries(prose) == ({}, None)
    assert corpus_build._judgment_entries([1, 2]) == ({}, None)


def test_judgment_lane_adds_call_note_labels_but_never_prospective_proof(tmp_path, monkeypatch):
    root = tmp_path / "zucai"
    root.mkdir()
    (root / "official-results.json").write_text(json.dumps({"26099": "3 1"}), encoding="utf-8")
    (root / "26099-issue.json").write_text(
        json.dumps(
            {
                "matches": [
                    {"match_no": 1, "match_date": "2026-08-02", "kickoff_bj": "2026-08-02 20:00"},
                    {"match_no": 2, "match_date": "2026-08-02", "kickoff_bj": "2026-08-02 22:00"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "26099-reads.json").write_text(
        json.dumps(
            [
                {"read_id": "26099-01-had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2}},
            ]
        ),
        encoding="utf-8",
    )
    (root / "26099-judgment.json").write_text(
        json.dumps(
            {
                "made_at": "2026-08-02T09:54:00+08:00",
                "matches": [
                    {
                        "match_no": "1",
                        "pick": "310",
                        "primary": "0",
                        "confidence": "2",
                        "flags": ["weak_home_draw_trap"],
                        "note": "top1<45且有无方向旗，强制全包。",
                    },
                    {
                        "match_no": "2",
                        "pick": "3",
                        "confidence": "4",
                        "anchor_fair_had": {"3": 0.7, "1": 0.2, "0": 0.1},
                        "reason": "只有 judgment 有价格的场",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_build, "Z", str(root))

    rows = {row["match_no"]: row for row in corpus_build.zucai_rows()}

    assert rows[1]["call"] == "310"
    assert rows[1]["conf"] == 2
    assert rows[1]["note"].startswith("top1<45")
    assert rows[1]["labels"]["judgment"]["flags"] == ["weak_home_draw_trap"]
    assert rows[1]["labels"]["judgment"]["_source"] == "judgment.matches"
    assert rows[1]["judged_at_declared"] == "2026-08-02T09:54:00+08:00"
    assert rows[1]["provably_prospective"] is None
    assert rows[1]["fair_source"] == "reads.prior"
    # a match with no reads/legs price is admitted only through the declared anchor fair
    assert rows[2]["fair_source"] == "judgment.anchor_fair_had"
    assert rows[2]["fair"] == {"home": 0.7, "draw": 0.2, "away": 0.1}
    assert rows[2]["actual"] == "1"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_jczq_rows_use_closing_odds_only_when_no_read_time_price(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    _write(
        root / "jc-results.json",
        {
            "2026-09-19": {
                "周六001": {"match_id": "1", "ft_home": 1, "ft_away": 0},
                "周六002": {"match_id": "2", "ft_home": 0, "ft_away": 0},
                "周六003": {"match_id": "3", "ft_home": 0, "ft_away": 2},
            },
            "2026-09-20": {"周六004": {"match_id": "4", "ft_home": 2, "ft_away": 1}},
        },
    )
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    _write(
        root / "daily" / "2026-09-19" / "bold_odds.json",
        {
            "周六001": {"match_winner": {"fair_probability": fair, "bookmaker_count": 3}},
            "周六004": {"match_winner": {"fair_probability": fair, "bookmaker_count": 3}},
        },
    )
    closing_entry = {
        "match_id": "2",
        "fetched_at": "2026-09-22T04:00:00+00:00",
        "source": "titan007_history",
        "book_count": 40,
        "updated_at_min": "2026-09-17T10:00:00",
        "updated_at_max": "2026-09-19T19:50:00",
        "sharp": {
            "odds": {"home": 2.0, "draw": 3.4, "away": 3.6},
            "fair_probability": {"home": 0.45, "draw": 0.3, "away": 0.25},
            "opening_odds": {"home": 2.1, "draw": 3.3, "away": 3.5},
            "bookmaker_count": 5,
        },
        "all": {
            "fair_probability": {"home": 0.46, "draw": 0.3, "away": 0.24},
            "bookmaker_count": 40,
        },
        "per_book": [],
    }
    _write(
        root / "daily" / "2026-09-19" / "closing_odds.json",
        {
            "周六001": {**closing_entry, "match_id": "1"},
            "周六002": closing_entry,
            "周六003": {"match_id": "3", "unavailable": "too few books"},
        },
    )
    monkeypatch.setattr(corpus_build, "J", str(root))

    rows = {row["key"]: row for row in corpus_build.jczq_rows()}

    # read-time price wins and the closing block is attached alongside it
    assert rows["2026-09-19-周六001"]["fair_kind"] == "read_time"
    assert rows["2026-09-19-周六001"]["closing"]["sharp_fair"]["home"] == 0.45
    # no read-time price: the sharp closing fair becomes the price, marked as such
    assert rows["2026-09-19-周六002"]["fair_kind"] == "closing"
    assert rows["2026-09-19-周六002"]["fair_source"] == "titan007_closing"
    assert rows["2026-09-19-周六002"]["fair"]["home"] == 0.45
    # unavailable closing entry and no bold price → no row, never a guessed price
    assert "2026-09-19-周六003" not in rows
    # a late-night match keyed on the next calendar day's result page still finds the
    # previous day's board price
    assert rows["2026-09-20-周六004"]["fair_kind"] == "read_time"


def _kernel_fixture(tmp_path):
    import sqlite3

    db = tmp_path / "ontology.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        create table forecast_series(
            forecast_series_id text, match_id text, market_definition_id text);
        create table forecast_revisions(forecast_revision_id text, forecast_series_id text,
            revision_no int, status text, made_at text, information_cutoff_at text,
            prior_distribution_json text, belief_distribution_json text, commitment_tier text,
            actor_id text, model_name text, evidence_coverage text, evidence_quality text,
            falsifier text);
        create table matches(match_id text, current_revision_id text);
        create table match_revisions(match_revision_id text, match_id text, scheduled_at text);
        create table match_outcomes(match_id text, score_90 text, status text);
        create table external_identifiers(entity_id text, entity_type text, provider text,
            external_id text);
        create table market_quotes(match_id text, market_definition_id text, provider text,
            captured_at text, selection_id text, decimal_odds real, quote_status text);
        """
    )
    prior = json.dumps({"home": 0.5, "draw": 0.3, "away": 0.2})
    belief = json.dumps({"home": 0.55, "draw": 0.27, "away": 0.18})
    rows = [
        # m1: kernel outcome, two sporttery snapshots before kickoff, one after (ignored)
        ("m1", "s1", "M-2026-09-19-甲-乙", "zucai-canonical", "2-0"),
        # m2: no kernel outcome; resolved through the zucai issue file
        ("m2", "s2", "M-2026-09-19-丙-丁", "zucai-canonical", None),
        # m3: no kernel outcome; resolved through the jczq board via sporttery id
        ("m3", "s3", "777", "sporttery", None),
        # m4: nothing resolves → dropped
        ("m4", "s4", "M-2026-09-19-戊-己", "import", None),
    ]
    for match_id, series, ext, provider, score in rows:
        con.execute("insert into forecast_series values (?,?,?)", (series, match_id, "md-had"))
        con.execute(
            "insert into forecast_revisions values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"fr-{match_id}-1", series, 1, "committed", "2026-09-18T10:00:00+00:00", None,
             prior, prior, "commit", "ai", "model", "0.8", "0.7", "fal"),
        )
        con.execute(
            "insert into forecast_revisions values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"fr-{match_id}-2", series, 2, "committed", "2026-09-19T10:00:00+00:00", None,
             prior, belief, "commit", "ai", "model", "0.8", "0.7", "fal"),
        )
        con.execute("insert into matches values (?,?)", (match_id, f"rev-{match_id}"))
        con.execute(
            "insert into match_revisions values (?,?,?)",
            (f"rev-{match_id}", match_id, "2026-09-19T20:00:00+08:00"),
        )
        con.execute(
            "insert into external_identifiers values (?,?,?,?)", (match_id, "match", provider, ext)
        )
        if score:
            con.execute("insert into match_outcomes values (?,?,?)", (match_id, score, "final"))
    for captured, odds in (
        ("2026-09-18T08:00:00+08:00", (2.0, 3.3, 3.8)),
        ("2026-09-19T18:00:00+08:00", (1.9, 3.4, 4.0)),
        ("2026-09-19T21:00:00+08:00", (1.5, 3.9, 5.0)),
    ):
        for sel, price in zip(("sel-had-home", "sel-had-draw", "sel-had-away"), odds, strict=True):
            con.execute(
                "insert into market_quotes values (?,?,?,?,?,?,?)",
                ("m1", "md-had", "sporttery", captured, sel, price, "active"),
            )
    con.commit()
    con.close()
    return db


def test_kernel_rows_join_outcomes_quotes_and_prove_prospective(tmp_path, monkeypatch):
    db = _kernel_fixture(tmp_path)
    zroot, jroot = tmp_path / "zucai", tmp_path / "jczq"
    _write(zroot / "official-results.json", {"26130": "3 1"})
    _write(
        zroot / "26130-issue.json",
        {
            "matches": [
                {"match_no": "1", "match_date": "2026-09-19", "home_team": "丙", "away_team": "丁"},
                {"match_no": "2", "match_date": "2026-09-19", "home_team": "庚", "away_team": "辛"},
            ]
        },
    )
    _write(
        jroot / "jc-results.json",
        {"2026-09-19": {"周六009": {"match_id": "t9", "ft_home": 0, "ft_away": 1}}},
    )
    _write(
        jroot / "daily" / "2026-09-19" / "sporttery_markets.json",
        {
            "matchInfoList": [
                {
                    "subMatchList": [
                        {
                            "matchId": "777",
                            "matchNumStr": "周六009",
                            "businessDate": "2026-09-19",
                            "matchDate": "2026-09-19",
                            "homeTeamAbbName": "壬",
                            "awayTeamAbbName": "癸",
                        }
                    ]
                }
            ]
        },
    )
    monkeypatch.setattr(corpus_build, "Z", str(zroot))
    monkeypatch.setattr(corpus_build, "J", str(jroot))

    rows = {row["kernel"]["match_id"]: row for row in corpus_build.kernel_rows(str(db))}

    assert set(rows) == {"m1", "m2", "m3"}
    m1 = rows["m1"]
    assert m1["actual"] == "3" and m1["kernel"]["outcome_source"] == "match_outcomes"
    assert m1["kernel"]["revision_no"] == 2  # latest committed revision per match
    assert m1["belief_moved"] is True
    assert m1["provably_prospective"] is True
    assert m1["judged_at_source"] == "ontology.forecast_revisions.made_at"
    assert m1["quotes"]["sporttery"]["n_snapshots"] == 2  # post-kickoff snapshot excluded
    assert m1["quotes"]["sporttery"]["closing"]["home"] == 1.9
    assert m1["name"] == "甲 vs 乙"
    m2 = rows["m2"]
    assert m2["actual"] == "3" and m2["kernel"]["outcome_source"] == "official-results"
    assert (m2["issue"], m2["match_no"]) == ("26130", 1)
    m3 = rows["m3"]
    assert m3["actual"] == "0" and m3["kernel"]["outcome_source"] == "jc-results"
    assert (m3["jczq_date"], m3["jczq_no"], m3["titan007_id"]) == ("2026-09-19", "周六009", "t9")


def test_attach_kernel_prefers_keys_then_same_or_adjacent_day_fair_and_keeps_row_flag():
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    zucai = {"src": "zucai", "key": "26130-1", "issue": "26130", "match_no": 1,
             "date": "2026-09-19",
             "fair": fair, "provably_prospective": None}
    jczq = {"src": "jczq", "key": "2026-09-19-周六009", "date": "2026-09-19", "fair": fair}
    late = {"src": "jczq", "key": "2026-09-19-周六010", "date": "2026-09-19",
            "fair": {"home": 0.3, "draw": 0.3, "away": 0.4}}
    kernel = [
        {"src": "kernel", "key": "kernel-m2", "issue": "26130", "match_no": 1, "date": "2026-09-19",
         "fair": fair, "belief": fair, "kernel": {"match_id": "m2"}, "quotes": {},
         "provably_prospective": True},
        {"src": "kernel", "key": "kernel-m3", "jczq_no": "周六009", "jczq_date": "2026-09-19",
         "date": "2026-09-20", "fair": {"home": 0.1, "draw": 0.1, "away": 0.8}, "belief": fair,
         "kernel": {"match_id": "m3"}, "quotes": {}, "provably_prospective": True},
        {"src": "kernel", "key": "kernel-m5", "date": "2026-09-20",
         "fair": {"home": 0.31, "draw": 0.3, "away": 0.39}, "belief": fair,
         "kernel": {"match_id": "m5"}, "quotes": {}, "provably_prospective": False},
        {"src": "kernel", "key": "kernel-m6", "date": "2026-09-19",
         "fair": {"home": 0.9, "draw": 0.05, "away": 0.05}, "belief": fair,
         "kernel": {"match_id": "m6"}, "quotes": {}, "provably_prospective": True},
    ]

    rows, attached = corpus_build.attach_kernel([zucai, jczq, late], kernel)

    assert attached == 3
    assert zucai["kernel"]["match_id"] == "m2" and zucai["provably_prospective"] is None
    assert zucai["kernel_provably_prospective"] is True
    assert jczq["kernel"]["match_id"] == "m3"  # business-day key beats calendar date
    assert late["kernel"]["match_id"] == "m5"  # adjacent-day fair match
    assert [r["key"] for r in rows if r["src"] == "kernel"] == ["kernel-m6"]


def test_zucai_lane_reads_judgment_v1_research_and_reads_fix(tmp_path, monkeypatch):
    root = tmp_path / "zucai"
    root.mkdir()
    _write(root / "official-results.json", {"26129": "3 1"})
    _write(
        root / "26129-issue.json",
        {"matches": [
            {"match_no": 1, "match_date": "2026-09-19", "kickoff_bj": "2026-09-19 20:00"},
            {"match_no": 2, "match_date": "2026-09-19", "kickoff_bj": "2026-09-19 22:00"},
        ]},
    )
    _write(
        root / "26129-reads.json",
        [
            {"read_id": "26129-01-had", "prior": {"home": 0.5, "draw": 0.3, "away": 0.2},
             "confidence": 2},
            {"read_id": "26129-02-had", "prior": {"home": 0.2, "draw": 0.3, "away": 0.5},
             "confidence": 2},
        ],
    )
    # a corrected read for match 2 overrides the original by read_id
    _write(
        root / "26129-reads-fix.json",
        [{"read_id": "26129-02-had", "prior": {"home": 0.25, "draw": 0.3, "away": 0.45},
          "confidence": 4}],
    )
    # judgment-v1 naming variant is accepted when judgment.json is absent
    _write(root / "26129-judgment-v1.json", {"1": {"action": "31", "confidence": 3, "note": "n"}})
    # zucai per-match research with the proofs_met / legacy hole_location shape
    _write(
        root / "26129-research-m1.json",
        {
            "researched_at": "2026-09-19T10:00:00+08:00",
            "anchor_integrity": "fail",
            "directional_flags": [],
            "death_three_proofs": {
                "away": {"proofs_met": 2, "verdict": "dead"},
                "draw": "prose-only block",
            },
            "hole_location": {"opponent": "defense", "anchor": "midfield"},
            "confidence": 3,
        },
    )
    monkeypatch.setattr(corpus_build, "Z", str(root))

    rows = {row["match_no"]: row for row in corpus_build.zucai_rows()}

    assert rows[1]["call"] == "31" and rows[1]["note"] == "n"
    labels = rows[1]["labels"]
    assert labels["label_source"] == "research"
    assert labels["death_three_proofs"]["away"]["proof_count"] == "2/3"
    assert "draw" not in labels["death_three_proofs"]
    assert labels["hole_location_unit"] is None  # legacy shape never guessed
    assert labels["researched_at"] == "2026-09-19T10:00:00+08:00"
    assert rows[1]["provably_prospective"] is None  # research time is information only
    assert rows[2]["fair"] == {"home": 0.25, "draw": 0.3, "away": 0.45}
    assert rows[2]["conf"] == 4


def test_jczq_rows_take_belief_conf_and_note_from_latest_day_read(tmp_path, monkeypatch):
    root = tmp_path / "jczq"
    _write(
        root / "jc-results.json",
        {"2026-09-20": {"周日001": {"match_id": "1", "ft_home": 1, "ft_away": 0}}},
    )
    fair = {"home": 0.5, "draw": 0.3, "away": 0.2}
    _write(root / "daily" / "2026-09-20" / "bold_odds.json",
           {"周日001": {"match_winner": {"fair_probability": fair}}})
    _write(
        root / "daily" / "2026-09-20" / "reads.json",
        [
            {"read_id": "R-ai-jczq-2026-09-20-周日001-had-0900",
             "made_at": "2026-09-20T09:00:00+08:00",
             "prior": fair, "belief": {"home": 0.55, "draw": 0.27, "away": 0.18},
             "confidence": 3, "note": "early"},
            {"read_id": "R-ai-jczq-2026-09-20-周日001-had-1206",
             "made_at": "2026-09-20T12:06:00+08:00",
             "prior": fair, "belief": {"home": 0.6, "draw": 0.25, "away": 0.15},
             "confidence": 4, "note": "later"},
            {"read_id": "R-ai-jczq-2026-09-20-周日001-ttg-1206",
             "made_at": "2026-09-20T12:07:00+08:00",
             "prior": fair, "belief": fair, "market": "ttg"},
        ],
    )
    monkeypatch.setattr(corpus_build, "J", str(root))

    row = corpus_build.jczq_rows()[0]

    assert row["belief"] == {"home": 0.6, "draw": 0.25, "away": 0.15}
    assert row["belief_moved"] is True and row["conf"] == 4 and row["note"] == "later"
    assert row["read_id"].endswith("had-1206")
    assert row["provably_prospective"] is None  # read time does not feed the strict gate


def test_research_labels_carry_rubric_answers_and_sidecar_only_when_prospective(tmp_path):
    from experiments.corpus_build import _research_labels, _rubric_sidecar, _with_sidecar

    doc = {"anchor_integrity": "pass", "death_three_proofs": {},
           "rubric": {"version": "r1", "items": {
               "S_anchor_side": {"answer": "home", "p": 1.0, "abstain": False},
               "F_absence_home": {"answer": None, "p": None, "abstain": True}},
               "belief": {"3": 0.6, "1": 0.25, "0": 0.15}},
           "rubric_overridden": True}
    labels = _research_labels(doc)
    assert labels["rubric"] == {"S_anchor_side": {"answer": "home", "p": 1.0, "source_tier": None}}
    assert labels["rubric_version"] == "r1" and labels["rubric_belief"]["3"] == 0.6
    assert labels["rubric_overridden"] is True
    assert _research_labels({"anchor_integrity": "pass"})["rubric"] is None
    side = tmp_path / "rubric-周五001.json"
    side.write_text(json.dumps({"b": {"items": {"S_anchor_side": {"answer": "away", "p": 0.7,
                                                                  "abstain": False}},
                                      "belief": {"3": 0.4, "1": 0.3, "0": 0.3}},
                                "kappa": {"kappa": 0.0, "n": 1}, "model": "haiku",
                                "at": "2026-10-02T10:45:00+08:00"}), encoding="utf-8")
    early = _rubric_sidecar(str(side), kickoff_bj="2026-10-02T22:00:00+08:00")
    assert early["items"] == {"S_anchor_side": {"answer": "away", "p": 0.7, "source_tier": None}}
    assert early["model"] == "haiku" and early["kappa"]["n"] == 1 and early["prospective"] is True
    late = _rubric_sidecar(str(side), kickoff_bj="2026-10-02 09:00")   # 开球后读：留着但标非前瞻
    assert late["prospective"] is False and late["items"] == early["items"]
    assert _rubric_sidecar(str(tmp_path / "nope.json"), kickoff_bj=None) is None
    assert _with_sidecar(labels, early)["rubric_b"] == early and _with_sidecar(None, early) is None
