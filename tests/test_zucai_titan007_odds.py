

def test_single_candidate_still_requires_name_match():
    """唯一候选也必须过队名校验——否则同刻的别场会被静默顶包。

    2026-09-15 实测：26124 场13「阿罗卡-圣克拉」当日不在竞彩板面，而「本菲卡-吉维森特」
    恰好同为 01:00 开球，唯一候选被无条件接受 → 身份错配（26111 同类死法）。
    """
    from datetime import datetime

    from nutmeg.data.titan007 import Titan007BoardRow
    from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007

    ko = datetime(2026, 9, 14, 1, 0)
    board = [
        Titan007BoardRow(
            match_id="9999", match_no="周日099", kickoff=ko,
            home_names=("本菲卡", "賓菲加"), away_names=("吉维森特", "基爾維森特"),
        )
    ]
    matches = [{
        "match_no": 13, "home_team": "阿罗卡", "away_team": "圣克拉",
        "kickoff_bj": "2026-09-14 01:00",
    }]

    assert align_zucai_to_titan007(matches, board) == {}, "同刻别场不得顶包"


def test_single_candidate_with_matching_name_is_kept():
    from datetime import datetime

    from nutmeg.data.titan007 import Titan007BoardRow
    from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007

    ko = datetime(2026, 9, 13, 23, 30)
    board = [
        Titan007BoardRow(
            match_id="1234", match_no="周日001", kickoff=ko,
            home_names=("曼彻斯特联", "曼聯"), away_names=("曼彻斯特城", "曼城"),
        )
    ]
    matches = [{
        "match_no": 1, "home_team": "曼联", "away_team": "曼彻斯特城",
        "kickoff_bj": "2026-09-13 23:30",
    }]

    assert list(align_zucai_to_titan007(matches, board)) == [1]
