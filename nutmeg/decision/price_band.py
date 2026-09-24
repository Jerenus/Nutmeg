"""Mechanical opening-to-current price-band observations."""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.market_data import devig, load_bold_odds_snapshot
from nutmeg.decision.microstructure import market_microstructure

_FACES = ("home", "draw", "away")


def _load_match_ids(day_dir: Path) -> dict[str, str | None]:
    path = day_dir / "jczq-legs-base.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    legs = doc.get("legs") if isinstance(doc, dict) else None
    if not isinstance(legs, dict):
        return {}
    return {
        str(code): (str(leg["match_id"]) if leg.get("match_id") is not None else None)
        for code, leg in legs.items()
        if isinstance(leg, dict)
    }


def write_price_band_artifacts(
    *, day: str, data_dir: Path, captured_at: str
) -> dict[str, int]:
    """Write one artifact per captured match; unavailable measurements remain null."""
    jczq_dir = Path(data_dir) / "jczq"
    day_dir = jczq_dir / "daily" / day
    snapshots = load_bold_odds_snapshot(day, jczq_dir)
    if not snapshots:
        raise ValueError(f"bold_odds 不存在或为空：{day_dir / 'bold_odds.json'}")
    match_ids = _load_match_ids(day_dir)
    written = 0
    missing_opening = 0
    for code, markets in sorted(snapshots.items()):
        market = markets.get("match_winner")
        if market is None:
            continue
        fair_now = dict(market.fair_probability or {}) or devig(dict(market.odds or {}))
        fair_open = devig(dict(market.opening_odds or {}))
        complete = all(face in fair_now and face in fair_open for face in _FACES)
        if not complete:
            missing_opening += 1
        micro = market_microstructure(market)
        payload = {
            "match_id": match_ids.get(code),
            "fair_now": fair_now or None,
            "fair_open": fair_open or None,
            "drift_pp": (
                {
                    face: round((fair_now[face] - fair_open[face]) * 100, 6)
                    for face in _FACES
                }
                if complete
                else {face: None for face in _FACES}
            ),
            "book_disagreement_pp": micro.get("dispersion_pp"),
            "books": micro.get("books"),
            "captured_at": captured_at,
        }
        (day_dir / f"price-band-{code}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1
    return {"written": written, "missing_opening": missing_opening}


def _by_match_no(path: Path) -> dict[int, dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = doc.get("matches") if isinstance(doc, dict) else None
    return {
        int(row["match_no"]): row
        for row in rows or []
        if isinstance(row, dict) and row.get("match_no") is not None
    }


def write_zucai_price_band_artifacts(
    *, issue: str, day: str, data_dir: Path, captured_at: str
) -> dict[str, int]:
    """足彩一期每场一份价格带观察，与竞彩同目录同 glob（F5 登记的 artifact_glob 冻结在
    jczq/daily/{day}/price-band-*.json）。

    开盘→当前只有 titan007 国际盘有（{issue}-odds-intl.json，只覆盖已对齐的场）；
    其余场用 500 在售页均值（{issue}-odds.json）只记当前，开盘与位移留 null。
    """
    zucai_dir = Path(data_dir) / "zucai"
    ids_path = zucai_dir / f"{issue}-store-ids.json"
    try:
        ids = json.loads(ids_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"store-ids 不存在或不可读：{ids_path}") from exc
    rows = ids.values() if isinstance(ids, dict) else ids
    intl = _by_match_no(zucai_dir / f"{issue}-odds-intl.json")
    sale = _by_match_no(zucai_dir / f"{issue}-odds.json")
    day_dir = Path(data_dir) / "jczq" / "daily" / day
    day_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    missing_opening = 0
    for row in rows:
        if not row.get("match_id") or row.get("match_no") is None:
            continue
        match_no = int(row["match_no"])
        book = intl.get(match_no) or {}
        if book.get("odds"):
            source = "titan007"
            fair_now = devig(dict(book["odds"]))
            fair_open = devig(dict(book.get("opening_odds") or {}))
            micro = book.get("micro") or {}
            disagreement, books = micro.get("dispersion_pp"), book.get("books")
        elif match_no in sale:
            source = "sale_page"
            fair_now = devig({face: sale[match_no][face] for face in _FACES
                              if sale[match_no].get(face)})
            fair_open, disagreement, books = {}, None, None
        else:
            source, fair_now, fair_open, disagreement, books = None, {}, {}, None, None
        complete = all(face in fair_now and face in fair_open for face in _FACES)
        if not complete:
            missing_opening += 1
        payload = {
            "match_id": str(row["match_id"]),
            "issue": issue,
            "match_no": match_no,
            "source": source,
            "fair_now": fair_now or None,
            "fair_open": fair_open or None,
            "drift_pp": (
                {
                    face: round((fair_now[face] - fair_open[face]) * 100, 6)
                    for face in _FACES
                }
                if complete
                else {face: None for face in _FACES}
            ),
            "book_disagreement_pp": disagreement,
            "books": books,
            "captured_at": captured_at,
        }
        (day_dir / f"price-band-z{issue}-{match_no:02d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1
    return {"written": written, "missing_opening": missing_opening}
