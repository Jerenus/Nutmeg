"""Nutmeg CLI package.

This module holds the shared ``app`` Typer object (the entry point
``nutmeg.interfaces.cli:app``) and the few names the subsystem command modules
reach through ``import nutmeg.interfaces.cli as _cli`` (``typer``, ``Path``,
``json``, ``console``, ``get_settings``, ``build_ontology_kernel``). Keep it this
small: every ``nutmeg`` invocation imports it, so anything imported here at top
level is paid by every timer run. Subsystems import what they need inside their
command functions.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from nutmeg.config.settings import get_settings

__all__ = ["Path", "app", "build_ontology_kernel", "console", "get_settings", "json", "typer"]

app = typer.Typer(help="Nutmeg CLI")
console = Console()


def build_ontology_kernel(settings):
    """Lazy kernel factory: the kernel imports most of ``nutmeg.ontology``."""
    from nutmeg.ontology import build_ontology_kernel as _build

    return _build(settings)


# --- command registration ----------------------------------------------------
# Importing these subsystem modules executes their ``@app.command()`` decorators,
# registering every command on the shared ``app`` above. Done last so the package
# namespace (factories, helpers, options) is fully populated before they load.
# E402 is expected: registration must run after the namespace is built.
from nutmeg.interfaces.cli import account as account  # noqa: E402
from nutmeg.interfaces.cli import arena as arena  # noqa: E402
from nutmeg.interfaces.cli import ask as ask  # noqa: E402
from nutmeg.interfaces.cli import betslip as betslip  # noqa: E402
from nutmeg.interfaces.cli import correction as correction  # noqa: E402
from nutmeg.interfaces.cli import crowd as crowd  # noqa: E402
from nutmeg.interfaces.cli import day as day  # noqa: E402
from nutmeg.interfaces.cli import decision as decision  # noqa: E402
from nutmeg.interfaces.cli import gym as gym  # noqa: E402
from nutmeg.interfaces.cli import inbox as inbox  # noqa: E402
from nutmeg.interfaces.cli import judgment as judgment  # noqa: E402
from nutmeg.interfaces.cli import load as load  # noqa: E402
from nutmeg.interfaces.cli import ontology as ontology  # noqa: E402
from nutmeg.interfaces.cli import research as research  # noqa: E402
from nutmeg.interfaces.cli import retro as retro  # noqa: E402
from nutmeg.interfaces.cli import rsi as rsi  # noqa: E402
from nutmeg.interfaces.cli import rubric as rubric  # noqa: E402
from nutmeg.interfaces.cli import zucai as zucai  # noqa: E402

if __name__ == "__main__":
    app()
