def test_package_exports_team_and_league():
    """包级导出——Team/League(实体层)从 nutmeg.decision 可 import。"""
    import nutmeg.decision as decision
    from nutmeg.decision import League, Team
    assert Team("t-1").id == "t-1" and League("l-1").id == "l-1"
    assert {"Team", "League"} <= set(decision.__all__)
