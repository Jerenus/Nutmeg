from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.product.operator_runtime import OntologyWriterLease, OperatorRuntimeError


def test_writer_shared_leases_are_compatible_and_exclusive_is_guarded(
    tmp_path: Path,
) -> None:
    first = OntologyWriterLease.shared(tmp_path / "data")
    second = OntologyWriterLease.shared(tmp_path / "data")
    exclusive = OntologyWriterLease.exclusive(tmp_path / "data")
    first.acquire()
    second.acquire()
    try:
        with pytest.raises(OperatorRuntimeError) as caught:
            exclusive.acquire()
        assert caught.value.code == "ontology_maintenance_conflict"
    finally:
        second.release()
        first.release()

    exclusive.acquire()
    exclusive.release()
