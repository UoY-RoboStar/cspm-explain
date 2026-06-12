"""Explain FDR deadlock counter-examples — rule-based and (optionally) Claude-based."""
from __future__ import annotations

import anthropic

from .model import AssertionResult, Behaviour, Counterexample, FdrOutput

# FDR uses event ID 0 to mark steps where one branch of a parallel composition
# performed an event that the current sub-machine did not participate in.
_INTERLEAVE_EVENT = 0


def _event_name(eid: int, event_map: dict[str, str]) -> str | None:
    """Return the name for *eid*, or None if it is an interleave placeholder."""
    if eid == _INTERLEAVE_EVENT:
        return None
    return event_map.get(str(eid), str(eid))


def _translate_trace(trace: list[int], event_map: dict[str, str]) -> list[str]:
    """Return only the visible (non-interleave) events in *trace*, by name."""
    return [n for eid in trace if (n := _event_name(eid, event_map)) is not None]


def _local_trace_with_markers(trace: list[int], event_map: dict[str, str]) -> list[str]:
    """Return every step in *trace* by name, replacing interleave events with a marker."""
    result = []
    for eid in trace:
        name = _event_name(eid, event_map)
        result.append(name if name is not None else "[other-component-moved]")
    return result


def _format_behaviour(b: Behaviour, event_map: dict[str, str], depth: int = 0) -> str:
    """Recursively render *b* as an indented, human-readable block."""
    pad = "  " * depth
    lines: list[str] = []

    accepted = [event_map.get(str(e), str(e)) for e in b.acceptance]
    accepted_str = ", ".join(accepted) if accepted else "(nothing — deadlocked / STOP)"

    if b.child_behaviours:
        # Composite machine — show the visible system-level trace.
        visible = _translate_trace(b.trace, event_map)
        trace_str = " -> ".join(visible) if visible else "(none — immediate deadlock)"
        lines.append(f"{pad}Composed process : {b.machine_name}")
        lines.append(f"{pad}  Trace to deadlock : {trace_str}")
        lines.append(f"{pad}  Composed acceptance: {accepted_str}")
        lines.append(f"{pad}  Component sub-behaviours:")
        for child in b.child_behaviours:
            lines.append(_format_behaviour(child, event_map, depth + 2))
    else:
        # Leaf (atomic) machine — show per-step state progression.
        local = _local_trace_with_markers(b.trace, event_map)
        states = b.states or []

        # Build a compact state-progression string.
        progression_parts: list[str] = []
        if states:
            progression_parts.append(f"initially {states[0]!r}")
        for i, step in enumerate(local):
            after = states[i + 1] if i + 1 < len(states) else "?"
            if after not in ("<unchanged>", "<unnamed>"):
                progression_parts.append(f"after {step!r} -> {after!r}")
            else:
                progression_parts.append(f"after {step!r} -> {after}")

        final = next(
            (s for s in reversed(states) if s not in ("<unchanged>", "<unnamed>")),
            states[-1] if states else "unknown",
        )

        lines.append(f"{pad}Component process : {b.machine_name}")
        lines.append(f"{pad}  Local trace       : {' -> '.join(local) if local else '(none)'}")
        lines.append(f"{pad}  State progression : {'; '.join(progression_parts)}")
        lines.append(f"{pad}  Final state       : {final!r}")
        lines.append(f"{pad}  Ready to accept   : {accepted_str}")

    return "\n".join(lines)


def _build_prompt(
    csp_source: str,
    assertion: AssertionResult,
    ce: Counterexample,
    event_map: dict[str, str],
) -> str:
    behaviour_text = _format_behaviour(ce.implementation_behaviour, event_map)

    return f"""\
You are an expert in the CSP process algebra and the FDR model checker.

An FDR check has found a deadlock counter-example. Your task is to explain clearly \
WHY the deadlock occurs, using only the evidence below.

## CSP specification
```
{csp_source}
```

## Failed assertion
`{assertion.assertion_string}`

## Counter-example (produced by FDR --divide)
{behaviour_text}

## Notes on the counter-example format
- "Trace to deadlock" is the sequence of visible events that leads the composed system \
to the deadlocked state.
- Each component shows its local trace (where "[other-component-moved]" marks a step \
in which the parallel partner performed an event that this component did not participate in).
- "Ready to accept" lists the events each component is willing to perform from the \
deadlocked state (empty means the component is in STOP or equivalent).
- The system deadlocks because none of the accepted events can actually occur in the \
composed context.

## Your response
Please explain:
1. The sequence of events that leads to the deadlock (narrate the trace).
2. The state each component is in when the deadlock is reached.
3. The root cause: why can no further events occur? Which components are waiting for \
what, and why those events are unavailable.
4. A concise suggestion for how the specification could be corrected, if one is apparent.

Be precise and concise. Use CSP terminology where helpful.\
"""


# ---------------------------------------------------------------------------
# Rule-based explainer (no LLM required)
# ---------------------------------------------------------------------------

def _final_state(b: Behaviour) -> str:
    """Last effective state of a leaf behaviour, accounting for <unchanged> steps.

    Returns <unnamed> as-is so callers can render it descriptively.
    """
    for s in reversed(b.states or []):
        if s != "<unchanged>":
            return s
    return (b.states or ["unknown"])[-1]


def _collect_leaves(b: Behaviour) -> list[Behaviour]:
    """Return all leaf (atomic) behaviours in the tree, depth-first."""
    if not b.child_behaviours:
        return [b]
    leaves: list[Behaviour] = []
    for child in b.child_behaviours:
        leaves.extend(_collect_leaves(child))
    return leaves


def _build_display_names(root: Behaviour) -> dict[int, str]:
    """Map each leaf's id() to a human-readable display name.

    Named leaves use their own machine_name.
    Anonymous leaves are attributed to the nearest named ancestor:
    '(sub-process of <ancestor>)'.  If there is no named ancestor, they
    are labelled '(anonymous)'.
    """
    result: dict[int, str] = {}

    def walk(b: Behaviour, named_ancestor: str | None) -> None:
        own = b.machine_name
        is_anon = own == "(anonymous)"
        # The label this node would receive if it were a leaf
        leaf_label = f"(sub-process of {named_ancestor})" if is_anon and named_ancestor else own
        # Ancestor name passed to children; anonymous nodes keep the current ancestor
        child_ancestor = named_ancestor if is_anon else own
        if not b.child_behaviours:
            result[id(b)] = leaf_label
        for child in b.child_behaviours:
            walk(child, child_ancestor)

    walk(root, named_ancestor=None)
    return result


def _next_visible_event(leaf: Behaviour, after_step: int, event_map: dict[str, str]) -> str | None:
    """Return the name of the next visible event leaf performs after after_step."""
    for j in range(after_step + 1, len(leaf.trace)):
        eid = leaf.trace[j]
        if eid != _INTERLEAVE_EVENT:
            return event_map.get(str(eid), str(eid))
    return None


def _unnamed_label(leaf: Behaviour, step: int, event_map: dict[str, str]) -> str:
    """Descriptive label for an <unnamed> state.

    Looks ahead in the leaf's trace for the next visible event it will perform.
    Falls back to the acceptance set when this is already the deadlock frontier.
    """
    next_ev = _next_visible_event(leaf, step, event_map)
    if next_ev is not None:
        return f"(ready to perform '{next_ev}')"
    accepted = [event_map.get(str(e), str(e)) for e in leaf.acceptance]
    if accepted:
        return f"(ready to perform {', '.join(repr(e) for e in accepted)})"
    return "(done)"


def _initial_label(leaf: Behaviour, event_map: dict[str, str]) -> str:
    """Display label for a leaf's initial state (states[0])."""
    initial = (leaf.states or ["?"])[0]
    # <unnamed> initial state — use look-ahead (step=-1 means scan from index 0)
    if initial == "<unnamed>":
        return _unnamed_label(leaf, -1, event_map)
    return repr(initial)


def _narrate_trace(
    system_b: Behaviour,
    leaves: list[Behaviour],
    display_names: dict[int, str],
    event_map: dict[str, str],
) -> list[str]:
    """Return a step-by-step narration using leaf processes.

    FDR guarantees that every behaviour's trace is globally indexed: leaf.trace[i]
    is non-INTERLEAVE iff that leaf participated at system-level step i.

    We track each leaf's DISPLAY LABEL (not the raw state string) so that
    <unnamed> states show a meaningful "ready to perform 'X'" description
    and <unchanged> placeholders are never surfaced to the user.

    Keyed by id(leaf) so multiple anonymous leaves don't collide.
    """
    lines: list[str] = []
    current_label: dict[int, str] = {
        id(leaf): _initial_label(leaf, event_map) for leaf in leaves
    }

    def dn(leaf: Behaviour) -> str:
        return display_names.get(id(leaf), leaf.machine_name)

    for step, sys_eid in enumerate(system_b.trace):
        sys_event = event_map.get(str(sys_eid), str(sys_eid))

        participants = [leaf for leaf in leaves
                        if step < len(leaf.trace) and leaf.trace[step] != _INTERLEAVE_EVENT]

        if len(participants) == 1:
            how = f"{dn(participants[0])} acts alone"
        elif participants:
            how = " and ".join(dn(leaf) for leaf in participants) + " synchronise"
        else:
            how = "all bystanders"  # shouldn't happen in practice

        lines.append(f"  Step {step + 1}: '{sys_event}'  ({how})")

        for leaf in leaves:
            states = leaf.states or []
            if step + 1 >= len(states):
                continue
            after = states[step + 1]
            if after == "<unchanged>":
                continue
            before_label = current_label[id(leaf)]
            after_label = _unnamed_label(leaf, step, event_map) if after == "<unnamed>" else repr(after)
            lines.append(f"           {dn(leaf)}: {before_label} → {after_label}")
            current_label[id(leaf)] = after_label

    return lines


def _acceptance_map(
    children: list[Behaviour],
    display_names: dict[int, str],
    event_map: dict[str, str],
) -> dict[str, list[str]]:
    """Map each accepted event name to the list of processes offering it."""
    out: dict[str, list[str]] = {}
    for c in children:
        label = display_names.get(id(c), c.machine_name)
        for eid in c.acceptance:
            name = event_map.get(str(eid), str(eid))
            out.setdefault(name, []).append(label)
    return out


def explain_deadlock(
    assertion: AssertionResult,
    ce: Counterexample,
    event_map: dict[str, str],
) -> str:
    """Produce a structured, rule-based explanation of a deadlock counter-example."""
    b            = ce.implementation_behaviour
    leaves       = _collect_leaves(b)
    display_names = _build_display_names(b)
    paras: list[str] = []

    def dn(leaf: Behaviour) -> str:
        return display_names.get(id(leaf), leaf.machine_name)

    # ── 1. Trace narrative ──────────────────────────────────────────────────
    visible = _translate_trace(b.trace, event_map)

    if not visible:
        paras.append(
            "The system deadlocks immediately — no events need to occur before "
            "the system becomes stuck."
        )
    else:
        trace_str = " → ".join(f"'{e}'" for e in visible)
        paras.append(f"The system reaches a deadlock after the trace: {trace_str}.")
        paras.append("")
        paras.append("How the trace unfolds:")
        paras.extend(_narrate_trace(b, leaves, display_names, event_map))

    # ── 2. State at deadlock ────────────────────────────────────────────────
    paras.append("")
    paras.append("State at the point of deadlock:")
    for c in leaves:
        accepted = [event_map.get(str(e), str(e)) for e in c.acceptance]
        final = _final_state(c)
        if final == "<unnamed>":
            # Process is in an intermediate unnamed state; describe by what it wants to do.
            if accepted:
                acc_str = ", ".join(f"'{e}'" for e in accepted)
                paras.append(f"  • {dn(c)}: ready to perform: {acc_str}")
            else:
                paras.append(f"  • {dn(c)}: no events available")
        elif accepted:
            acc_str = ", ".join(f"'{e}'" for e in accepted)
            paras.append(f"  • {dn(c)}: in {repr(final)}, ready to perform: {acc_str}")
        else:
            paras.append(f"  • {dn(c)}: in {repr(final)}, no events available")

    # ── 3. Root-cause analysis ──────────────────────────────────────────────
    paras.append("")
    paras.append("Root cause:")

    stopped = [c for c in leaves if not c.acceptance]
    waiting = [c for c in leaves if     c.acceptance]

    if not waiting:
        # ── Case A: every component is in STOP (termination deadlock) ───────
        names_str = ", ".join(dn(c) for c in stopped)
        paras.append(
            f"  Every component ({names_str}) has reached a state with no outgoing "
            "events (STOP or equivalent). The composition is permanently stuck "
            "because there is nothing left for any process to do."
        )
        paras.append("")
        paras.append(
            "  This is a termination deadlock. If the processes are intended to "
            "terminate, replace STOP with SKIP and use sequential composition (;) "
            "or redefine components to loop back to their initial state."
        )

    elif not stopped:
        # ── Case B: all components are waiting — classify the conflict ───────
        acc_map = _acceptance_map(waiting, display_names, event_map)
        shared = {e: ps for e, ps in acc_map.items() if len(ps) > 1}
        solo   = {e: ps[0] for e, ps in acc_map.items() if len(ps) == 1}

        paras.append(
            "  All components are waiting for events that cannot occur in the "
            "current state of the composition:"
        )
        for c in waiting:
            events = ", ".join(f"'{event_map.get(str(e),str(e))}'" for e in c.acceptance)
            paras.append(f"    – {dn(c)} is ready to perform {events}.")

        paras.append("")

        if solo and not shared:
            # Classic mismatched-first-event deadlock
            paras.append(
                "  No two components are offering the same event. Because all "
                "events in the synchronisation alphabet must be agreed on jointly, "
                "and the processes' ready-sets are disjoint, no event can be "
                "selected and the system is stuck."
            )
            for event, proc in solo.items():
                other_wants = []
                for c in waiting:
                    if dn(c) != proc:
                        w = [event_map.get(str(e), str(e)) for e in c.acceptance]
                        other_wants.append(f"{dn(c)} (offering {', '.join(repr(x) for x in w)})")
                paras.append(
                    f"    – '{event}' is only offered by {proc}, "
                    f"not by {'; '.join(other_wants)}."
                )
        elif shared:
            shared_str = ", ".join(f"'{e}'" for e in shared)
            paras.append(
                f"  Events {shared_str} are offered by multiple components "
                "simultaneously but still cannot proceed. This can happen when a "
                "required third participant is absent, or when a renaming or hiding "
                "operator is preventing the event from being visible to the "
                "synchronisation set."
            )
        else:
            # Mix of solo and shared — report both
            for event, proc in solo.items():
                paras.append(f"    – '{event}' is only offered by {proc}; no partner offers it.")
            for event, procs in shared.items():
                names_str = " and ".join(procs)
                paras.append(
                    f"    – '{event}' is offered by {names_str} but is still blocked "
                    "(possible missing third-party synchronisation)."
                )

    else:
        # ── Case C: some in STOP, others still waiting ───────────────────────
        stopped_names = ", ".join(dn(c) for c in stopped)
        waiting_names = ", ".join(dn(c) for c in waiting)
        paras.append(
            f"  {stopped_names} {'has' if len(stopped) == 1 else 'have'} reached "
            "a state with no outgoing events (STOP), while "
            f"{waiting_names} {'is' if len(waiting) == 1 else 'are'} still "
            "waiting to perform events:"
        )
        for c in waiting:
            events = ", ".join(f"'{event_map.get(str(e),str(e))}'" for e in c.acceptance)
            paras.append(f"    – {dn(c)} wants to perform {events}.")

        paras.append("")
        paras.append(
            f"  The deadlock arises because "
            f"{stopped_names} can no longer offer any events, so "
            f"{'any event' if len(waiting) == 1 else 'the events'} that "
            f"{waiting_names} need{'s' if len(waiting) == 1 else ''} from "
            f"{'it' if len(stopped) == 1 else 'them'} as synchronisation "
            "partners will never be available."
        )

    return "\n".join(paras)


def explain_fdr_output(
    fdr_output: FdrOutput,
    csp_source: str,
    client: anthropic.Anthropic,
    model: str = "claude-sonnet-4-6",
) -> None:
    """Print Claude-generated explanations for every failed deadlock assertion."""
    failed = [r for r in fdr_output.results if r.result == 0 and r.counterexamples]

    if not failed:
        print("All assertions passed — no deadlocks found.")
        return

    for assertion in failed:
        for idx, ce in enumerate(assertion.counterexamples, start=1):
            print(f"\n{'=' * 70}")
            print(f"ASSERTION FAILED: {assertion.assertion_string}")
            if len(assertion.counterexamples) > 1:
                print(f"Counter-example {idx} of {len(assertion.counterexamples)}")
            print("=" * 70)

            if ce.type != "deadlock":
                print(
                    f"  (counter-example type is {ce.type!r}; "
                    "only 'deadlock' explanations are currently supported)"
                )
                continue

            print("\nQuerying Claude for an explanation...\n")
            prompt = _build_prompt(csp_source, assertion, ce, fdr_output.event_map)
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            print(response.content[0].text)
