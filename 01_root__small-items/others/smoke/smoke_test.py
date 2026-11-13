#!/usr/bin/env python3
"""Hypothesis smoke test for E02 Counterfactual Comprehension (stdlib only, seeded, deterministic).

Mechanism-level checks on a small embedded testbed of 8 Python functions -- NOT a real-data result.
  H0  the programmatic articulation checker separates an execution-grounded articulator (template
      built from differential execution) from an ungrounded articulator (guesses the witness/outputs);
      real AST mutation + real differential execution + real paired bootstrap CI.
  H1  (instrument, model-side) a simulated reader that traces correctly with prob p but applies a
      stated intervention correctly with prob q < 1 scores lower on counterfactual than descriptive
      questions, i.e. the instrument has the intended difficulty ordering (direction only).
  equivalent-mutant handling: operators that do not change behaviour on the inputs are detected and skipped.
"""
import ast
import copy
import random

SEED = 20261109
TESTBED = {
    "clamp": ("def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n",
              [(5, 0, 10), (-3, 0, 10), (12, 0, 10), (0, 0, 10), (10, 0, 10), (7, 7, 7)]),
    "abs_sum": ("def abs_sum(xs):\n    s = 0\n    for v in xs:\n        if v < 0:\n            v = -v\n        s = s + v\n    return s\n",
                [([1, -2, 3],), ([],), ([-5],), ([0, 0],), ([4, 4],)]),
    "safe_div": ("def safe_div(a, b, default=0):\n    if b == 0:\n        return default\n    return a // b\n",
                 [(6, 3), (1, 0), (7, 2), (0, 5), (9, -3)]),
    "is_even_pos": ("def is_even_pos(n):\n    return n > 0 and n % 2 == 0\n",
                    [(2,), (3,), (-2,), (0,), (10,)]),
    "first_big": ("def first_big(xs, t):\n    for i in range(len(xs)):\n        if xs[i] >= t:\n            return i\n    return -1\n",
                  [([1, 5, 9], 5), ([1, 2], 5), ([], 1), ([5], 5), ([9, 1], 2)]),
    "count_until": ("def count_until(xs, stop):\n    c = 0\n    for v in xs:\n        if v == stop:\n            break\n        c = c + 1\n    return c\n",
                    [([1, 2, 3], 3), ([1, 2, 3], 9), ([], 1), ([3], 3), ([2, 2, 3, 2], 3)]),
    "grade": ("def grade(s):\n    if s >= 90:\n        return 'A'\n    if s >= 80:\n        return 'B'\n    return 'C'\n",
              [(95,), (90,), (85,), (80,), (10,), (89,)]),
    "dedup_len": ("def dedup_len(xs):\n    if not xs:\n        return 0\n    return len(set(xs))\n",
                  [([],), ([1, 1, 2],), ([3],), ([1, 2, 3, 3],)]),
}

CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
ARITH_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mod: ast.FloorDiv, ast.FloorDiv: ast.Mod}


def run(src, name, args):
    g = {}
    exec(compile(src, "<t>", "exec"), g)
    try:
        return ("ok", repr(g[name](*args)))
    except Exception as e:  # noqa: BLE001
        return ("exc", type(e).__name__)


def candidates(src):
    tree = ast.parse(src)
    out = []
    for i, n in enumerate(ast.walk(tree)):
        if isinstance(n, ast.If):
            out.append(("NEG_GUARD", i))
        if isinstance(n, ast.Compare) and type(n.ops[0]) in CMP_SWAP:
            out.append(("CMP_OP", i))
        if isinstance(n, ast.BinOp) and type(n.op) in ARITH_SWAP:
            out.append(("ARITH_OP", i))
        if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool):
            out.append(("BOUND_CONST", i))
    return out


def apply(src, cand):
    op, i = cand
    tree = ast.parse(src)
    n = list(ast.walk(tree))[i]
    if op == "NEG_GUARD":
        n.test = ast.UnaryOp(op=ast.Not(), operand=n.test)
    elif op == "CMP_OP":
        n.ops[0] = CMP_SWAP[type(n.ops[0])]()
    elif op == "ARITH_OP":
        n.op = ARITH_SWAP[type(n.op)]()
    elif op == "BOUND_CONST":
        n.value = n.value + 1
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def bootstrap_ci(xs, rng, reps=2000):
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps)]


def verdict(ok):
    return "HOLDS" if ok else "DOES-NOT-HOLD"


def main():
    rng = random.Random(SEED)
    print(f"# E02 smoke test (seed={SEED}); mechanism-level, synthetic testbed, NOT a paper result")
    # ---- mutation + differential execution, with equivalent-mutant detection
    mutants, n_equiv, n_tried = [], 0, 0
    for name, (src, inputs) in TESTBED.items():
        cands = candidates(src)
        rng.shuffle(cands)
        for cand in cands:
            n_tried += 1
            try:
                mut = apply(src, cand)
            except Exception:  # noqa: BLE001
                continue
            o = [run(src, name, a) for a in inputs]
            m = [run(mut, name, a) for a in inputs]
            diff = [k for k in range(len(inputs)) if o[k] != m[k]]
            if not diff:
                n_equiv += 1
                continue
            mutants.append((name, src, mut, inputs, o, m, diff))
            break
    print(f"  mutation: {len(mutants)}/{len(TESTBED)} functions got a non-equivalent mutant; "
          f"{n_equiv}/{n_tried} candidates were equivalent on the inputs (skipped)")
    assert all(len(d) >= 1 for *_, d in mutants)

    # ---- H0: programmatic checker on grounded (template) vs ungrounded (guessing) articulators
    def check(name, src, mut, witness, claim_o, claim_m):
        o, m = run(src, name, witness), run(mut, name, witness)
        return o != m and claim_o == o and claim_m == m   # passes iff witness differs & both claims right

    err_g, err_u = [], []
    for name, src, mut, inputs, o, m, diff in mutants:
        k = diff[0]                                     # grounded: template reads evidence
        err_g.append(0 if check(name, src, mut, inputs[k], o[k], m[k]) else 1)
        j = rng.randrange(len(inputs))                  # ungrounded: picks an input without executing,
        guess_m = ("ok", repr(rng.choice([0, 1, -1, True, False, None])))  # guesses the mutant output
        err_u.append(0 if check(name, src, mut, inputs[j], o[j], guess_m) else 1)
    d = [u - g for u, g in zip(err_u, err_g)]
    lo, hi = bootstrap_ci(d, rng)
    h0 = sum(err_g) == 0 and lo > 0
    print(f"  H0: articulation error grounded={sum(err_g)/len(err_g):.2f} ungrounded={sum(err_u)/len(err_u):.2f} "
          f"paired diff CI=[{lo:+.2f},{hi:+.2f}] -> {verdict(h0)}")

    # ---- H1 (instrument ordering under a simulated reader; direction only)
    p_trace, q_apply = 0.85, 0.7
    desc, cf = [], []
    for _ in range(4000):
        desc.append(1 if rng.random() < p_trace else 0)
        cf.append(1 if (rng.random() < p_trace and rng.random() < q_apply) else 0)
    gap = sum(desc) / len(desc) - sum(cf) / len(cf)
    lo, hi = bootstrap_ci([a - b for a, b in zip(desc, cf)], rng)
    h1 = lo > 0
    print(f"  H1: desc acc={sum(desc)/len(desc):.3f} cf acc={sum(cf)/len(cf):.3f} gap={gap:+.3f} "
          f"CI=[{lo:+.3f},{hi:+.3f}] -> {verdict(h1)} (simulated reader; ordering only)")
    print("  H2/H3: human-study hypotheses -- NOT TESTABLE here (protocol only)")
    print("# Verdicts:", {"H0": verdict(h0), "H1": verdict(h1), "H2": "NOT-TESTABLE", "H3": "NOT-TESTABLE"})


if __name__ == "__main__":
    main()
