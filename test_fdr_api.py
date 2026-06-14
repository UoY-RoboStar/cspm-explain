#!/usr/bin/env python3
"""Test the Python3 FDR C++ API wrapper.

Answers two questions:
  1. Are machine names available via C++ API even with --compiler-reuse-machines off?
  2. Are tau events attributable via DebugContext.reveal_tau() even with reuse ON?
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import fdr_py as fdr

CSP_FILE = os.path.join(os.path.dirname(__file__), "examples/Zxoyx.csp")

print(f"FDR version: {fdr.version()}")
print(f"Valid license: {fdr.has_valid_license()}")
print()

# ---- Test with default options (compiler-reuse-machines = on) ----
print("=" * 60)
print("TEST 1: default FDR options (reuse machines = ON)")
print("=" * 60)

with fdr.FdrSession(CSP_FILE) as sess:
    assertions = sess.assertions()
    print(f"Found {len(assertions)} assertions")
    for a in assertions:
        a.execute()
        label = a.to_string()
        status = "PASS" if a.passed() else "FAIL"
        print(f"  {status}: {label}")
        if not a.passed():
            ces = a.counterexamples()
            print(f"    {len(ces)} counterexample(s)")
            for ce in ces:
                if not ce.is_property():
                    continue
                root_beh = ce.property_behaviour()
                if root_beh is None:
                    continue
                trace_len = root_beh.trace_len()
                mname = sess.machine_name_for(root_beh)
                print(f"    root behaviour: machine={mname!r}, trace_len={trace_len}")

                dc = ce.debug_context(elide_uninteresting=True)
                dc.initialise()
                roots = dc.root_behaviours()
                print(f"    DebugContext root behaviours: {len(roots)}")
                for rb in roots:
                    rb_name = sess.machine_name_for(rb)
                    rb_trace = rb.trace()
                    taus = [i for i, e in enumerate(rb_trace) if e == fdr.TAU]
                    print(f"      machine={rb_name!r}, trace_len={len(rb_trace)}, tau_indices={taus}")

                    # For each tau, reveal which child behaviour caused it
                    if taus:
                        print(f"      reveal_tau results:")
                        for tau_idx in taus:
                            child = dc.reveal_tau(rb, tau_idx)
                            if child is not None:
                                child_name = sess.machine_name_for(child)
                                print(f"        tau@{tau_idx} -> child machine={child_name!r}")
                            else:
                                print(f"        tau@{tau_idx} -> None (non-determinism)")

                    # reveal_taus_in_trace: full trace with tau replaced by actual event
                    revealed = dc.reveal_taus_in_trace(rb)
                    tau_revealed = {i: revealed[i] for i in taus if i < len(revealed)}
                    if tau_revealed:
                        print(f"      reveal_taus_in_trace (tau positions only):")
                        for idx, ev in tau_revealed.items():
                            evname = sess.uncompile_event(ev) if ev not in (fdr.TAU, fdr.INVALID_EVENT) else f"(tau/invalid={ev})"
                            print(f"        tau@{idx} -> {evname!r}")

                    # Also check children
                    children = dc.children(rb)
                    print(f"      children: {len(children)}")
                    for ch in children:
                        ch_name = sess.machine_name_for(ch)
                        ch_trace = ch.trace()
                        ch_taus = [i for i, e in enumerate(ch_trace) if e == fdr.TAU]
                        print(f"        child machine={ch_name!r}, trace_len={len(ch_trace)}, tau_indices={ch_taus}")

print()

# ---- Test with reuse-machines OFF to check if machine names still work ----
print("=" * 60)
print("TEST 2: compiler-reuse-machines = off")
print("=" * 60)

fdr.set_option("compiler-reuse-machines", "off")
print(f"compiler-reuse-machines = {fdr.get_option('compiler-reuse-machines')!r}")
print()

with fdr.FdrSession(CSP_FILE) as sess:
    assertions = sess.assertions()
    for a in assertions:
        a.execute()
        label = a.to_string()
        status = "PASS" if a.passed() else "FAIL"
        print(f"  {status}: {label}")
        if not a.passed():
            ces = a.counterexamples()
            for ce in ces:
                if not ce.is_property():
                    continue
                root_beh = ce.property_behaviour()
                if root_beh is None:
                    continue
                mname = sess.machine_name_for(root_beh)
                trace_len = root_beh.trace_len()
                trace = root_beh.trace()
                taus = [i for i, e in enumerate(trace) if e == fdr.TAU]
                print(f"    root behaviour: machine={mname!r}, trace_len={trace_len}, tau_indices={taus}")

                # Check DebugContext children machine names
                dc = ce.debug_context()
                dc.initialise()
                roots = dc.root_behaviours()
                for rb in roots:
                    rb_name = sess.machine_name_for(rb)
                    rb_trace = rb.trace()
                    rb_taus = [i for i, e in enumerate(rb_trace) if e == fdr.TAU]
                    print(f"      dbg-root machine={rb_name!r}, trace_len={len(rb_trace)}, tau_indices={rb_taus}")
                    children = dc.children(rb)
                    for ch in children:
                        ch_name = sess.machine_name_for(ch)
                        ch_trace = ch.trace()
                        ch_taus = [i for i, e in enumerate(ch_trace) if e == fdr.TAU]
                        print(f"        child machine={ch_name!r}, trace_len={len(ch_trace)}, tau_indices={ch_taus}")
