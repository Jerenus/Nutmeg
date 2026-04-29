from __future__ import annotations
from pathlib import Path
from nutmeg.services.psychology.calibration.recorder import Recorder
from nutmeg.services.psychology.engine import PsychologyEngine
from nutmeg.services.psychology.guardrails import BudgetGuard, ConvictionGate
from nutmeg.services.psychology.inspiration import InspirationParser, InspirationStore
from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.reconciliator import Reconciliator
from nutmeg.services.psychology.schemas import DataLeg, Scheme, SignalReading
from nutmeg.services.psychology.signals.base import SignalContext

class _Stub:
    name = "stub"
    def __init__(self, outcome: str, conviction: float):
        self._outcome = outcome
        self._conviction = conviction
    def evaluate(self, ctx: SignalContext):
        return [SignalReading("stub", str(ctx.fixtures[0]["id"]), "HHAD", self._outcome, self._conviction, [], [], None)]

def test_lifecycle_with_inspiration_force_psychology_below_gate(tmp_path: Path) -> None:
    insp_store = InspirationStore(base_dir=tmp_path / "inspiration")
    note = InspirationParser(llm=FakeLLMCompleter(responses=[])).parse("今天必须心理，反着来", date="2026-04-29")
    insp_store.write_raw(date="2026-04-29", text=note.raw_text)
    insp_store.write_parsed(date="2026-04-29", tags=note.parsed_tags, raw_text=note.raw_text, parse_method=note.parse_method, timestamp=note.timestamp)
    engine = PsychologyEngine(providers=[_Stub(outcome="away_win", conviction=0.55)])
    recon = Reconciliator(ConvictionGate(0.7), BudgetGuard(1))
    data_scheme = Scheme(name="data", legs=[DataLeg("L1","psg-bay","HHAD","home_win",2.10)])
    verdicts = engine.evaluate(ctx=SignalContext(date="2026-04-29", fixtures=[{"id": "psg-bay", "home_team_name": "PSG", "away_team_name": "Bayern"}], snapshots={}, odds={}), data_picks={"psg-bay": {"HHAD": "home_win"}})
    report = recon.reconcile(data_scheme=data_scheme, psychology_verdicts=verdicts, inspiration=insp_store.read(date="2026-04-29"))
    assert report.final_scheme.legs[0].provenance == "inspiration_forced"
    rec = Recorder(base_dir=tmp_path / "inspiration")
    rec.record(date="2026-04-29", report=report)
    rec.update_outcome(date="2026-04-29", fixture_id="psg-bay", market="HHAD", actual_outcome="away_win")
    rows = rec.read(date="2026-04-29")
    assert rows[0]["hit"] is True
    assert rows[0]["provenance"] == "inspiration_forced"
