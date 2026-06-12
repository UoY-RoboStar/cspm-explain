import json
import subprocess

from .model import FdrOutput

REFINES = "refines"
FDR_FLAGS = [
    "--format", "json",
    "--divide",
    "--compiler-leaf-compression", "none",
]


def run_fdr(csp_file: str) -> tuple[FdrOutput, str]:
    """Run FDR on *csp_file* and return (parsed output, stderr text)."""
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
