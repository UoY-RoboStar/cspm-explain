"""Explain FDR deadlock counter-examples — rule-based and (optionally) Claude-based."""
from __future__ import annotations

import anthropic

from .model import AssertionResult, Behaviour, Counterexample, FdrOutput
from .cspm_parser import parallel_operand_labels, sequential_tail

# FDR uses event ID 0 to mark steps where one branch of a parallel composition
# performed an event that the current sub-machine did not participate in.
_INTERLEAVE_EVENT = 0

# FDR event ID 1 is the internal τ (tau) event.
_TAU_EVENT = 1

# FDR uses ✓ (U+2713) for the CSP termination (tick) event.
_TICK = "✓"


def _event_name(eid: int, event_map: dict[str, str]) -> str | None:
    """Return the name for *eid*, or None if it is an interleave placeholder."""
    if eid == _INTERLEAVE_EVENT:
        return None
    return event_map.get(str(eid), str(eid))


def _display_event(
    step: int,
    raw_eid: int,
    event_map: dict[str, str],
    revealed_trace: list[str | None] | None,
) -> str:
    """Human-readable event label for *step*, using revealed_trace when available.

    For τ steps whose hidden event is known, returns 'hidden(<event>)'.
    For other τ (non-determinism), returns 'τ'.
    For normal events, returns the event name.
    """
    if raw_eid == _TAU_EVENT and revealed_trace and step < len(revealed_trace):
        name = revealed_trace[step]  # already a string name, or None
        if name is not None:
            return f"hidden('{name}')"
        return "τ"
    name = event_map.get(str(raw_eid), str(raw_eid))
    return name


def _translate_trace(
    trace: list[int],
    event_map: dict[str, str],
    revealed_trace: list[int] | None = None,
) -> list[str]:
    """Return only the visible (non-interleave) events in *trace*, by name.

    When *revealed_trace* is provided, τ events are replaced by their actual
    hidden-event names so the trace reads as a sequence of meaningful events.
    """
    result = []
    for i, eid in enumerate(trace):
        if eid == _INTERLEAVE_EVENT:
            continue
        result.append(_display_event(i, eid, event_map, revealed_trace))
    return result


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
    """Last effective state of a leaf behaviour.

    Skips <unchanged> placeholders; if every state is <unchanged> (the
    leaf was dormant throughout) returns '<unnamed>' so callers can fall
    back to the acceptance-set description.
    """
    for s in reversed(b.states or []):
        if s != "<unchanged>":
            return s
    return "<unnamed>"


def _collect_leaves(b: Behaviour) -> list[Behaviour]:
    """Return all leaf (atomic) behaviours in the tree, depth-first."""
    if not b.child_behaviours:
        return [b]
    leaves: list[Behaviour] = []
    for child in b.child_behaviours:
        leaves.extend(_collect_leaves(child))
    return leaves


def _build_display_names(
    root: Behaviour,
    operand_labels: dict[str, list[str]] | None = None,
) -> dict[int, str]:
    """Map each leaf's id() to a human-readable display name.

    Named leaves use their own machine_name.
    Anonymous leaves are labelled using ``operand_labels`` when available:
    the parser-derived source text for the corresponding parallel operand.
    Falls back to '(sub-process of <ancestor>)' when the source text is not
    available, or '(anonymous)' when there is no named ancestor at all.

    ``operand_labels`` maps process_name → [label_left, label_right] and is
    produced by ``cspm_parser.parallel_operand_labels``.

    The child index is tracked so that the Nth anonymous child of a named
    process N is matched to operand_labels[N][child_index].
    """
    result: dict[int, str] = {}
    ops = operand_labels or {}

    def walk(b: Behaviour, named_ancestor: str | None, child_index: int) -> None:
        own = b.machine_name
        is_anon = own == "(anonymous)"
        if is_anon and named_ancestor:
            ancestor_ops = ops.get(named_ancestor, [])
            if child_index < len(ancestor_ops):
                # Named ancestor is a parallel composition — use source-text operand label.
                leaf_label = f"{ancestor_ops[child_index]} (in {named_ancestor})"
            elif ancestor_ops:
                # Parallel composition but more anonymous children than operands (shouldn't happen).
                leaf_label = f"(sub-process of {named_ancestor})"
            else:
                # Named ancestor is not a parallel composition (e.g. sequential, hiding).
                # FDR decomposes it internally; the anonymous child IS the ancestor.
                leaf_label = named_ancestor
        else:
            leaf_label = own
        # Anonymous nodes keep the current ancestor; named nodes become the new ancestor.
        child_ancestor = named_ancestor if is_anon else own
        if not b.child_behaviours:
            result[id(b)] = leaf_label
        for idx, child in enumerate(b.child_behaviours):
            walk(child, child_ancestor, idx)

    walk(root, named_ancestor=None, child_index=0)
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


def _terminated_via_tick(leaf: Behaviour, event_map: dict[str, str]) -> bool:
    """True if this leaf performed the ✓ termination event at any step."""
    return any(
        eid != _INTERLEAVE_EVENT and event_map.get(str(eid)) == _TICK
        for eid in leaf.trace
    )


def _initial_label(leaf: Behaviour, event_map: dict[str, str]) -> str:
    """Display label for a leaf's initial state (states[0])."""
    initial = (leaf.states or ["?"])[0]
    # Both <unnamed> and <unchanged> as the initial state mean FDR has no
    # concrete name for it; use look-ahead (step=-1 scans from index 0).
    if initial in ("<unnamed>", "<unchanged>"):
        return _unnamed_label(leaf, -1, event_map)
    return repr(initial)


def _narrate_trace(
    system_b: Behaviour,
    leaves: list[Behaviour],
    display_names: dict[int, str],
    event_map: dict[str, str],
    seq_chains: dict[str, tuple[int, str]] | None = None,
) -> tuple[list[str], dict[int, str]]:
    """Return (narration_lines, final_process_names) for a step-by-step trace.

    final_process_names maps id(leaf) → the semantic process name that leaf
    was acting as at the end of the trace.  Callers use this to show correct
    names in the "State at deadlock" and "Root cause" sections.

    seq_chains: optional {process_name: (prefix_event_count, continuation)} from the
    CSP-M parser, used to track Mrk → Yuxjyk → IRGXg style sequential chains.
    """
    lines: list[str] = []
    chains = seq_chains or {}

    # Build threshold tables for sequential-chain leaves.
    anchor_thresholds: dict[str, list[tuple[int, str | None]]] = {}
    anchor_counts: dict[str, int] = {}
    leaf_anchor: dict[int, str | None] = {}

    for leaf in leaves:
        lbl = display_names.get(id(leaf), leaf.machine_name)
        if " (in " in lbl or lbl not in chains:
            leaf_anchor[id(leaf)] = None
            continue
        anchor = lbl
        leaf_anchor[id(leaf)] = anchor
        if anchor not in anchor_thresholds:
            thresholds: list[tuple[int, str | None]] = []
            cur, cumul = anchor, 0
            visited: set[str] = {anchor}
            while cur in chains:
                cnt, nxt = chains[cur]
                cumul += cnt
                thresholds.append((cumul, nxt))
                if nxt is None or nxt in visited:
                    break
                visited.add(nxt)
                cur = nxt
            anchor_thresholds[anchor] = thresholds
            anchor_counts[anchor] = 0

    def _sem_name(anchor: str, count: int) -> str:
        name = anchor
        for threshold, nxt in anchor_thresholds.get(anchor, []):
            if count >= threshold and nxt is not None:
                name = nxt
            else:
                break
        return name

    # per_leaf_sem tracks each leaf's current semantic process name.
    # Updated as events are consumed and as FDR transitions to named states.
    per_leaf_sem: dict[int, str] = {
        id(leaf): display_names.get(id(leaf), leaf.machine_name) for leaf in leaves
    }

    def dn(leaf: Behaviour) -> str:
        # Chain leaves: use the shared anchor counter so bystander transitions
        # and headers reflect the chain's current position even before a leaf
        # has had its first active step.
        anchor = leaf_anchor.get(id(leaf))
        if anchor is not None:
            return _sem_name(anchor, anchor_counts[anchor])
        # Non-chain leaves: use per_leaf_sem which tracks FDR named-state transitions.
        return per_leaf_sem.get(id(leaf), display_names.get(id(leaf), leaf.machine_name))

    current_label: dict[int, str] = {
        id(leaf): _initial_label(leaf, event_map) for leaf in leaves
    }

    for step, sys_eid in enumerate(system_b.trace):
        sys_event = _display_event(step, sys_eid, event_map, system_b.revealed_trace)

        participants = [leaf for leaf in leaves
                        if step < len(leaf.trace) and leaf.trace[step] != _INTERLEAVE_EVENT]

        if len(participants) == 1:
            how = f"{dn(participants[0])} acts alone"
        elif participants:
            how = " and ".join(dn(leaf) for leaf in participants) + " synchronise"
        else:
            how = "all bystanders"

        lines.append(f"  Step {step + 1}: '{sys_event}'  ({how})")

        for leaf in leaves:
            states = leaf.states or []
            leaf_participated = step < len(leaf.trace) and leaf.trace[step] != _INTERLEAVE_EVENT

            # Advance the sequential-chain counter for ALL active events — including
            # steps where the leaf participates but its FDR state doesn't change
            # (<unchanged>).  Skipping those steps causes an off-by-one in the
            # threshold crossing and makes the label update one event too late.
            threshold_crossed: str | None = None
            anchor = leaf_anchor.get(id(leaf))
            sem_prefix = dn(leaf)           # name BEFORE this step's update
            if anchor is not None and leaf_participated:
                sem_before = _sem_name(anchor, anchor_counts[anchor])
                anchor_counts[anchor] += 1
                sem_after  = _sem_name(anchor, anchor_counts[anchor])
                per_leaf_sem[id(leaf)] = sem_after
                if sem_after != sem_before:
                    threshold_crossed = sem_after

            if step + 1 >= len(states):
                continue
            after = states[step + 1]
            if after == "<unchanged>":
                continue

            before_label = current_label[id(leaf)]

            if after == "<unnamed>" and threshold_crossed is not None:
                after_label = repr(threshold_crossed)
            elif after == "<unnamed>":
                after_label = _unnamed_label(leaf, step, event_map)
            elif after == "STOP" and sys_event == _TICK and leaf_participated:
                after_label = "(terminated)"
            else:
                after_label = repr(after)
                # For non-chain leaves, track FDR named-state transitions so the
                # header ("X acts alone") reflects the current process name.
                if anchor is None and after not in ("STOP", "SKIP"):
                    per_leaf_sem[id(leaf)] = after

            lines.append(f"           {sem_prefix}: {before_label} → {after_label}")
            current_label[id(leaf)] = after_label

    return lines, per_leaf_sem


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
    csp_source: str | None = None,
) -> str:
    """Produce a structured, rule-based explanation of a deadlock counter-example.

    If *csp_source* is provided the CSP-M source is parsed so that anonymous
    parallel sub-processes can be labelled with their actual source text rather
    than the generic '(sub-process of X)'.
    """
    b            = ce.implementation_behaviour
    leaves       = _collect_leaves(b)

    ops: dict[str, list[str]] | None = None
    chains: dict[str, tuple[int, str]] | None = None
    if csp_source:
        try:
            ops = parallel_operand_labels(csp_source)
            chains = sequential_tail(csp_source)
        except Exception:
            pass  # parsing failure is non-fatal; fall back to generic labels

    display_names = _build_display_names(b, ops)
    paras: list[str] = []

    # final_proc_names is populated by _narrate_trace; dn() uses it so that
    # "State at deadlock" and "Root cause" sections show semantic process names
    # (e.g. Yuxjyk, IRGXg) rather than the static tree-level labels (Mrk × 4).
    final_proc_names: dict[int, str] = {}

    def dn(leaf: Behaviour) -> str:
        return final_proc_names.get(id(leaf), display_names.get(id(leaf), leaf.machine_name))

    # ── 1. Trace narrative ──────────────────────────────────────────────────
    # Use revealed_trace so τ steps are shown as their actual hidden event.
    visible = _translate_trace(b.trace, event_map, b.revealed_trace)

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
        trace_lines, fp = _narrate_trace(b, leaves, display_names, event_map, chains)
        final_proc_names.update(fp)
        paras.extend(trace_lines)

    # ── 2. State at deadlock ────────────────────────────────────────────────
    paras.append("")
    paras.append("State at the point of deadlock:")
    for c in leaves:
        accepted = [event_map.get(str(e), str(e)) for e in c.acceptance]
        final = _final_state(c)
        if final == "STOP" and not accepted and _terminated_via_tick(c, event_map):
            # Process reached STOP by performing ✓ — it terminated normally.
            paras.append(f"  • {dn(c)}: terminated normally")
        elif final == "<unnamed>":
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

    stopped     = [c for c in leaves if not c.acceptance]
    waiting     = [c for c in leaves if     c.acceptance]
    terminated  = [c for c in stopped if _terminated_via_tick(c, event_map)]
    stuck       = [c for c in stopped if c not in terminated]

    if not waiting:
        # ── Case A: every component is in STOP ───────────────────────────────
        if terminated and not stuck:
            if len(leaves) == 1:
                name = dn(terminated[0])
                paras.append(
                    f"  {name} terminates normally (performed ✓), after which no further "
                    "events are available. FDR's deadlock-free check requires a process "
                    "to be able to make progress indefinitely; a process that "
                    "successfully terminates is still flagged. If the process is "
                    "intended to repeat, redefine it to loop back to its initial state."
                )
            else:
                names_str = ", ".join(dn(c) for c in terminated)
                paras.append(
                    f"  Every component ({names_str}) has terminated normally (performed ✓). "
                    "The parallel composition has no further events to synchronise on, "
                    "so the system is stuck."
                )
                paras.append("")
                paras.append(
                    "  If the components are intended to run repeatedly, redefine them "
                    "to loop back to their initial state, or sequence them further "
                    "using sequential composition (;)."
                )
        else:
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
        # ── Case C: some done/stuck, others still waiting ────────────────────
        def _stop_desc(c: Behaviour) -> str:
            return "terminated" if c in terminated else "reached STOP"

        waiting_names = ", ".join(dn(c) for c in waiting)

        # Describe each non-waiting component individually.
        for c in stopped:
            verb = "has" if True else "have"   # always singular here
            paras.append(
                f"  {dn(c)} {_stop_desc(c)}, while "
                f"{waiting_names} {'is' if len(waiting) == 1 else 'are'} still "
                "waiting to perform events:"
            )
            break   # opening sentence covers all stopped; rest listed below
        for c in waiting:
            events = ", ".join(f"'{event_map.get(str(e),str(e))}'" for e in c.acceptance)
            paras.append(f"    – {dn(c)} wants to perform {events}.")
        if len(stopped) > 1:
            extras = ", ".join(
                f"{dn(c)} ({_stop_desc(c)})" for c in stopped[1:]
            )
            paras.append(f"  Also: {extras}.")

        paras.append("")
        stopped_names = ", ".join(dn(c) for c in stopped)
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
