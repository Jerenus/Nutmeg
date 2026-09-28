"""Discovery 世界输入 · day 源：从当天决策泳道三份文件冻结 StructuralInputSnapshot。

设计：docs/superpowers/specs/2026-09-23-discovery-day-source-design.md §2。
不读内核、不写任何文件；面码以生成器口径为准（``candidates._FACE_ORDER`` = 3/1/0）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from nutmeg.discovery.audit import _CANDIDATE_AUDIT_POLICY_VERSION, _CandidateAuditOffer
from nutmeg.discovery.candidates import (
    CandidateGenerationInput,
    CandidateStructureTemplate,
    FaceBundleOption,
    OfferCandidateInput,
)
from nutmeg.discovery.online_inputs import StructuralInputSnapshot, freeze_structural_input

BJ = timezone(timedelta(hours=8))
FACE_CODE = {"home": "3", "draw": "1", "away": "0"}  # 生成器面码 3/1/0
_FACE_KEYS = ("home", "draw", "away")
_HAD_ODDS_KEYS = (("home", "h"), ("draw", "d"), ("away", "a"))
_PROBABILITY_QUANTUM = Decimal("0.000001")
CAPITAL_CAP_MINOR = 200_000  # ¥2,000 日帽
UNIT_STAKE_MINOR = 200  # ¥2 单注
MAX_TICKET_COUNT = 20
MAX_EXHAUSTIVE = 50_000
SOURCE_FILES = ("jczq-legs-base.json", "reads.json", "sporttery_markets.json")


def day_source_identity(jczq_dir: Path | str, day: str) -> str:
    return f"day:{(Path(jczq_dir) / 'daily' / day).resolve()}"


def day_fingerprint(day_dir: Path) -> str:
    h = hashlib.sha256()
    for name in SOURCE_FILES:
        p = Path(day_dir) / name
        h.update(name.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    return h.hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _probabilities(values: dict) -> tuple[tuple[str, str], ...]:
    """量化到 6 位并把残差记到最大面上——生成器要求三面 Decimal 和精确等于 1。"""
    quantized = {
        key: Decimal(str(values[key])).quantize(_PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN)
        for key in _FACE_KEYS
    }
    residual = Decimal("1") - sum(quantized.values(), Decimal("0"))
    if residual:
        largest = max(_FACE_KEYS, key=lambda key: quantized[key])
        quantized[largest] += residual
    return tuple((FACE_CODE[key], format(quantized[key], "f")) for key in _FACE_KEYS)


class DayBoardTooSmall(ValueError):
    """截止时刻未开球、且同时有 Read 与体彩 had 报价的场次不足两场（夜间作业记为跳过）。"""


def _market_rows(markets: dict) -> dict[str, dict]:
    return {
        sub["matchNumStr"]: sub
        for block in markets.get("matchInfoList") or []
        for sub in block.get("subMatchList") or []
        if sub.get("matchNumStr")
    }


def _kickoff_at(leg: dict, row: dict) -> datetime | None:
    """板面 `kickoff_bj` 优先，其次体彩 matchDate+matchTime；都没有 → None（按已开球排除）。"""
    if leg.get("kickoff_bj"):
        return datetime.fromisoformat(str(leg["kickoff_bj"]))
    if row.get("matchDate") and row.get("matchTime"):
        return datetime.fromisoformat(f"{row['matchDate']}T{row['matchTime']}+08:00")
    return None


def _face_bundles(faces: str) -> tuple[FaceBundleOption, ...]:
    bundles = [FaceBundleOption(bundle_code=faces, face_codes=tuple(faces))]
    if len(faces) > 1:
        bundles += [FaceBundleOption(bundle_code=f, face_codes=(f,)) for f in faces]
    return tuple(bundles)


def _precedents(leg: dict) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        tuple(map(str, p))[:3] for p in leg.get("precedents") or [] if len(p) >= 3
    )



def _prescribed_bundles(faces: str) -> tuple[frozenset[str], ...]:
    bundles = [frozenset(faces), frozenset()]
    bundles += [frozenset({f}) for f in faces if len(faces) > 1]
    return tuple(bundles)

def read_structural_input_from_day(
    jczq_dir: Path | str,
    day: str,
    *,
    cutoff_at: str,
    max_templates: int = 4,
) -> StructuralInputSnapshot:
    day_dir = Path(jczq_dir) / "daily" / day
    board_path = day_dir / "jczq-legs-base.json"
    board_bytes = board_path.read_bytes()
    reads_bytes = (day_dir / "reads.json").read_bytes()
    markets_bytes = (day_dir / "sporttery_markets.json").read_bytes()
    legs = json.loads(board_bytes)["legs"]
    reads = {r["match_id"]: r for r in json.loads(reads_bytes) if isinstance(r, dict)}
    cutoff = datetime.fromisoformat(cutoff_at)
    rows = _market_rows(json.loads(markets_bytes))
    # 处方的采集时刻 = 最晚一条 Read 的 made_at（表态与 Read 同一次落盘），不用文件 mtime：
    # mtime 跟墙钟走，会让同一份输入在 cutoff 过后突然「超过 cutoff」。
    made_ats = sorted(str(r.get("made_at") or "") for r in reads.values() if r.get("made_at"))
    board_captured = made_ats[-1] if made_ats else f"{day}T00:00:00+08:00"

    offers, audits, refs = [], [], []
    for code, leg in sorted(legs.items()):
        read = reads.get(leg.get("match_id"))
        row = rows.get(code) or {}
        had = row.get("had") or {}
        if not read or not had.get("h"):
            continue
        kickoff = _kickoff_at(leg, row)
        if kickoff is None or kickoff <= cutoff:
            # 前瞻纪律：截止时已开球（或开球时刻不明）的场不进世界，留引用说明为什么少了
            refs.append(
                {
                    "kind": "excluded_started",
                    "id": code,
                    "source_revision": f"kickoff:{kickoff.isoformat() if kickoff else 'unknown'}",
                    "captured_at": (kickoff or cutoff).isoformat(),
                }
            )
            continue
        faces = str(leg.get("faces") or "310")
        belief = _probabilities(read["belief"])
        prior = _probabilities(read["prior"])
        quote_ids = tuple(
            (FACE_CODE[k], f"sporttery:{day}:{code}:had:{FACE_CODE[k]}") for k in _FACE_KEYS
        )
        odds = tuple((FACE_CODE[k], str(had[c])) for k, c in _HAD_ODDS_KEYS)
        offers.append(
            OfferCandidateInput(
                official_match_no=code,
                official_offer_revision_id=f"{day}:{code}:had",
                match_id=str(leg["match_id"]),
                market_definition_id="md-had",
                probabilities=belief,
                allowed_face_bundles=_face_bundles(faces),
                omission_allowed=True,
                quote_ids_by_face=quote_ids,
                booked_decimal_odds_by_face=odds,
            )
        )
        audits.append(
            _CandidateAuditOffer(
                official_match_no=code,
                market_definition_id="md-had",
                belief=belief,
                prior=prior,
                # 处方 = 表态面集合、其中每个单面、以及「丢掉这场」（omission_allowed）；
                # 其余组合是偏离，由具名规则 stance 记 WARN 而不是让审计器抛错。
                prescribed_face_bundles=_prescribed_bundles(faces),
                rule_ids=("stance",),
                anchor_integrity=str(leg.get("anchor_integrity") or "unknown"),
                face_precedents=_precedents(leg),
            )
        )
        read_sha = _sha(json.dumps(read, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        refs.append(
            {
                "kind": "forecast",
                "id": str(read["read_id"]),
                "source_revision": f"{read.get('status', 'draft')}:{read_sha}",
                "captured_at": str(read["made_at"]),
            }
        )
        captured = f"{had.get('updateDate') or day}T{had.get('updateTime') or '00:00:00'}+08:00"
        had_sha = _sha(json.dumps(had, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        for _face, qid in quote_ids:
            refs.append(
                {"kind": "quote", "id": qid, "source_revision": had_sha, "captured_at": captured}
            )
    if not offers:
        raise DayBoardTooSmall(
            "day source has no unstarted match with both a Read and sporttery odds"
        )
    refs.append(
        {
            "kind": "prescription",
            "id": f"{day}:legs-base",
            "source_revision": _sha(board_bytes),
            "captured_at": board_captured,
        }
    )
    codes = tuple(o.official_match_no for o in offers)
    templates = tuple(
        CandidateStructureTemplate(
            kind="jczq_pass",
            structure_code=f"pass-{n}-1",
            eligible_official_match_nos=codes,
            required_offer_count=n,
            maximum_groups=1,
            pass_size=n,
        )
        for n in range(2, min(len(codes), 1 + max_templates) + 1)
    )
    if not templates:
        raise DayBoardTooSmall(
            "day source needs at least two unstarted matches for a pass template"
        )
    candidate_input = CandidateGenerationInput(
        lane="jczq",
        ticket_kind="jczq_pass",
        currency="CNY",
        capital_cap_minor=CAPITAL_CAP_MINOR,
        unit_stake_minor=UNIT_STAKE_MINOR,
        maximum_ticket_count=MAX_TICKET_COUNT,
        maximum_exhaustive_candidate_count=MAX_EXHAUSTIVE,
        offers=tuple(offers),
        templates=templates,
    )
    slate = f"day:{day}:{_sha(markets_bytes)[:16]}"
    return freeze_structural_input(
        candidate_input=candidate_input,
        references=tuple(refs),
        business_date=day,
        task_snapshot_hash=_sha(board_bytes + reads_bytes),
        slate_revision_id=slate,
        board_slate_revision_id=slate,
        cutoff_at=cutoff_at,
        audit_policy_revision=_CANDIDATE_AUDIT_POLICY_VERSION,
        audit_offers=tuple(audits),
        source_identity=day_source_identity(jczq_dir, day),
    )
