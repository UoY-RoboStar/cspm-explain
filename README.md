# cspm-explain

Runs [FDR](https://cocotec.io/fdr/) on a CSP-M file that contains
deadlock-freedom assertions and produces plain-English explanations of any
counter-examples it finds. Can also be applied to a CSV file of CSP-M entries
with assertions and passing statuses.

## Requirements

- FDR 4 installed (`refines` on PATH)
- Python 3.11+
- `lark` Python package (`pip install lark`)

## Usage

```bash
python3 main.py path/to/spec.csp
```

For each failed deadlock assertion the tool prints:

- the trace that leads to the deadlock,
- how each component behaves at each step,
- the state of every component at the point of deadlock, and
- a root-cause analysis explaining why no further progress is possible.

```bash
python3 main.py path/to/spec.csv
```

For each failed deadlock assertion, as indicated within the CSV, the tool prints:

- the CSP
- the assertion
- the passing status
- the trace that leads to the deadlock,
- how each component behaves at each step,
- the state of every component at the point of deadlock, and
- a root-cause analysis explaining why no further progress is possible.

For each passing deadlock assertion, as indicated within the CSV, the tool prints:

- the CSP
- the assertion
- the passing status

### Optional: Output explanation to CSV

Passing "--output_csv" triggers the generation of an output file of the form 
`<file>-output.csv` containing the csp, assertion, passing status, and 
generated explanation steps. 

```bash
python3 main.py --output_csv path/to/spec.csp
python3 main.py --o path/to/spec.csp
python3 main.py --output_csv path/to/spec.csv
python3 main.py --o path/to/spec.csv
```

### Optional: Claude-powered explanations

Passing `--use-claude` replaces the built-in explainer with a call to the
Claude API. This requires the `anthropic` package and an API key:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python3 main.py --use-claude path/to/spec.csp
```

## Examples

```bash
python3 main.py examples/lock_ordering.csp
python3 main.py examples/traced_deadlock.csp
```

## How it works

1. Invokes `refines --format json --divide --compiler-leaf-compression none <file>`.
   - `--format json` — machine-readable output for parsing.
   - `--divide` — decomposes each counter-example into per-component traces
     so that each sub-process's local behaviour is visible separately.
   - `--compiler-leaf-compression none` — disables bisimulation minimisation
     on leaf machines, keeping counter-examples faithful to the source.
2. Parses the JSON and translates internal event IDs to names via the
   event map embedded in FDR's output.
3. Parses the CSP-M source with a lark Earley parser to resolve anonymous
   inline sub-expressions (e.g. the operands of a parallel composition) back
   to their original source text.
4. For each failed deadlock assertion, generates a structured explanation:
   traces are rendered step-by-step with before/after states per component,
   and the root cause is classified (lock-ordering cycle, premature
   termination, synchronisation mismatch, etc.).
