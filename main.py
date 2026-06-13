#!/usr/bin/env python3
"""cspm-explain: run FDR on a CSP file and explain any deadlock counter-examples."""

import argparse
import json
import os
import pathlib
import sys

from cspm_explain.explain import explain_deadlock, explain_fdr_output
from cspm_explain.fdr import run_fdr


def _print_header(assertion_string: str, idx: int, total: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"ASSERTION FAILED: {assertion_string}")
    if total > 1:
        print(f"Counter-example {idx} of {total}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run FDR on a CSP file and explain any deadlock counter-examples."
    )
    parser.add_argument("csp_file", help="Path to the .csp file to check")
    parser.add_argument(
        "--use-claude",
        action="store_true",
        help="Use Claude (requires ANTHROPIC_API_KEY) instead of the built-in explainer",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Write a <file>.replay.json alongside the explanation for interactive step-through",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.csp_file):
        sys.exit(f"Error: file not found: {args.csp_file}")

    with open(args.csp_file) as f:
        csp_source = f.read()

    print(f"Running FDR on {args.csp_file} …")
    try:
        fdr_output, _stderr = run_fdr(args.csp_file)
    except RuntimeError as exc:
        sys.exit(f"FDR error: {exc}")

    if fdr_output.errors:
        for err in fdr_output.errors:
            print(f"  Compilation error: {err}", file=sys.stderr)
        sys.exit(1)

    total    = len(fdr_output.results)
    passed   = sum(1 for r in fdr_output.results if r.result == 1)
    failed   = total - passed
    print(f"Results: {passed}/{total} assertions passed, {failed} failed.\n")

    failed_results = [r for r in fdr_output.results if r.result == 0 and r.counterexamples]
    if not failed_results:
        print("No deadlocks found.")
        return

    if args.use_claude:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit("Error: --use-claude requires ANTHROPIC_API_KEY to be set.")
        client = anthropic.Anthropic(api_key=api_key)
        explain_fdr_output(fdr_output, csp_source, client)
        return

    # ── Rule-based explanation (default) ────────────────────────────────────
    total_ces = sum(len(r.counterexamples) for r in failed_results)

    for a_idx, assertion in enumerate(failed_results):
        for idx, ce in enumerate(assertion.counterexamples, start=1):
            _print_header(assertion.assertion_string, idx, len(assertion.counterexamples))
            if ce.type != "deadlock":
                print(
                    f"  (counter-example type '{ce.type}' — "
                    "only deadlock explanations are currently supported)"
                )
                continue
            print()
            print(explain_deadlock(assertion, ce, fdr_output.event_map, csp_source))

            if args.replay:
                from cspm_explain.trace_replay import generate_replay
                replay_data = generate_replay(
                    assertion, ce, fdr_output.event_map, csp_source, args.csp_file
                )
                base = pathlib.Path(args.csp_file).with_suffix("")
                suffix = f".{a_idx}.{idx - 1}" if total_ces > 1 else ""
                replay_path = pathlib.Path(f"{base}{suffix}.replay.json")
                with open(replay_path, "w") as f:
                    json.dump(replay_data, f, indent=2)
                print(f"\nReplay written to: {replay_path}")


if __name__ == "__main__":
    main()
