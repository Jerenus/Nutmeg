"""lineup_watch：无票不打网 / 关键人与研究相反→推一次 / 全包格不推 / 倒计时去重 /
位移只报票内未开球场。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg, register_slip
from nutmeg.decision.bj_time import BJ
from nutmeg.decision.lineup_watch import (
    compare,
    key_names,
    parse_shift_table,
    run_countdown,
    run_lineup_check,
    run_shift_diff,
    watch,
)

ISSUE = "26199"
KICK = datetime(2026, 11, 1, 22, 0, tzinfo=BJ)
DEADLINE = datetime(2026, 11, 1, 21, 30, tzinfo=BJ)

RESEARCH = {
    "summary": "主队中轴完整，Marquinhos 与 Nuno Mendes 缺阵；Zabarnyi 顶上中卫。",
    "hole_location": {"unit": "attack", "side": "home", "priced_in": True,
                      "detail": "破门端缺 Dembélé（伤），Vitinha 组织核心在。"},
}


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, kind, key, fingerprint, text, *, dry_run=False, **_):
        self.sent.append((kind, key, text))
        return "sent"


def _issue(tmp: Path, *, kick: datetime = KICK, deadline: datetime = DEADLINE) -> Path:
    z = tmp / "zucai"
    z.mkdir(parents=True, exist_ok=True)
    doc = {"issue_id": ISSUE, "sale_deadline": deadline.strftime("%Y-%m-%d %H:%M"),
           "matches": [{"match_no": i, "home_team": f"主{i}", "away_team": f"客{i}",
                        "kickoff_bj": kick.strftime("%Y-%m-%d %H:%M")} for i in range(1, 15)]}
    (z / f"{ISSUE}-issue.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")
    (z / f"{ISSUE}-research-m1.json").write_text(json.dumps(RESEARCH, ensure_ascii=False),
                                                  "utf-8")
    (z / f"{ISSUE}-research-m2.json").write_text(json.dumps(RESEARCH, ensure_ascii=False),
                                                  "utf-8")
    return z


def _slip(tmp: Path, faces: dict[str, str], *, purchased: bool = True) -> None:
    faces = dict(faces)
    for no in range(14, 0, -1):                 # 任九至少 9 场：其余用全包补齐（全包不算票面押了）
        if len(faces) >= 9:
            break
        faces.setdefault(str(no), "310")
    legs = [SlipLeg(key=no, name="", market="had", line=None,
                    selections=tuple({"3": "home", "1": "draw", "0": "away"}[c] for c in f),
                    odds=(), fair={"home": 0.4, "draw": 0.3, "away": 0.3})
            for no, f in faces.items()]
    register_slip(tmp, BetSlip(slip_id=f"{ISSUE}-T1", channel="renjiu", placed_at="2026-11-01",
                               legs=legs, issue=ISSUE, purchased=purchased, faces=faces),
                  now=datetime(2026, 11, 1, 15, 0, tzinfo=BJ))


def _fetchers(calls: list, lineups: list[dict]):
    def fixtures(day):
        calls.append(("fixtures", day))
        return [{"fixture_id": "F1", "home": "主1", "away": "客1", "kickoff": KICK},
                {"fixture_id": "F2", "home": "主2", "away": "客2", "kickoff": KICK}]

    def lineup(fid):
        calls.append(("lineups", fid))
        return lineups

    return fixtures, lineup


_RESOLVE = {"主1": "h1", "客1": "a1", "主2": "h2", "客2": "a2"}.get


def test_key_names_split_by_absence_context():
    present, absent = key_names(RESEARCH)
    assert {"Marquinhos", "Nuno Mendes", "Dembélé"} <= absent
    assert {"Zabarnyi", "Vitinha"} <= present


def test_compare_only_flags_contradictions_on_sheet():
    lineups = [{"team": "H", "xi": ["Marquinhos", "K. Mbappé"], "bench": ["Vitinha"]}]
    v = compare(RESEARCH, lineups)
    assert v.status == "affected"
    assert v.absent_but_starting == ["Marquinhos"]
    assert v.present_but_bench == ["Vitinha"]
    # 名单上根本没有的名字（Zabarnyi 不在 XI 也不在替补）不算事
    v2 = compare(RESEARCH, [{"team": "H", "xi": ["K. Mbappé"], "bench": []}])
    assert v2.status == "no_impact"


def test_no_real_ticket_never_touches_network(tmp_path: Path):
    _issue(tmp_path)
    _slip(tmp_path, {"1": "3"}, purchased=False)          # 试玩票不算
    calls: list = []
    rec = Recorder()
    now = KICK - timedelta(minutes=60)
    evs = run_lineup_check(tmp_path, ISSUE, now=now, notify_fn=rec,
                           fetchers=_fetchers(calls, []), resolve=_RESOLVE)
    assert evs == [{"issue": ISSUE, "status": "no_real_ticket"}]
    assert calls == [] and rec.sent == []


def test_outside_window_exits_without_network(tmp_path: Path):
    _issue(tmp_path)
    _slip(tmp_path, {"1": "3"})
    calls: list = []
    evs = run_lineup_check(tmp_path, ISSUE, now=KICK - timedelta(hours=3), notify_fn=Recorder(),
                           fetchers=_fetchers(calls, []), resolve=_RESOLVE)
    assert evs == [{"issue": ISSUE, "status": "no_match_in_window"}]
    assert calls == []


def test_key_person_contradiction_pushes_once(tmp_path: Path):
    _issue(tmp_path)
    _slip(tmp_path, {"1": "3", "2": "310"})               # 场 2 全包 → 不看
    calls: list = []
    rec = Recorder()
    lineups = [{"team": "H", "xi": ["Marquinhos"], "bench": []}]
    now = KICK - timedelta(minutes=60)
    evs = run_lineup_check(tmp_path, ISSUE, now=now, notify_fn=rec,
                           fetchers=_fetchers(calls, lineups), resolve=_RESOLVE)
    assert [e["match_no"] for e in evs] == ["1"]
    assert evs[0]["status"] == "pushed"
    assert rec.sent[0][1] == f"{ISSUE}:1"
    assert "研究记缺阵但首发：Marquinhos" in rec.sent[0][2]
    assert f"票 {ISSUE}-T1 该格 3" in rec.sent[0][2]
    assert ("lineups", "F2") not in calls                 # 全包格不拉名单
    # 第二轮：状态文件已记 pushed → 不再推、不再打网
    calls.clear()
    evs2 = run_lineup_check(tmp_path, ISSUE, now=now + timedelta(minutes=10), notify_fn=rec,
                            fetchers=_fetchers(calls, lineups), resolve=_RESOLVE)
    assert evs2 == [] and calls == [] and len(rec.sent) == 1
    state = json.loads((tmp_path / "zucai" / f"{ISSUE}-lineup-watch.json").read_text("utf-8"))
    assert state["lineup"]["1"]["status"] == "pushed"


def test_no_lineups_yet_is_recorded_and_retried(tmp_path: Path):
    _issue(tmp_path)
    _slip(tmp_path, {"1": "3"})
    rec = Recorder()
    now = KICK - timedelta(minutes=70)
    evs = run_lineup_check(tmp_path, ISSUE, now=now, notify_fn=rec,
                           fetchers=_fetchers([], []), resolve=_RESOLVE)
    assert evs[0]["status"] == "no_lineups" and rec.sent == []
    lineups = [{"team": "H", "xi": ["Zabarnyi"], "bench": ["Vitinha"]}]
    evs2 = run_lineup_check(tmp_path, ISSUE, now=now + timedelta(minutes=15), notify_fn=rec,
                            fetchers=_fetchers([], lineups), resolve=_RESOLVE)
    assert evs2[0]["status"] == "pushed" and "研究记在阵却替补：Vitinha" in rec.sent[0][2]


def test_countdown_only_without_ticket_and_dedupes(tmp_path: Path):
    z = _issue(tmp_path)
    (z / f"{ISSUE}-packet.md").write_text(
        "# 包\n## §1\n…\n## §2 胆与票\n凑不齐 → **机器默认空仓**；9双 超帽\n", "utf-8")
    rec = Recorder()
    t30 = DEADLINE - timedelta(minutes=28)
    assert run_countdown(tmp_path, ISSUE, now=t30, notify_fn=rec)[0]["status"] == "pushed"
    assert "停售前 28 分" in rec.sent[0][2] and "机器默认空仓" in rec.sent[0][2]
    assert run_countdown(tmp_path, ISSUE, now=t30 + timedelta(minutes=5),
                         notify_fn=rec)[0]["status"] == "already_pushed"
    t10 = DEADLINE - timedelta(minutes=9)
    assert run_countdown(tmp_path, ISSUE, now=t10, notify_fn=rec)[0]["status"] == "pushed"
    assert len(rec.sent) == 2
    # 停售后 / 太早：不推
    assert run_countdown(tmp_path, ISSUE, now=DEADLINE + timedelta(minutes=1),
                         notify_fn=rec) == []
    assert run_countdown(tmp_path, ISSUE, now=DEADLINE - timedelta(hours=2), notify_fn=rec) == []
    # 有实票：不推
    _slip(tmp_path, {"1": "3"})
    assert run_countdown(tmp_path, ISSUE, now=DEADLINE - timedelta(minutes=9),
                         notify_fn=Recorder())[0]["status"] == "has_real_ticket"


def test_shift_diff_reports_only_ticket_matches_not_kicked_off(tmp_path: Path):
    z = _issue(tmp_path)
    (z / f"{ISSUE}-diff-afternoon-revision.md").write_text(
        "# diff\n\n| 场 | 对阵 | Δ主 | Δ平 | Δ客 | 现 fair |\n|---|---|---|---|---|---|\n"
        "| 6 | 弗赖堡-拜仁 | +2.5 | +1.3 | -3.8 | 17.7/18.9/63.4 |\n"
        "| 5 | 霍芬海-勒沃 | -1.8 | -0.2 | +2.0 | 30.9/23.4/45.7 |\n"
        "| 3 | 曼联-伯恩茅 | -4.0 | +0.9 | +3.1 | 40.3/27.3/32.4 |\n", "utf-8")
    rows = parse_shift_table((z / f"{ISSUE}-diff-afternoon-revision.md").read_text("utf-8"))
    assert [r["match_no"] for r in rows] == ["6", "5", "3"] and rows[0]["max_abs"] == 3.8
    _slip(tmp_path, {"6": "0", "5": "30"})               # 3 不在票内，5 位移 2.0 不够
    rec = Recorder()
    before = DEADLINE - timedelta(hours=2)
    evs = run_shift_diff(tmp_path, ISSUE, now=before, notify_fn=rec)
    assert evs[0]["status"] == "pushed" and "6 弗赖堡-拜仁" in rec.sent[0][2]
    assert "曼联" not in rec.sent[0][2] and "霍芬海" not in rec.sent[0][2]
    assert run_shift_diff(tmp_path, ISSUE, now=before, notify_fn=rec)[0]["status"] == \
        "already_pushed"
    # 开球后的位移不可行动
    (z / f"{ISSUE}-lineup-watch.json").unlink()
    assert run_shift_diff(tmp_path, ISSUE, now=KICK + timedelta(minutes=1),
                          notify_fn=Recorder())[0]["status"] == "no_shift_in_ticket"


def test_watch_builds_fetchers_only_when_a_ticket_match_is_in_window(tmp_path: Path):
    _issue(tmp_path)
    _slip(tmp_path, {"1": "3"})
    built: list = []

    def factory():
        built.append(1)
        return _fetchers([], [{"team": "H", "xi": ["Marquinhos"], "bench": []}])

    rep = watch(tmp_path, issue=ISSUE, now=KICK - timedelta(hours=5), notify_fn=Recorder(),
                fetchers_factory=factory, resolve=_RESOLVE)
    assert built == [] and rep["issues"][ISSUE]["lineup"][0]["status"] == "no_match_in_window"
    rec = Recorder()
    rep = watch(tmp_path, issue=ISSUE, now=KICK - timedelta(minutes=50), notify_fn=rec,
                fetchers_factory=factory, resolve=_RESOLVE)
    assert built == [1] and rep["issues"][ISSUE]["lineup"][0]["status"] == "pushed"
    assert len(rec.sent) == 1


def test_find_fixture_falls_back_to_league_and_kickoff_when_teams_unresolved():
    from nutmeg.decision.lineup_watch import find_fixture
    board = [{"fixture_id": "A", "home": "Paris Saint Germain", "away": "Lyon",
              "league": "Ligue 1", "kickoff": KICK},
             {"fixture_id": "B", "home": "Nice", "away": "Lens", "league": "Ligue 1",
              "kickoff": KICK + timedelta(hours=2)},
             {"fixture_id": "C", "home": "Toronto", "away": "Halifax", "league": "NSL",
              "kickoff": KICK}]
    none = lambda name: None  # noqa: E731 - 法甲六队无实体
    lg = {"法甲": "fra-ligue1", "Ligue 1": "fra-ligue1"}.get
    assert find_fixture(board, "日尔曼", "里昂", KICK, "法甲", none, lg) == "A"
    # 同时刻同联赛两场 → 不猜
    board.append({"fixture_id": "D", "home": "Metz", "away": "Brest", "league": "Ligue 1",
                  "kickoff": KICK})
    assert find_fixture(board, "日尔曼", "里昂", KICK, "法甲", none, lg) is None
    assert find_fixture(board, "日尔曼", "里昂", KICK, "", none, lg) is None


def test_pushes_carry_issue_link_only_when_configured_and_fingerprint_ignores_it(tmp_path: Path):
    """Task 9.1：三类推送配了前缀才带 `{base}/issue/<期>`；指纹对加链接前的正文算。"""
    class FpRecorder(Recorder):
        def __call__(self, kind, key, fingerprint, text, *, dry_run=False, **_):
            self.sent.append((kind, fingerprint, text))
            return "sent"

    def push_all(base_url: str) -> list[tuple[str, str, str]]:
        tmp = tmp_path / (base_url and "on" or "off")
        z = _issue(tmp)
        (z / f"{ISSUE}-packet.md").write_text("## §2\n**机器默认空仓**\n", "utf-8")
        (z / f"{ISSUE}-diff-afternoon-revision.md").write_text(
            "| 场 | 对阵 | Δ主 | Δ平 | Δ客 | 现 fair |\n|---|---|---|---|---|---|\n"
            "| 1 | 主1-客1 | +2.5 | +1.3 | -3.8 | 17.7/18.9/63.4 |\n", "utf-8")
        rec = FpRecorder()
        run_countdown(tmp, ISSUE, now=DEADLINE - timedelta(minutes=28), notify_fn=rec,
                      base_url=base_url)
        _slip(tmp, {"1": "3"})
        run_shift_diff(tmp, ISSUE, now=DEADLINE - timedelta(hours=2), notify_fn=rec,
                       base_url=base_url)
        run_lineup_check(tmp, ISSUE, now=KICK - timedelta(minutes=60), notify_fn=rec,
                         fetchers=_fetchers([], [{"team": "H", "xi": ["Marquinhos"],
                                                  "bench": []}]),
                         resolve=_RESOLVE, base_url=base_url)
        return rec.sent

    off, on = push_all(""), push_all("http://mac.local:8787/")
    kinds = ["zucai.countdown", "zucai.shift", "zucai.lineup"]
    assert [k for k, _, _ in off] == kinds == [k for k, _, _ in on]
    assert all("http" not in text for _, _, text in off)
    for (_, fp_off, t_off), (_, fp_on, t_on) in zip(off, on, strict=True):
        assert t_on == f"{t_off}\nhttp://mac.local:8787/issue/{ISSUE}"
        assert fp_on == fp_off


def test_watch_reads_link_prefix_from_settings_when_not_passed(tmp_path: Path, monkeypatch):
    from nutmeg.config.settings import get_settings

    z = _issue(tmp_path)
    (z / f"{ISSUE}-packet.md").write_text("## §2\n**机器默认空仓**\n", "utf-8")
    monkeypatch.setenv("NUTMEG_DECISION_WEB_URL", "http://h/")
    get_settings.cache_clear()
    try:
        rec = Recorder()
        watch(tmp_path, issue=ISSUE, now=DEADLINE - timedelta(minutes=28), notify_fn=rec)
        assert rec.sent[0][2].endswith(f"\nhttp://h/issue/{ISSUE}")
    finally:
        get_settings.cache_clear()
