from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_RESOLVED_MARKS = ("已裁", "已行权", "取代", "resolved", "complete", "完成")
_PROBABILITY_TOLERANCE = Decimal("0.001")
_ModelT = TypeVar("_ModelT", bound=BaseModel)


def parse_shanghai(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"invalid Shanghai datetime: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(_SHANGHAI)


def _validate_probability_sum(values: list[float]) -> None:
    total = sum((Decimal(str(value)) for value in values), start=Decimal("0"))
    if abs(total - Decimal("1")) > _PROBABILITY_TOLERANCE:
        raise ValueError("probabilities must sum to 1 within 0.001")


def _validate_match_keys(values: dict[str, object], *, label: str) -> None:
    for key in values:
        if not re.fullmatch(r"(?:[1-9]|1[0-4])", key):
            raise ValueError(f"{label} keys must be decimal match numbers from 1 to 14")


class StrictSource(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ZucaiSourceRef(StrictSource):
    label: str
    url: str
    captured_at: str


class ZucaiIssueMatch(StrictSource):
    match_no: int = Field(ge=1, le=14)
    competition: str
    home_team: str
    away_team: str
    kickoff_bj: str
    match_date: str
    asian_ref: str | None = None


class ZucaiIssueDocument(StrictSource):
    issue_id: str = Field(pattern=r"^\d{5}$")
    sale_deadline: str | None = None
    sources: list[ZucaiSourceRef]
    matches: list[ZucaiIssueMatch] = Field(min_length=1, max_length=14)

    @model_validator(mode="after")
    def require_unique_matches(self) -> ZucaiIssueDocument:
        match_numbers = [match.match_no for match in self.matches]
        if len(match_numbers) != len(set(match_numbers)):
            raise ValueError("issue match numbers must be unique")
        return self


class ProbabilityTriple(StrictSource):
    home: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_probability_sum(self) -> ProbabilityTriple:
        _validate_probability_sum([self.home, self.draw, self.away])
        return self


class PrepScreenItem(StrictSource):
    match_no: int = Field(ge=1, le=14)
    name: str
    face: str | None = None
    top1: float | None = Field(default=None, ge=0, le=1)
    draw: float | None = Field(default=None, ge=0, le=1)


class PrepScreens(StrictSource):
    strong_anchors: list[PrepScreenItem]
    coinflip: list[PrepScreenItem]
    fattest_draws: list[PrepScreenItem]
    missing_euro_anchor: list[PrepScreenItem]
    missing_ttg_anchor: list[PrepScreenItem]


class AlignmentItem(StrictSource):
    match_no: int = Field(ge=1, le=14)
    home: str
    away: str
    competition: str


class PrepAlignment(StrictSource):
    unmatched: list[AlignmentItem]
    ambiguous: list[AlignmentItem]


class ZucaiPrepRecord(StrictSource):
    name: str
    league: str
    kickoff_bj: str
    match_date: str
    sporttery_match_num: str | None
    fair_had: ProbabilityTriple
    sporttery_had_date: str | None
    hhad_line: str | None = None
    ttg_anchor: bool
    lambdas: list[float] = Field(alias="lambda", min_length=3, max_length=3)
    fit_loss: float
    dc_had: list[float] = Field(min_length=3, max_length=3)
    top_scores: list[tuple[str, float]]
    ttg_bands: dict[str, float]
    over25: float = Field(ge=0, le=1)
    margin: dict[str, float]
    home_by_2plus: float = Field(ge=0, le=1)
    away_by_2plus: float = Field(ge=0, le=1)
    hhad_cover: dict[str, float | str] | None


class ZucaiPrepDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    run_date: str
    slot: str
    captured_at: datetime
    n_matches: int = Field(ge=1, le=14)
    alignment: PrepAlignment
    screens: PrepScreens
    records: dict[str, ZucaiPrepRecord]
    judgment: None = None

    @field_validator("captured_at", mode="after")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=_SHANGHAI)
        return value.astimezone(_SHANGHAI)

    @field_validator("records", mode="after")
    @classmethod
    def validate_record_keys(
        cls, values: dict[str, ZucaiPrepRecord]
    ) -> dict[str, ZucaiPrepRecord]:
        _validate_match_keys(values, label="prep record")
        return values


class ZucaiPrescription(StrictSource):
    singles: dict[str, str]
    doubles: dict[str, str]
    fulls: list[str]
    expected_broken_legs: float
    correction_log: str
    difficulty_price_cny: int
    audit_R432: str


class ZucaiPendingAdjudication(StrictSource):
    id: str
    status: str
    q: str
    options: str | None = None
    default: str | None = None
    reason: str | None = None
    evidence_rejected: str | None = None
    deployment_gate: str | None = None

    @property
    def requires_operator(self) -> bool:
        return not any(mark in self.status for mark in _RESOLVED_MARKS)


class ZucaiPrediction(StrictSource):
    id: str
    claim: str
    falsifier: str


class ZucaiRecordedOutcomes(StrictSource):
    settled_at: str
    source: str
    draw_result: str
    position: str
    prescription_score: str
    ticket_counterfactuals: str
    predictions: dict[str, str]
    adjudication_outcomes: dict[str, str]
    key_lessons: str


class ZucaiRxDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    registered_at: AwareDatetime
    decision: str
    capital_report: dict[str, str]
    prescription_P14: ZucaiPrescription
    ticket_versions: dict[str, str]
    pending_adjudications: list[ZucaiPendingAdjudication]
    predictions: list[ZucaiPrediction]
    notes: str
    outcomes: ZucaiRecordedOutcomes | None = None


class ZucaiCandidateLeg(StrictSource):
    name: str
    faces: str
    confidence: int = Field(ge=0, le=5)
    directional_flags: list[tuple[str, str]]
    nondirectional_flags: list[str]
    anchor_integrity: str
    fair: ProbabilityTriple
    precedents: list[tuple[str, str, str]]

    @field_validator("faces", mode="after")
    @classmethod
    def validate_faces(cls, value: str) -> str:
        if not value or any(face not in "310" for face in value) or len(set(value)) != len(value):
            raise ValueError("faces must contain unique 3, 1, or 0 values")
        return value


class ZucaiCandidateDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    version: str
    legs: dict[str, ZucaiCandidateLeg]
    candidate_id: str = Field(exclude=True)

    @field_validator("legs", mode="after")
    @classmethod
    def validate_leg_keys(
        cls, values: dict[str, ZucaiCandidateLeg]
    ) -> dict[str, ZucaiCandidateLeg]:
        _validate_match_keys(values, label="candidate leg")
        return values

    def faces(self) -> dict[str, str]:
        return {match_no: leg.faces for match_no, leg in self.legs.items()}


class ZucaiNightResult(StrictSource):
    code: Literal["3", "1", "0"]
    ft: str
    home: str
    away: str
    status: str


class ZucaiNightDocument(StrictSource):
    issue: str = Field(pattern=r"^\d{5}$")
    source: str
    fetched_at: AwareDatetime
    results: dict[str, ZucaiNightResult]
    skipped: list[str]

    @field_validator("results", mode="after")
    @classmethod
    def validate_result_keys(
        cls, values: dict[str, ZucaiNightResult]
    ) -> dict[str, ZucaiNightResult]:
        _validate_match_keys(values, label="night result")
        return values


class ZucaiArtifactBundle(StrictSource):
    issue: ZucaiIssueDocument
    prep: ZucaiPrepDocument
    rx: ZucaiRxDocument
    candidates: list[ZucaiCandidateDocument]
    night_snapshots: list[ZucaiNightDocument] = Field(default_factory=list)

    def fallback_deadline(self) -> datetime | None:
        if self.issue.sale_deadline:
            return parse_shanghai(self.issue.sale_deadline)
        kickoffs = [parse_shanghai(match.kickoff_bj) for match in self.issue.matches]
        return min(kickoffs, default=None)

    def match_record(self, match_no: int) -> ZucaiPrepRecord | None:
        return self.prep.records.get(str(match_no))


class OperatorArtifactError(ValueError):
    pass


class ZucaiArtifactRepository:
    RX_PATTERN = re.compile(r"^(?P<issue>\d{5})-rx\.json$")
    PREP_PATTERN = re.compile(r"^(?P<issue>\d{5})-prep-(?P<slot>[^/]+)\.json$")
    CANDIDATE_PATTERN = re.compile(
        r"^(?P<issue>\d{5})-legs-(?P<candidate>[A-Za-z0-9][A-Za-z0-9_-]*)\.json$"
    )
    NIGHT_PATTERN = re.compile(r"^(?P<issue>\d{5})-night-\d{4}-\d{2}-\d{2}-af\.json$")

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def discover_issues(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted(
            {
                match.group("issue")
                for path in self._root.iterdir()
                if path.is_file() and (match := self.RX_PATTERN.fullmatch(path.name))
            }
        )

    def load(self, issue: str) -> ZucaiArtifactBundle:
        if not re.fullmatch(r"\d{5}", issue):
            raise OperatorArtifactError("zucai issue must be five digits")
        issue_doc = self._read(f"{issue}-issue.json", ZucaiIssueDocument)
        rx = self._read(f"{issue}-rx.json", ZucaiRxDocument)
        prep = self._latest_prep(issue)
        candidates = self._candidate_documents(issue)
        night_snapshots = self._night_documents(issue)
        if issue_doc.issue_id != issue or rx.issue != issue or prep.issue != issue:
            raise OperatorArtifactError("artifact issue binding mismatch")
        if any(candidate.issue != issue for candidate in candidates):
            raise OperatorArtifactError("candidate issue binding mismatch")
        if any(snapshot.issue != issue for snapshot in night_snapshots):
            raise OperatorArtifactError("night snapshot issue binding mismatch")
        return ZucaiArtifactBundle(
            issue=issue_doc,
            prep=prep,
            rx=rx,
            candidates=candidates,
            night_snapshots=night_snapshots,
        )

    def _read(self, name: str, model_type: type[_ModelT]) -> _ModelT:
        try:
            return model_type.model_validate(self._json_payload(self._path(name)))
        except (ValidationError, ValueError) as error:
            raise OperatorArtifactError(f"invalid operator artifact {name}: {error}") from error

    def _path(self, name: str) -> Path:
        path = (self._root / name).resolve()
        if path.parent != self._root:
            raise OperatorArtifactError("artifact path escaped root")
        return path

    @staticmethod
    def _json_payload(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OperatorArtifactError(f"invalid operator artifact {path.name}") from error
        if not isinstance(payload, dict):
            raise OperatorArtifactError(f"invalid operator artifact {path.name}: expected object")
        return dict(payload)

    def _latest_prep(self, issue: str) -> ZucaiPrepDocument:
        documents: list[tuple[datetime, str, ZucaiPrepDocument]] = []
        if self._root.exists():
            for path in self._root.iterdir():
                match = self.PREP_PATTERN.fullmatch(path.name)
                if path.is_file() and match and match.group("issue") == issue:
                    document = self._read(path.name, ZucaiPrepDocument)
                    documents.append((document.captured_at, path.name, document))
        if not documents:
            raise OperatorArtifactError(f"invalid operator artifact: no prep for {issue}")
        return max(documents, key=lambda item: (item[0], item[1]))[2]

    def _candidate_documents(self, issue: str) -> list[ZucaiCandidateDocument]:
        documents: list[ZucaiCandidateDocument] = []
        identities: dict[str, str] = {}
        if not self._root.exists():
            return documents
        for path in self._artifact_paths():
            match = self.CANDIDATE_PATTERN.fullmatch(path.name)
            if not path.is_file() or not match or match.group("issue") != issue:
                continue
            candidate_id = match.group("candidate")
            normalized = candidate_id.casefold()
            if normalized in identities:
                raise OperatorArtifactError(
                    "candidate identity collision: "
                    f"{identities[normalized]} and {candidate_id}"
                )
            identities[normalized] = candidate_id
            payload = self._json_payload(self._path(path.name))
            if "candidate_id" in payload:
                raise OperatorArtifactError("invalid candidate_id supplied by source artifact")
            payload["candidate_id"] = candidate_id
            try:
                documents.append(ZucaiCandidateDocument.model_validate(payload))
            except ValidationError as error:
                raise OperatorArtifactError(
                    f"invalid operator artifact {path.name}: {error}"
                ) from error
        return sorted(documents, key=lambda document: document.candidate_id)

    def _artifact_paths(self) -> list[Path]:
        return list(self._root.iterdir())

    def _night_documents(self, issue: str) -> list[ZucaiNightDocument]:
        documents: list[tuple[datetime, str, ZucaiNightDocument]] = []
        if not self._root.exists():
            return []
        for path in self._root.iterdir():
            match = self.NIGHT_PATTERN.fullmatch(path.name)
            if path.is_file() and match and match.group("issue") == issue:
                document = self._read(path.name, ZucaiNightDocument)
                documents.append((document.fetched_at, path.name, document))
        return [item[2] for item in sorted(documents, key=lambda item: (item[0], item[1]))]
