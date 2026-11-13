"""Differential execution: run a program (original or mutant) on a list of inputs inside a
separate isolated subprocess (python -I, CPU rlimit, per-input and whole-process timeouts)."""
import json
import os
import subprocess
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import PER_INPUT_TIMEOUT, PROCESS_TIMEOUT, outcomes_equal  # noqa: E402

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_runner.py")


def run_program(program, entry_point, inputs_repr, per_input_timeout=PER_INPUT_TIMEOUT,
                process_timeout=PROCESS_TIMEOUT, max_timeouts=4):
    job = {"program": program, "entry_point": entry_point, "inputs_repr": inputs_repr,
           "per_input_timeout": per_input_timeout, "max_timeouts": max_timeouts,
           "cpu_limit": int(process_timeout)}
    with tempfile.TemporaryDirectory() as td:
        try:
            p = subprocess.run([sys.executable, "-I", RUNNER], input=json.dumps(job).encode(),
                               capture_output=True, timeout=process_timeout, cwd=td,
                               env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"})
        except subprocess.TimeoutExpired:
            return [{"ok": False, "exc": "ProcessTimeout"}] * len(inputs_repr)
    if p.returncode != 0 or not p.stdout.strip():
        return [{"ok": False, "exc": "ProcessCrash"}] * len(inputs_repr)
    try:
        return json.loads(p.stdout.decode())
    except Exception:
        return [{"ok": False, "exc": "ProcessCrash"}] * len(inputs_repr)


def differential(orig_outcomes, mut_outcomes, set_compare=False):
    """Indices of inputs on which outcomes differ."""
    return [i for i, (a, b) in enumerate(zip(orig_outcomes, mut_outcomes))
            if not outcomes_equal(a, b, set_compare)]
