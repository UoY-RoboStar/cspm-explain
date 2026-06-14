import json
import subprocess

from .model import FdrOutput

REFINES = "refines"
# CLI fallback flags — used only when the C++ API is unavailable.
# Note: --compiler-reuse-machines is intentionally left at its default (on),
# because the C++ API path always returns correct machine names via
# Session::machine_name() regardless of that setting.
FDR_FLAGS = [
    "--format", "json",
    "--divide",
    "--compiler-leaf-compression", "none",
]


def run_fdr(csp_file: str) -> tuple[FdrOutput, str]:
    """Run FDR on *csp_file* and return (FdrOutput, stderr).

    Tries the C++ API (fdr_api.py) first for richer data (correct machine
    names, τ attribution via revealed_trace).  Falls back to the CLI if the
    compiled extension is unavailable.
    """
    try:
        from .fdr_api import run_fdr_api
        return run_fdr_api(csp_file)
    except Exception:
        pass
    return _run_fdr_cli(csp_file)


def _run_fdr_cli(csp_file: str) -> tuple[FdrOutput, str]:
    """CLI fallback: invoke *refines* and parse its JSON output."""
    proc = subprocess.run(
        [REFINES, *FDR_FLAGS, csp_file],
        capture_output=True,
        text=True,
    )

    if not proc.stdout.strip():
        raise RuntimeError(
            f"FDR produced no JSON output (exit {proc.returncode}).\n"
            f"Stderr:\n{proc.stderr}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Could not parse FDR JSON: {exc}\n"
            f"First 500 chars of stdout:\n{proc.stdout[:500]}"
        ) from exc

    return FdrOutput.from_dict(data), proc.stderr
