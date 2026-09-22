import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_broadcast import due_broadcasts, read_sent, render_broadcast, send_all

BJ = timezone(timedelta(hours=8))
DEC = [
    {"id": "read:周三001", "kind": "approve_read", "subject": "周三001 A vs B", "status": "open",
     "deadline": "2026-09-23T19:30:00+08:00", "default_action": "草稿不入库＝跟市场"},
    {"id": "plan:26132", "kind": "plan_choose_commit", "subject": "26132 定案", "status": "open",
     "deadline": "2026-09-23T21:00:00+08:00", "default_action": "空仓"},
    {"id": "rsi:0", "kind": "rsi", "subject": "C11", "status": "open", "deadline": None,
     "default_action": "hold"},
    {"id": "read:周三009", "kind": "approve_read", "subject": "done one", "status": "done",
     "deadline": "2026-09-23T19:30:00+08:00", "default_action": "x"},
]


def test_due_broadcasts_fire_t30_then_t10_once_each():
    at_19_05 = datetime(2026, 9, 23, 19, 5, tzinfo=BJ)
    due = due_broadcasts(DEC, now=at_19_05, sent=set())
    assert [(b.key, b.minutes_left) for b in due] == [("read:周三001@T30", 25)]
    assert due_broadcasts(DEC, now=at_19_05, sent={"read:周三001@T30"}) == []
    at_19_25 = datetime(2026, 9, 23, 19, 25, tzinfo=BJ)
    due_after_t30 = due_broadcasts(DEC, now=at_19_25, sent={"read:周三001@T30"})
    assert [b.key for b in due_after_t30] == ["read:周三001@T10"]
    at_20_45 = datetime(2026, 9, 23, 20, 45, tzinfo=BJ)
    assert [b.key for b in due_broadcasts(DEC, now=at_20_45, sent=set())] == ["plan:26132@T30"]


def test_render_broadcast_states_time_and_default_action():
    b = due_broadcasts(DEC, now=datetime(2026, 9, 23, 19, 5, tzinfo=BJ), sent=set())[0]
    text = render_broadcast(b)
    assert text.startswith("⏰ 剩 25 分（截止 19:30）")
    assert "周三001 A vs B" in text and "未定则默认：草稿不入库＝跟市场" in text
    assert "不代下单" in text


def test_send_all_records_sent_keys_and_survives_sender_errors(tmp_path: Path):
    calls: list[str] = []

    def sender(text: str) -> None:
        calls.append(text)
        if "26132" in text:
            raise RuntimeError("telegram down")

    now = datetime(2026, 9, 23, 20, 45, tzinfo=BJ)
    dec = DEC + [{"id": "read:周三010", "kind": "approve_read", "subject": "late", "status": "open",
                  "deadline": "2026-09-23T21:05:00+08:00", "default_action": "跟市场"}]
    report = send_all(dec, data_dir=tmp_path, date="2026-09-23", now=now, sender=sender)
    assert report["sent"] == ["read:周三010@T30"] and report["failed"] == ["plan:26132@T30"]
    assert read_sent(tmp_path, "2026-09-23") == {"read:周三010@T30"}
    log_path = tmp_path / "daily" / "2026-09-23" / "broadcasts.jsonl"
    rows = log_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["key"] == "read:周三010@T30"



def test_same_deadline_decisions_are_sent_as_one_message(tmp_path: Path):
    sent: list[str] = []
    dec = [
        {"id": "read:a", "kind": "approve_read", "subject": "A vs B", "status": "open",
         "deadline": "2026-09-23T02:00:00+08:00", "default_action": "跟市场"},
        {"id": "read:b", "kind": "approve_read", "subject": "C vs D", "status": "open",
         "deadline": "2026-09-23T02:00:00+08:00", "default_action": "跟市场"},
    ]
    now = datetime(2026, 9, 23, 1, 35, tzinfo=BJ)
    report = send_all(dec, data_dir=tmp_path, date="2026-09-22", now=now, sender=sent.append)
    assert len(sent) == 1 and "A vs B" in sent[0] and "C vs D" in sent[0]
    assert report["sent"] == ["read:a@T30", "read:b@T30"]
    assert read_sent(tmp_path, "2026-09-22") == {"read:a@T30", "read:b@T30"}
