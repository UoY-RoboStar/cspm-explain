import csv
import os

def write_csv(file_path: str, csp, assertion, passed, counterexample, trace, steps,state, root) -> None:
    print(f"Writing to {file_path}")

    with open(file_path, mode="a+") as csv_file:
        csv_writer = csv.writer(csv_file)
        if not (os.path.isfile(file_path) and os.path.getsize(file_path) > 0):
            csv_writer.writerow(["CSP", "Assertion", "Passed", "CounterExample", "Trace", "Steps", "State at point of deadlock", "Root Cause"])
        if trace!="": trace_entry = trace[0:len(trace)-24].strip()
        else: trace_entry = trace
        if root!="": root_entry = root[12:].strip()
        else: root_entry = root
        if state!="": state_entry = state[32:].strip()
        else: state_entry = state
        csv_writer.writerow([csp.strip(), assertion.strip(), passed, counterexample.strip(), trace_entry, steps.strip(), state_entry, root_entry])
