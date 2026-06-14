"""Adapter that runs FDR via the pybind11 C++ API and produces the same
FdrOutput model that the CLI JSON path produces.

Key improvements over the CLI path:
  - Machine names are always correct (Session::machine_name, not JSON injection).
  - τ events are attributed to their actual hidden events via
    DebugContext::reveal_taus_in_trace(), stored in Behaviour.revealed_trace.
  - The acceptance of each leaf behaviour comes from MinAcceptanceBehaviour.
  - States come from machine_node_name() on each node in the behaviour's path.
"""
from __future__ import annotations

from .model import AssertionResult, Behaviour, Counterexample, FdrOutput
from .fdr_py import DebugContext, FdrAssertion, FdrCounterexample, Session, TAU, INVALID_EVENT


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def _build_event_map(session: Session, dc: DebugContext) -> dict[str, str]:
    """Build compiled_event_id -> name for all events in the debug tree."""
    ev_map: dict[str, str] = {}
    for ev_id in dc.full_alphabet():
        if ev_id in (INVALID_EVENT, TAU):
            continue
        name = session.uncompile_event(ev_id)
        if name:
            ev_map[str(ev_id)] = name
    return ev_map


def _build_revealed(
    raw_trace: list[int],
    rev: list[int],
    session: Session,
) -> list[str | None] | None:
    """Build the revealed_trace as a list of string names (or None).

    Returns None if no τ position has a non-τ revealed event (nothing to show).
    Otherwise returns a parallel list: for each trace position, the hidden event
    name if that τ was produced by a hiding operator, else None.
    """
    any_resolved = False
    result: list[str | None] = []
    for t, r in zip(raw_trace, rev):
        if t == TAU and r != TAU:
            name = session.uncompile_event(r) or str(r)
            result.append(name)
            any_resolved = True
        else:
            result.append(None)
    return result if any_resolved else None


def _build_behaviour(
    beh: "fdr_py.Behaviour",  # noqa: F821
    dc: DebugContext,
    session: Session,
) -> Behaviour:
    """Recursively build a model.Behaviour from a C++ API Behaviour."""
    machine_name = beh.machine_name()
    raw_trace    = beh.trace()
    states_list  = beh.states()          # uses machine_node_name()
    acceptance   = beh.min_acceptance()  # [] if not MinAcceptanceBehaviour

    # Resolve τ events to string names now, while this session's mapping is correct.
    rev = dc.reveal_taus_in_trace(beh)
    revealed = _build_revealed(raw_trace, rev, session)

    # Recurse into children produced by --divide decomposition.
    children = [
        _build_behaviour(child, dc, session)
        for child in dc.children(beh)
    ]

    return Behaviour(
        machine_name=machine_name,
        type="min_acceptance",
        acceptance=acceptance,
        trace=raw_trace,
        states=states_list,
        child_behaviours=children,
        revealed_trace=revealed,
    )


def _run_one_assertion(
    assertion: FdrAssertion,
    session: Session,
) -> tuple[AssertionResult, dict[str, str]]:
    """Execute one assertion and return its model result plus a partial event_map."""
    assertion.execute()
    label   = assertion.to_string()
    passed  = assertion.passed()

    counterexamples: list[Counterexample] = []
    ev_map: dict[str, str] = {}

    if not passed:
        for ce in assertion.counterexamples():
            if not ce.is_property():
                continue
            root_beh = ce.behaviour()
            if root_beh is None:
                continue

            dc = ce.debug_context(elide_uninteresting=True)
            dc.initialise()

            # Merge event map from this debug context's full alphabet.
            ev_map.update(_build_event_map(session, dc))

            # Use the root behaviour from the DebugContext (same as the CE
            # behaviour, but already registered with the DebugContext so that
            # reveal_taus_in_trace and behaviour_children work correctly).
            dc_roots = dc.root_behaviours()
            model_beh = _build_behaviour(
                dc_roots[0] if dc_roots else root_beh,
                dc,
                session,
            )

            counterexamples.append(Counterexample(
                type="deadlock",
                implementation_behaviour=model_beh,
            ))

    result = AssertionResult(
        assertion_string=label,
        result=1 if passed else 0,
        visited_states=0,
        visited_transitions=0,
        visited_plys=0,
        counterexamples=counterexamples,
        errors=[],
    )
    return result, ev_map


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_fdr_api(csp_file: str) -> tuple[FdrOutput, str]:
    """Load *csp_file* via the FDR C++ API and return (FdrOutput, stderr).

    Each assertion is executed in its own fresh Session so that FDR compiles
    machines without reusing state from previous assertions.  This is necessary
    to preserve τ events in counterexample traces: with a shared session FDR's
    machine-reuse optimisation can produce shorter counterexample paths that
    omit hidden τ transitions, causing reveal_taus_in_trace() to find nothing
    to reveal.  A fresh session per assertion avoids this at the cost of one
    extra file-load per assertion.
    """
    # First pass: load once to discover assertion labels and warnings.
    catalog = Session()
    warnings = catalog.load(csp_file)
    labels = [a.to_string() for a in catalog.assertions()]
    del catalog  # free the shared session before spawning per-assertion ones

    results: list[AssertionResult] = []
    combined_ev_map: dict[str, str] = {}

    for label in labels:
        session = Session()
        session.load(csp_file)
        for a in session.assertions():
            if a.to_string() != label:
                continue
            ar, ev_map = _run_one_assertion(a, session)
            results.append(ar)
            combined_ev_map.update(ev_map)
            break

    return FdrOutput(
        results=results,
        event_map=combined_ev_map,
        file_name=csp_file,
        errors=[],
        warnings=warnings,
    ), ""
