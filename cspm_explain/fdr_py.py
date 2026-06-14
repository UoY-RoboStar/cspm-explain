"""Thin Python wrapper around the pybind11 fdr_ext module.

Provides:
  - library_init / library_exit / has_valid_license / version
  - Session           — load CSP files, uncompile events, get machine names
  - FdrAssertion      — execute, passed, counterexamples
  - FdrCounterexample — detect type, extract behaviour/debug context
  - DebugContext      — decompose behaviours, reveal τ events
  - Behaviour         — trace, states, min_acceptance, machine_name

Constants: INVALID_EVENT = 0, TAU = 1
"""
from __future__ import annotations

import sys
import os

# Locate fdr_ext next to this file inside the cspm_explain package.
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

import fdr_ext as _ext  # noqa: E402  (compiled extension)

# ---------------------------------------------------------------------------
# Re-export constants
# ---------------------------------------------------------------------------

INVALID_EVENT: int = _ext.INVALID_EVENT
TAU: int           = _ext.TAU

# ---------------------------------------------------------------------------
# Library lifecycle (called automatically on import)
# ---------------------------------------------------------------------------

_ext.library_init()


def has_valid_license() -> bool:
    return _ext.has_valid_license()


def version() -> str:
    return _ext.version()

# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

class Behaviour:
    """Wraps fdr_ext.Behaviour and adds convenience methods."""

    def __init__(self, raw: "_ext.Behaviour", session: "Session"):
        self._raw = raw
        self._session = session

    # raw fdr_ext.Behaviour for passing back into DebugContext methods
    @property
    def _ext_beh(self) -> "_ext.Behaviour":
        return self._raw

    def machine_name(self) -> str:
        return self._session._raw.machine_name_from_behaviour(self._raw)

    def trace(self) -> list[int]:
        return list(self._raw.trace())

    def states(self) -> list[str]:
        return self._raw.states(self._session._raw)

    def min_acceptance(self) -> list[int]:
        return list(self._raw.min_acceptance())

# ---------------------------------------------------------------------------
# DebugContext
# ---------------------------------------------------------------------------

class DebugContext:
    def __init__(self, raw: "_ext.DebugContext", session: "Session"):
        self._raw = raw
        self._session = session

    def initialise(self):
        self._raw.initialise()

    def root_behaviours(self) -> list[Behaviour]:
        return [Behaviour(b, self._session) for b in self._raw.root_behaviours()]

    def children(self, beh: Behaviour) -> list[Behaviour]:
        return [Behaviour(b, self._session) for b in self._raw.behaviour_children(beh._ext_beh)]

    def full_alphabet(self) -> list[int]:
        return list(self._raw.full_alphabet())

    def reveal_taus_in_trace(self, beh: Behaviour) -> list[int]:
        return list(self._raw.reveal_taus_in_trace(beh._ext_beh))

    def reveal_tau(self, beh: Behaviour, index: int) -> Behaviour | None:
        r = self._raw.reveal_tau(beh._ext_beh, index)
        return Behaviour(r, self._session) if r is not None else None

# ---------------------------------------------------------------------------
# Counterexample
# ---------------------------------------------------------------------------

class FdrCounterexample:
    def __init__(self, raw_ce, session: "Session"):
        self._raw = raw_ce
        self._session = session

    def is_deadlock(self) -> bool:
        return isinstance(self._raw, _ext.DeadlockCounterexample)

    def is_property(self) -> bool:
        return isinstance(self._raw, _ext.PropertyCounterexample)

    def behaviour(self) -> Behaviour | None:
        pce = self._raw if isinstance(self._raw, _ext.PropertyCounterexample) else None
        if pce is None:
            return None
        raw_beh = pce.behaviour()
        return Behaviour(raw_beh, self._session) if raw_beh else None

    def debug_context(self, elide_uninteresting: bool = True) -> DebugContext:
        raw_dc = _ext.DebugContext(self._raw, elide_uninteresting)
        return DebugContext(raw_dc, self._session)

# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------

class FdrAssertion:
    def __init__(self, raw: "_ext.Assertion", session: "Session"):
        self._raw = raw
        self._session = session

    def execute(self):
        self._raw.execute()

    def passed(self) -> bool:
        return self._raw.passed()

    def to_string(self) -> str:
        return self._raw.to_string()

    def counterexamples(self) -> list[FdrCounterexample]:
        return [FdrCounterexample(ce, self._session) for ce in self._raw.counterexamples()]

# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class Session:
    def __init__(self):
        self._raw = _ext.Session()

    def load(self, path: str) -> list[str]:
        return self._raw.load_file(path)

    def assertions(self) -> list[FdrAssertion]:
        return [FdrAssertion(a, self) for a in self._raw.assertions()]

    def uncompile_event(self, event_id: int) -> str:
        return self._raw.uncompile_event(event_id)

    def uncompile_events(self, event_ids: list[int]) -> list[str]:
        return self._raw.uncompile_events(event_ids)
