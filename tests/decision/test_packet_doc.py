import json

from nutmeg.decision.packet_doc import load_packet


def _write(tmp_path, doc):
    z = tmp_path / "zucai"
    z.mkdir(exist_ok=True)
    (z / "26151-packet.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")


def test_missing_packet_is_reported_not_raised(tmp_path):
    out = load_packet(tmp_path, "26151")
    assert out["rows"] == [] and out["errors"] == ["缺 26151-packet.json（/zucai-packet 未出旁车）"]


def test_rows_keyed_and_bad_rows_named(tmp_path):
    _write(tmp_path, {"issue": "26151", "rows": [
        {"no": "13", "tier": "B", "k": 4, "n": 6, "default": "31"},
        {"no": "2", "tier": "B"}],
        "main_shape": {"label": "W4", "faces": {"13": "3"}}})
    out = load_packet(tmp_path, "26151")
    assert [r["no"] for r in out["rows"]] == ["2", "13"]          # 按场号排
    assert out["by_no"]["13"]["k"] == 4
    assert out["errors"] == ["场 2 缺字段：default、k、n"]
    assert out["main_shape"]["faces"] == {"13": "3"}


def test_full_contract_rows_load_clean(tmp_path):
    full = {"no": "13", "tier": "B", "k": 4, "n": 6, "default": "31",
            "cond": "① ✗ ② ✓ ③ ✓ ④ ✗ ⑤ ✓ ⑥ ✓", "flip": "卡利亚里·弱·价内 → 1(19)",
            "dead": "排 0 10", "lineup_at": "02:45", "lineup_before_close": False,
            "unknowable": "首发 02:45（停售后 9 小时）", "watch": "Gollini、Koné 替代者",
            "anchor": "fail：门将 Svilar、后腰 Koné 缺", "hole": "锚方·门将·价内",
            "consistency": "同向", "crowd": "PM $45k 反卡利亚里 −$1.0k", "converged": True,
            "sfc_default": None,
            "c1": {"path": "卡利亚里·弱·价内 → 1(19)", "move": "低位反击、定位球",
                   "q3a": "弱：8 轮 6 球", "fav": "罗马近 2 场失 7",
                   "weak_check": "① 缺 ② ✗ ③ ✗"},
            "d1": {"cell": "B·锚方·价内·弱·球员", "layer": "档×洞位×价态×标签", "n": 20,
                   "open": "16/2/2", "hot_pct": 80, "p1": 71, "diff": 9}}
    coin = {"no": "1", "tier": "D", "k": None, "n": None, "default": "丢", "sfc_default": "31",
            "c1": None, "d1": {"cell": "D·无洞·价内·真实·无", "layer": "档×洞位", "n": 40,
                               "open": "19/11/10", "hot_pct": 48, "p1": 40, "diff": 7}}
    _write(tmp_path, {
        "issue": "26151", "built_at": "2026-10-27T10:25:00+08:00",
        "default": {"action": "空仓", "reason": "许可证层：许可胆 0"},
        "rows": [full, coin],
        "main_shape": {"label": "W4 4单5双", "faces": {"13": "3", "4": "10"},
                       "price": 64, "p": 0.0784},
        "alternatives": [{"label": "W1 1单8双", "role": "替代", "faces": {"13": "3", "2": "31"}}],
        "signed_bold": []})
    out = load_packet(tmp_path, "26151")
    assert out["errors"] == []
    assert out["by_no"]["1"]["c1"] is None and out["by_no"]["13"]["d1"]["diff"] == 9
    assert out["default"]["action"] == "空仓" and out["built_at"].startswith("2026-10-27")
    assert out["alternatives"][0]["role"] == "替代"


def test_non_canonical_faces_named(tmp_path):
    _write(tmp_path, {"issue": "26151", "rows": [
        {"no": "4", "tier": "B", "k": 2, "n": 6, "default": "01"}],
        "main_shape": {"label": "W4", "faces": {"4": "01", "13": "3"}},
        "alternatives": [{"label": "W1", "faces": {"9": "13"}}]})
    out = load_packet(tmp_path, "26151")
    assert out["errors"] == ["场 4 默认面 01 应写 10",
                             "W4 场 4 面 01 应写 10",
                             "W1 场 9 面 13 应写 31"]


def test_delivery_check_rejects_empty_packet_despite_clean_loader(tmp_path):
    from nutmeg.decision.packet_doc import check_delivery

    _write(tmp_path, {"issue": "26151", "rows": []})
    assert load_packet(tmp_path, "26151")["errors"] == []
    out = check_delivery(tmp_path, "26151")
    assert out["ready"] is False
    assert any("14" in e for e in out["errors"])
    assert any("主形" in e for e in out["errors"])


def test_delivery_check_rejects_duplicate_rows_and_uncomputed_shape(tmp_path):
    from nutmeg.decision.packet_doc import check_delivery

    row = {"no": "1", "tier": "B", "k": 2, "n": 6, "default": "31"}
    _write(tmp_path, {"issue": "26151", "rows": [row] * 14,
                     "main_shape": {"label": "未核算", "faces": {"1": "3"}}})
    out = check_delivery(tmp_path, "26151")
    assert any("重复" in e for e in out["errors"])
    assert any("票面" in e for e in out["errors"])


def test_complete_reference_packet_does_not_require_betting_or_bridge(tmp_path):
    from nutmeg.decision.packet_doc import check_delivery

    nos = [str(i) for i in range(1, 15)]
    shape = {"label": "参考", "faces": {n: "31" for n in nos[:9]}, "price": 1024, "p": .1}
    rows = [{"no": n, "tier": "B", "k": 1, "n": 6, "default": "31",
             "anchor": "待首发", "hole": "未确认", "flip": "真实", "cond": "①否，其余未知",
             "watch": "首发", "c1": {"q3a": "未知"}, "d1": {"n": 20}} for n in nos]
    _write(tmp_path, {"issue": "26151", "rows": rows,
                     "default": {"action": "空仓", "reason": "无许可胆"},
                     "main_shape": shape, "alternatives": [{**shape, "role": "替代"}]})
    zdir = tmp_path / "zucai"
    (zdir / "26151-store-ids.json").write_text(json.dumps({n: {
        "match_id": f"m{n}", "snapshot_id": f"s{n}",
        "fair": {"home": .7, "draw": .2, "away": .1}} for n in nos}))
    for n in nos:
        (zdir / f"26151-research-m{n}.json").write_text('{}')
    for suffix in ("packet.md", "judgment-brief.md", "draft.json", "counter-matrix.md",
                   "structure-align.md", "dead-align.md", "team-load.json", "polymarket.json"):
        (zdir / f"26151-{suffix}").write_text('reference fixture')
    out = check_delivery(tmp_path, "26151")
    assert out["ready"] is True and out["errors"] == []
    assert "不表示桥/实购/复盘已完成" in out["scope"]
