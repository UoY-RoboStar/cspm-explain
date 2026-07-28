#!/usr/bin/env python3
"""cspm-explain: run FDR on a CSP file and explain any deadlock counter-examples."""

import argparse
import json
import os
import pathlib
import sys

from cspm_explain import csv_writer
from cspm_explain import csv_parser
from cspm_explain.explain import explain_deadlock, explain_fdr_output
from cspm_explain.fdr import run_fdr


def _print_header(assertion_string: str, idx: int, total: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"ASSERTION FAILED: {assertion_string}")
    if total > 1:
        print(f"Counter-example {idx} of {total}")
    print("=" * 70)

def _format_counterexample(event_map, trace) -> str:
    formatted_trace = []
    for element in trace:
        if str(element) in event_map:
            formatted_trace.append(event_map[str(element)])

    return "<"+(",".join(formatted_trace))+">"

def _create_temp_file(csp, csp_file) -> str:
    filepath = csp_file[:len(csp_file)-4]+"temp.csp"
    with open(filepath, "w+") as f:
        f.write(csp.strip())

    return filepath

def _delete_temp_fle(temp_file) -> None:
    os.remove(temp_file)

def _run_explainer(csp_source, csp_file, replay: bool, output_csv, dataset: bool= False) -> None:
    print(f"Running FDR on {csp_file} …")
    if dataset:
        csp = csp_source[0]
        passed = csp_source[2]
    else:
        csp = csp_source
        passed = "false"

    if passed != "true":
        try:
            if dataset:
                temp_file = _create_temp_file(csp, csp_file)
                fdr_output, _stderr = run_fdr(temp_file)
                _delete_temp_fle(temp_file)
            else:
                fdr_output, _stderr = run_fdr(csp_file)
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

        # ── Rule-based explanation (default) ────────────────────────────────────
        total_ces = sum(len(r.counterexamples) for r in failed_results)

        for a_idx, assertion in enumerate(failed_results):
            for idx, ce in enumerate(assertion.counterexamples, start=1):
                _print_header(assertion.assertion_string, idx, len(assertion.counterexamples))
                counterexample = _format_counterexample(fdr_output.event_map,ce.implementation_behaviour.trace)
                if ce.type != "deadlock":
                    print(
                        f"  (counter-example type '{ce.type}' — "
                        "only deadlock explanations are currently supported)"
                    )
                    continue
                print()
                trace,steps,state,root = explain_deadlock(assertion.assertion_string, ce, fdr_output.event_map, csp)
                print(trace+"\n"+steps+"\n"+state+"\n"+root)

                if output_csv is not None:
                    csv_writer.write_csv(output_csv, csp_source[4], csp_source[1], passed, counterexample, trace, steps, state, root)

                if replay:
                    from cspm_explain.trace_replay import generate_replay
                    from cspm_explain.trace_replay_html import generate_replay_html
                    replay_data = generate_replay(
                        assertion, ce, fdr_output.event_map, csp_source, csp_file
                    )
                    base = pathlib.Path(csp_file).with_suffix("")
                    suffix = f".{a_idx}.{idx - 1}" if total_ces > 1 else ""
                    replay_path = pathlib.Path(f"{base}{suffix}.replay.json")
                    html_path   = pathlib.Path(f"{base}{suffix}.replay.html")
                    with open(replay_path, "w") as f:
                        json.dump(replay_data, f, indent=2)
                    with open(html_path, "w") as f:
                        f.write(generate_replay_html(replay_data, csp_source))
                    print(f"\nReplay written to: {replay_path}")
                    print(f"Viewer  written to: {html_path}")

    else:
        if output_csv is not None:
            csv_writer.write_csv(output_csv, csp_source[4], csp_source[1], passed, "",
                             "", "", "", "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run FDR on a CSP file and explain any deadlock counter-examples."
    )
    parser.add_argument("csp_file", help="Path to the .csp (or .csv) file to check")
#    parser.add_argument(
#        "-c",
#        "--use-claude",
#        action="store_true",
#        help="Use Claude (requires ANTHROPIC_API_KEY) instead of the built-in explainer",
#    )
    parser.add_argument(
        "-r",
        "--replay",
        action="store_true",
        help="Write a <file>.replay.json alongside the explanation for interactive step-through",
    )
    parser.add_argument(
        "-o",
        "--output_csv",
        help="Write a <file>-output.csv alongside the explanation",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.csp_file):
        sys.exit(f"Error: file not found: {args.csp_file}")

    with open(args.csp_file) as f:
        csp_source = f.read()

        if args.csp_file.endswith(".csv") or args.csp_file.endswith(".csv.gz"):
            parsed_csv = csv_parser.parse_csv(args.csp_file)
            for entry in parsed_csv:
                _run_explainer(entry, args.csp_file, args.replay, args.output_csv, True)
        else:
            _run_explainer(csp_source, args.csp_file, args.replay, args.output_csv)


if __name__ == "__main__":
    main()
