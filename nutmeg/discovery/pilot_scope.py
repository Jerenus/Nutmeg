"""D0 shadow-only cannot be promoted by a deployment row or a fixture claim."""

from __future__ import annotations


def validate_control_scope(scope: dict, pilot_contract: dict) -> None:
    # No approved prospective revision is shipped with D6. Only a separate
    # reviewed contract and its Action may eventually enable control here.
    raise ValueError("reviewed prospective scope contract is required for control")
