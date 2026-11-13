"""Sandbox runner: executed in a separate `python -I` subprocess by execute.py.
Reads JSON {program, entry_point, inputs_repr:[...]} on stdin, runs the entry point on every
input with a per-input wall-clock timeout, writes JSON list of outcomes on stdout.
Outcome: {"ok": true, "repr": "..."} | {"ok": false, "exc": "ExceptionType"} | {"ok": false, "exc": "Timeout"}."""
import json
import math
import resource
import signal
import sys


class _Timeout(BaseException):   # BaseException: a program's own `except Exception` cannot swallow it
    pass


def _alarm(signum, frame):
    raise _Timeout()


_ALLOWED = {"inf": math.inf, "nan": math.nan, "True": True, "False": False, "None": None}


def _parse(s):
    import ast
    tree = ast.parse(s, mode="eval")

    def ev(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in _ALLOWED:
            return _ALLOWED[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.List):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(ev(e) for e in node.elts)
        if isinstance(node, ast.Set):
            return set(ev(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return {ev(k): ev(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id in ("set", "frozenset", "tuple", "list", "dict") and len(node.args) <= 1:
            arg = ev(node.args[0]) if node.args else []
            return {"set": set, "frozenset": frozenset, "tuple": tuple, "list": list, "dict": dict}[node.func.id](arg)
        raise ValueError("disallowed")
    return ev(tree.body)


def main():
    job = json.load(sys.stdin)
    per_input = float(job.get("per_input_timeout", 2.0))
    max_timeouts = int(job.get("max_timeouts", 4))
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (int(job.get("cpu_limit", 80)), int(job.get("cpu_limit", 80)) + 5))
    except Exception:
        pass
    # best-effort extra limits (process-level only; there is no filesystem or network sandbox)
    for lim, val in ((getattr(resource, "RLIMIT_FSIZE", None), 1 << 20),      # max 1 MB per written file
                     (getattr(resource, "RLIMIT_AS", None), 4 << 30),         # 4 GB address space (not enforced on macOS)
                     (getattr(resource, "RLIMIT_CORE", None), 0)):
        if lim is None:
            continue
        try:
            resource.setrlimit(lim, (val, val))
        except Exception:
            pass
    sys.setrecursionlimit(4000)
    g = {"__name__": "__sandbox__"}
    outcomes = []
    import io
    import contextlib
    try:
        with contextlib.redirect_stdout(io.StringIO()):   # module-level prints must not corrupt the JSON
            exec(compile(job["program"], "<program>", "exec"), g)
        fn = g[job["entry_point"]]
    except BaseException as e:  # noqa: B036
        json.dump([{"ok": False, "exc": "LoadError:" + type(e).__name__}] * len(job["inputs_repr"]), sys.stdout)
        return
    signal.signal(signal.SIGALRM, _alarm)
    n_timeouts = 0
    # silence program output
    for s in job["inputs_repr"]:
        if n_timeouts >= max_timeouts:
            outcomes.append({"ok": False, "exc": "Timeout"})
            continue
        try:
            args = _parse(s)
        except Exception:
            outcomes.append({"ok": False, "exc": "InputParseError"})
            continue
        signal.setitimer(signal.ITIMER_REAL, per_input)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                out = fn(*args)
            signal.setitimer(signal.ITIMER_REAL, 0)
            r = repr(out)
            if len(r) > 4000:
                import hashlib
                r = r[:4000] + f"...<sha{hashlib.sha1(r.encode()).hexdigest()[:8]}>"
            outcomes.append({"ok": True, "repr": r})
        except _Timeout:
            n_timeouts += 1
            outcomes.append({"ok": False, "exc": "Timeout"})
        except RecursionError:
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes.append({"ok": False, "exc": "RecursionError"})
        except BaseException as e:  # noqa: B036
            signal.setitimer(signal.ITIMER_REAL, 0)
            outcomes.append({"ok": False, "exc": type(e).__name__})
    json.dump(outcomes, sys.stdout)


if __name__ == "__main__":
    main()
