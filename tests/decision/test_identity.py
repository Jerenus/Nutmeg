from nutmeg.decision.identity import canonical_match_id, norm_team


def test_norm_team_strips_and_casefolds():
    assert norm_team(" 阿根廷 ") == "阿根廷"
    assert norm_team("Real Madrid") == "realmadrid"


def test_canonical_id_same_for_same_match_across_channels():
    # 竞彩 abbrev 与 zucai 名一致时,两通道算出同一 id
    a = canonical_match_id("阿根廷", "埃及", "2026-07-06")
    b = canonical_match_id(" 阿根廷 ", "埃及", "2026-07-06")
    assert a == b == "M-2026-07-06-阿根廷-埃及"


def test_canonical_id_distinct_matches():
    assert (canonical_match_id("葡萄牙", "西班牙", "2026-07-06")
            != canonical_match_id("阿根廷", "埃及", "2026-07-06"))
