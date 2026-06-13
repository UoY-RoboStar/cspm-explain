"""Generate a JSON trace replay for interactive step-through tools.

The replay captures, at each trace step, the source position (line/col) of
each component process in the CSP-M file.  A VS Code extension or HTML viewer
can consume this to highlight exactly which event in the original specification
is being fired at every step.

JSON shape
----------
{
  "csp_file": str,           # absolute path to the .csp file
  "assertion": str,          # e.g. "Mrk :[deadlock free]"
  "components": [            # stable leaf ordering
    {"id": int, "name": str},
    ...
  ],
  "steps": [
    {
      "step": int,           # 1-based
      "event": str,
      "highlights": [
        {
          "id": int,         # component id
          "name": str,       # semantic process name at this step
          "role": "participant" | "bystander",
          # present when a source position is known:
          "line": int, "col": int, "end_line": int, "end_col": int,
          "text": str        # source snippet of the highlighted expression
        },
        ...
      ]
    },
    ...
  ],
  "deadlock": [              # state at the end of the trace
    {
      "id": int,
      "name": str,
      "acceptance": [str],   # events the component is ready to perform
      # present when a source position is known:
      "line": int, "col": int, "end_line": int, "end_col": int
    },
    ...
  ]
}
"""
from __future__ import annotations

import os

from .model import AssertionResult, Behaviour, Counterexample
from .explain import _collect_leaves, _build_display_names, _INTERLEAVE_EVENT
from .cspm_parser import (
    all_definition_positions,
    parallel_operand_labels,
    prefix_chain_event_positions,
    sequential_tail,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_anchor_thresholds(
    chains: dict[str, tuple[int, str | None]],
    anchor: str,
) -> list[tuple[int, str | None]]:
    """Build the cumulative threshold list for one sequential-chain anchor.

    Returns [(cumulative_count, next_process_name), ...] in order.
    Self-referencing (recursive) processes are stopped at the self-loop.
    """
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
    return thresholds


def _sem_name(
    anchor: str,
    count: int,
    thresholds: list[tuple[int, str | None]],
) -> str:
    """Semantic process name for *anchor* after *count* total events."""
    name = anchor
    for threshold, nxt in thresholds:
        if count >= threshold and nxt is not None:
            name = nxt
        else:
            break
    return name


def _chain_position(
    anchor: str,
    count: int,
    thresholds: list[tuple[int, str | None]],
) -> tuple[str, int]:
    """Return (process_name, index_within_process) for the given cumulative count.

    For recursive processes the index wraps modulo the process's event count.
    """
    proc = anchor
    base = 0
    for t_count, t_proc in thresholds:
        if count >= t_count and t_proc is not None:
            proc = t_proc
            base = t_count
        else:
            break
    return proc, count - base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_replay(
    assertion: AssertionResult,
    ce: Counterexample,
    event_map: dict[str, str],
    csp_source: str,
    csp_file: str,
) -> dict:
    """Produce the replay dict for one deadlock counter-example.

    The returned value is JSON-serialisable (contains only str/int/list/dict/None).
    """
    b = ce.implementation_behaviour
    leaves = _collect_leaves(b)

    # --- CSP-M source analysis ------------------------------------------------
    ops = None
    chains: dict[str, tuple[int, str | None]] = {}
    event_positions: dict[str, list[dict]] = {}
    def_positions: dict[str, dict] = {}

    try:
        ops = parallel_operand_labels(csp_source)
    except Exception:
        pass
    try:
        chains = sequential_tail(csp_source) or {}  # type: ignore[assignment]
    except Exception:
        pass
    try:
        event_positions = prefix_chain_event_positions(csp_source)
    except Exception:
        pass
    try:
        def_positions = all_definition_positions(csp_source)
    except Exception:
        pass

    display_names = _build_display_names(b, ops)

    # --- Build anchor tables (mirrors _narrate_trace) -------------------------
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
            anchor_thresholds[anchor] = _build_anchor_thresholds(chains, anchor)
            anchor_counts[anchor] = 0

    # --- Per-leaf semantic state -----------------------------------------------
    per_leaf_sem: dict[int, str] = {
        id(leaf): display_names.get(id(leaf), leaf.machine_name) for leaf in leaves
    }

    # --- Source-highlight helpers ----------------------------------------------

    def _chain_highlight(anchor: str, count: int) -> dict | None:
        proc, raw_idx = _chain_position(anchor, count, anchor_thresholds.get(anchor, []))
        positions = event_positions.get(proc, [])
        if not positions:
            return def_positions.get(proc)
        # Wrap around for recursive processes (e.g. P = e1 -> e2 -> P)
        idx = raw_idx % len(positions)
        return positions[idx]

    def _leaf_sem(leaf: Behaviour) -> str:
        anchor = leaf_anchor.get(id(leaf))
        if anchor is not None:
            return _sem_name(anchor, anchor_counts[anchor], anchor_thresholds.get(anchor, []))
        return per_leaf_sem.get(id(leaf), display_names.get(id(leaf), leaf.machine_name))

    def _leaf_highlight(leaf: Behaviour) -> dict | None:
        anchor = leaf_anchor.get(id(leaf))
        if anchor is not None:
            return _chain_highlight(anchor, anchor_counts[anchor])
        proc = per_leaf_sem.get(id(leaf), display_names.get(id(leaf), leaf.machine_name))
        return def_positions.get(proc)

    # --- Stable leaf numbering and dormancy tracking -------------------------
    leaf_index = {id(leaf): i for i, leaf in enumerate(leaves)}

    # last_active[id(leaf)] = the last step index where the leaf participated (-1 if never).
    def _last_active(leaf: Behaviour) -> int:
        return max(
            (j for j in range(len(leaf.trace)) if leaf.trace[j] != _INTERLEAVE_EVENT),
            default=-1,
        )

    leaf_last_active = {id(leaf): _last_active(leaf) for leaf in leaves}

    # A leaf is "dormant" (fully finished) only if it has no remaining trace events
    # AND its acceptance set is empty (it reached STOP, not just waiting at a sync point).
    # Leaves with non-empty acceptance but no more trace events are "bystanders" — they
    # want to act but are blocked by the deadlock.
    leaf_dormant = {
        id(leaf): (len(leaf.acceptance) == 0) for leaf in leaves
    }

    # --- Walk the trace -------------------------------------------------------
    steps: list[dict] = []

    for step, sys_eid in enumerate(b.trace):
        sys_event = event_map.get(str(sys_eid), str(sys_eid))

        participant_ids = {
            id(leaf)
            for leaf in leaves
            if step < len(leaf.trace) and leaf.trace[step] != _INTERLEAVE_EVENT
        }

        # Build per-leaf highlight entries BEFORE advancing state
        highlights: list[dict] = []
        for leaf in leaves:
            if id(leaf) in participant_ids:
                role = "participant"
            elif step > leaf_last_active[id(leaf)] and leaf_dormant[id(leaf)]:
                # Past last active step with empty acceptance: finished in STOP.
                role = "dormant"
            else:
                role = "bystander"
            # Dormant chain leaves omit the stale chain-position highlight (the
            # chain pointer stopped at the boundary process, which is confusing
            # since that process is now being executed by a different leaf).
            if role == "dormant" and leaf_anchor.get(id(leaf)) is not None:
                hl = None
            else:
                hl = _leaf_highlight(leaf)
            entry: dict = {
                "id": leaf_index[id(leaf)],
                "name": _leaf_sem(leaf),
                "role": role,
            }
            if hl:
                entry.update(hl)
            highlights.append(entry)

        steps.append({"step": step + 1, "event": sys_event, "highlights": highlights})

        # Advance state (mirrors _narrate_trace inner loop)
        for leaf in leaves:
            leaf_participated = id(leaf) in participant_ids
            anchor = leaf_anchor.get(id(leaf))

            if anchor is not None and leaf_participated:
                anchor_counts[anchor] += 1
                per_leaf_sem[id(leaf)] = _sem_name(
                    anchor, anchor_counts[anchor], anchor_thresholds.get(anchor, [])
                )
            elif anchor is None and leaf_participated:
                # Track FDR named-state transitions for non-chain leaves
                states = leaf.states or []
                if step + 1 < len(states):
                    after = states[step + 1]
                    if after not in ("<unchanged>", "<unnamed>", "STOP", "SKIP"):
                        per_leaf_sem[id(leaf)] = after

    # --- Deadlock state -------------------------------------------------------
    deadlock: list[dict] = []
    for leaf in leaves:
        proc = per_leaf_sem.get(id(leaf), display_names.get(id(leaf), leaf.machine_name))
        accepted = [event_map.get(str(e), str(e)) for e in leaf.acceptance]
        hl = _leaf_highlight(leaf)
        entry = {"id": leaf_index[id(leaf)], "name": proc, "acceptance": accepted}
        if hl:
            entry.update(hl)
        deadlock.append(entry)

    return {
        "csp_file": os.path.abspath(csp_file),
        "assertion": assertion.assertion_string,
        "components": [
            {"id": leaf_index[id(leaf)], "name": display_names.get(id(leaf), leaf.machine_name)}
            for leaf in leaves
        ],
        "steps": steps,
        "deadlock": deadlock,
    }
