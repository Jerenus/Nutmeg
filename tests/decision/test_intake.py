"""票据收件（2026-11-02 产品形态 Task 10.5）：data URL 解码与限制、存原图、读数规整（场号 / 面序 /
看不清）、看图失败照样落盘、对账（截图读不到的项不算对上）。"""
import base64
import json

import pytest

from nutmeg.decision import intake

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def test_decode_and_save(tmp_path):
    raw, ext = intake.decode_data_url(URL)
    assert raw == PNG and ext == "png"
    iid = intake.save_image(tmp_path, "26155", raw, ext)
    assert intake.image_path(tmp_path, "26155", iid).read_bytes() == PNG
    assert intake.image_path(tmp_path, "26155", "../x") is None


@pytest.mark.parametrize("bad", ["", "hello", "data:text/plain;base64,aGk=",
                                 "data:image/gif;base64,R0lG"])
def test_decode_refuses_non_images(bad):
    with pytest.raises(ValueError):
        intake.decode_data_url(bad)


def test_normalize_orders_faces_and_flags_doubt():
    got = intake.normalize({
        "channel": "renjiu", "issue_seen": 26155, "notes": "64", "stake": "128.00元",
        "multiplier": 1, "status_text": "试玩",
        "cells": [{"no": "3", "faces": "13", "doubt": True, "options": ["3", "13", "x"]},
                  {"no": 1, "faces": "3"}, {"no": "1", "faces": "0"},
                  {"no": "15", "faces": "3"}, {"no": "2", "faces": "平"},
                  {"no": "4", "faces": "0", "options": ["10"]}]})
    assert [c["no"] for c in got["cells"]] == ["1", "3", "4"]
    assert got["cells"][1] == {"no": "3", "faces": "31", "doubt": True, "options": ["3"], "why": ""}
    assert got["cells"][2]["doubt"] is True                     # 列了别的读法＝看不清
    assert len(got["dropped"]) == 3                             # 重复的场、15、读不出面
    assert (got["notes"], got["stake"], got["issue_seen"]) == (64, 128, "26155")
    assert intake.normalize({"channel": "大乐透"})["channel"] is None


def test_read_ticket_writes_result_and_names_reach_prompt(tmp_path):
    iid = intake.save_image(tmp_path, "26155", PNG, "png")
    seen = {}

    def runner(system, stdin, *, folder):
        seen.update(stdin=stdin, folder=folder)
        return 0, "抄好了：" + json.dumps({"channel": "shengfucai", "cells": [
            {"no": "1", "faces": "0"}], "notes": 1, "stake": 2}), {"duration_s": 20.0}

    out = intake.read_ticket(tmp_path, "26155", iid, names={"1": "甲-乙"}, runner=runner)
    assert out["state"] == "done" and out["read"]["cells"][0]["faces"] == "0"
    assert "1: 甲-乙" in seen["stdin"] and seen["folder"] == intake.intake_dir(tmp_path, "26155")
    assert intake.load_result(tmp_path, "26155", iid)["duration_s"] == 20.0


def test_read_ticket_failure_is_recorded(tmp_path):
    iid = intake.save_image(tmp_path, "26155", PNG, "png")
    out = intake.read_ticket(tmp_path, "26155", iid, names={},
                             runner=lambda *a, **k: (1, "Please run /login", {}))
    assert out["state"] == "failed" and "/login" in out["error"]
    out = intake.read_ticket(tmp_path, "26155", iid, names={},
                             runner=lambda *a, **k: (0, "看不出来", {}))
    assert out["state"] == "failed"
    with pytest.raises(KeyError):
        intake.read_ticket(tmp_path, "26155", "nope", names={})


def test_reconcile_needs_both_seen_and_equal():
    assert intake.reconcile({"notes": 64, "stake": 128}, notes=64, stake=128)["ok"] is True
    half = intake.reconcile({"notes": 32, "stake": 128}, notes=64, stake=128)
    assert half["ok"] is False and [r["ok"] for r in half["rows"]] == [False, True]
    assert intake.reconcile({"notes": None, "stake": 128}, notes=64, stake=128)["ok"] is False
