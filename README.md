# cspm-explain

Runs [FDR](https://cocotec.io/fdr/) on a CSP file that contains deadlock-freedom
assertions and uses Claude to explain any counter-examples it finds.

## Requirements

- FDR 4 installed (`refines` on PATH)
- Python 3.11+
- `anthropic` Python package (`pip install anthropic`)
- `ANTHROPIC_API_KEY` environment variable set

## Usage

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 main.py path/to/spec.csp
```

## How it works

1. Invokes `refines --format json --divide --compiler-leaf-compression none <file>`.
   - `--format json` — machine-readable output for parsing.
   - `--divide` — splits counter-examples per component process so each
     sub-machine's local trace and state are visible.
   - `--compiler-leaf-compression none` — disables `sbisim`/`dbisim` compression
     on leaf machines, keeping the counter-example faithful to the source.
2. Parses the JSON, translates internal event IDs to names via the `event_map`.
3. For each failed deadlock assertion, builds a structured description of the
   counter-example (trace, component states, accepted events) and asks Claude
   to explain in plain English why the deadlock occurs and how it might be fixed.

## Examples

```bash
python3 main.py examples/immediate_deadlock.csp
python3 main.py examples/traced_deadlock.csp
```
