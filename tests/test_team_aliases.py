from nutmeg.data.team_aliases import (
    load_club_team_aliases,
    load_national_team_aliases,
    load_team_aliases,
)


def test_national_table_strips_comment_and_covers_board():
    aliases = load_national_team_aliases()
    assert "_comment" not in aliases
    for zh, en in (("荷兰", "Netherlands"), ("乌兹别克", "Uzbekistan"), ("法国", "France"),
                   ("北爱尔兰", "Northern Ireland"), ("秘鲁", "Peru"), ("西班牙", "Spain")):
        assert aliases[zh] == en


def test_club_table_strips_comment_and_covers_board():
    aliases = load_club_team_aliases()
    assert "_comment" not in aliases
    for zh, en in (("伏伊伏丁", "Vojvodina"), ("费伦茨", "Ferencvarosi TC"),
                   ("索陆军", "CSKA Sofia"), ("德里城", "Derry City"),
                   ("斯海杜克", "HNK Hajduk Split"), ("日利纳", "Žilina")):
        assert aliases[zh] == en


def test_merged_table_has_both():
    merged = load_team_aliases()
    assert "_comment" not in merged
    assert merged["法国"] == "France" and merged["索陆军"] == "CSKA Sofia"
