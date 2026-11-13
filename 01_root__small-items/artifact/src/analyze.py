"""Stage 6: statistics. Reads results/*.jsonl, writes results/*.csv and results/summary.json.
Bootstrap CIs resample FUNCTIONS (the unit of analysis); paired tests are exact McNemar; Holm correction is applied
across the family of reported hypothesis tests (keys *_p_holm). Round 2 (after review): witness error with/without
copies and malformed witnesses, executable affected-input predicates, the docstring-stripped probe with CF_CTRL,
per-benchmark splits, differing-fraction strata. Judge statistics are descriptive only."""
import ast
import csv
import json
import os
import random
import re
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)
from collections import Counter

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS, SEED, GEN_MODEL, STRONG_MODEL, JUDGE_MODELS, PROBE_MODELS, read_jsonl  # noqa: E402
from mutate import OPERATORS  # noqa: E402

B = 2000
OP_LABEL = {"NEG_GUARD": "negate guard", "DEL_GUARD": "remove check", "CMP_OP": "comparison op",
            "DEF_ARG": "default arg", "ARITH_OP": "arithmetic op", "BOUND_CONST": "boundary const"}
GK = {GEN_MODEL: "gen", STRONG_MODEL: "strong"}
PK = {PROBE_MODELS[0]: "p14", PROBE_MODELS[1]: "p7"}
SRC = {"HumanEval+": "he", "MBPP+": "mb"}
TESTS = {}          # name -> raw p, for Holm


def tag(model):
    return model.replace(":", "_").replace("/", "_")


def boot_rate(x, rng):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    m = x[rng.integers(0, len(x), size=(B, len(x)))].mean(axis=1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def boot_diff(a, b, rng):
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    m = d[rng.integers(0, len(d), size=(B, len(d)))].mean(axis=1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def mcnemar(a, b):
    """a, b: binary indicators per unit. Exact two-sided McNemar p on discordant pairs."""
    n10 = int(sum(1 for x, y in zip(a, b) if x and not y))
    n01 = int(sum(1 for x, y in zip(a, b) if y and not x))
    n = n10 + n01
    p = 1.0 if n == 0 else float(stats.binomtest(min(n10, n01), n, 0.5).pvalue)
    return n10, n01, p


def kappa(x, y):
    x, y = np.asarray(x, dtype=int), np.asarray(y, dtype=int)
    po = float((x == y).mean())
    pe = float(x.mean() * y.mean() + (1 - x.mean()) * (1 - y.mean()))
    return po, ((po - pe) / (1 - pe) if pe < 1 else float("nan"))


def write_csv(name, rows, fields):
    with open(os.path.join(RESULTS, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def paired(S, key, a, b, rng, test=True):
    """Store rates of a and b (indicators), their difference with CI, and exact McNemar."""
    S[f"{key}_a"], S[f"{key}_a_lo"], S[f"{key}_a_hi"] = boot_rate(a, rng)
    S[f"{key}_b"], S[f"{key}_b_lo"], S[f"{key}_b_hi"] = boot_rate(b, rng)
    S[f"{key}_d"], S[f"{key}_d_lo"], S[f"{key}_d_hi"] = boot_diff(a, b, rng)
    n10, n01, p = mcnemar(a, b)
    S[f"{key}_n10"], S[f"{key}_n01"], S[f"{key}_n"] = n10, n01, len(a)
    S[f"{key}_p"] = p
    if test:
        TESTS[key] = p


def stratum(m):
    f = m["n_differ"] / m["n_inputs"]
    return "narrow" if f < 0.10 else ("mid" if f < 0.50 else "broad")


def main():
    rng = np.random.default_rng(SEED)
    S = {"seed": SEED, "bootstrap_reps": B}
    mutants_all = read_jsonl(os.path.join(RESULTS, "mutants.jsonl"))
    mutants = [m for m in mutants_all if m.get("op")]
    mm = {m["id"]: m for m in mutants}
    ids_all = [m["id"] for m in mutants]
    mstats = json.load(open(os.path.join(RESULTS, "mutation_stats.json")))
    S.update({f"mut_{k}": v for k, v in mstats.items()})
    S["n_mutants"] = len(mutants)
    S["n_functions_attempted"] = len(mutants_all)
    S["equivalent_candidate_rate"] = mstats["equivalent"] / mstats["candidates_tried"]
    S["n_humaneval"] = sum(1 for m in mutants if m["source"] == "HumanEval+")
    S["n_mbpp"] = sum(1 for m in mutants if m["source"] == "MBPP+")
    S["n_no_candidates"] = mstats["no_candidates"]
    S["n_no_nonequivalent"] = sum(1 for m in mutants_all if not m.get("op") and
                                  m["bookkeeping"].get("reason") == "no_nonequivalent_mutant")
    S["n_degenerate"] = mstats["non_terminating"] + mstats["crashes_everywhere"]
    S["median_differing_fraction"] = float(np.median([m["n_differ"] / m["n_inputs"] for m in mutants]))
    S["mean_inputs_per_function"] = float(np.mean([m["n_inputs"] for m in mutants]))
    S["n_line_mismatch_round1"] = sum(1 for m in mutants if m["line"] != m["line_norm"])

    def raises_mostly(m):   # the mutant raises (where the original returns) on more than half of T
        k = sum(1 for e in m["differing"] if e["orig"].get("ok") and not e["mut"].get("ok"))
        return k > m["n_inputs"] / 2
    S["n_mutants_raise_mostly"] = sum(1 for m in mutants if raises_mostly(m))
    S["n_mutants_exception_change"] = sum(1 for m in mutants if any(
        e["orig"].get("ok") != e["mut"].get("ok") for e in m["differing"]))
    S["n_mutants_all_differ"] = sum(1 for m in mutants if m["n_differ"] == m["n_inputs"])
    for st in ("narrow", "mid", "broad"):
        S[f"n_stratum_{st}"] = sum(1 for m in mutants if stratum(m) == st)

    hp = os.path.join(RESULTS, "heldout_mutants.jsonl")
    if os.path.exists(hp):
        H = [h for h in read_jsonl(hp) if h.get("op")]
        S["n_heldout"] = len(H)
        S["n_heldout_mixed"] = sum(1 for h in H if h["unaffected_inputs"])
        S["n_heldout_mixed_narrow"] = sum(1 for h in H if h["unaffected_inputs"] and h["n_differ"] / h["n_inputs"] < 0.5)

    # ------------------------------------------------------------------ witness error (programmatic)
    scores = {}
    for gen in (GEN_MODEL, STRONG_MODEL):
        path = os.path.join(RESULTS, f"scores_{tag(gen)}.jsonl")
        if os.path.exists(path):
            scores[gen] = {(r["id"], r["condition"]): r for r in read_jsonl(path)}
    fail_rows, op_rows = [], []
    for gen, by in scores.items():
        gk = GK[gen]
        ids = [i for i in ids_all if (i, "ungrounded") in by and (i, "grounded") in by]
        S[f"wit_{gk}_n"] = len(ids)
        P = {(i, c): by[(i, c)]["programmatic"] for i in ids for c in ("ungrounded", "grounded")}
        err = lambda i, c: int(P[(i, c)]["error"])                                     # noqa: E731
        cop = lambda i: int(P[(i, "grounded")].get("copied", False))                    # noqa: E731
        mal = lambda i, c: int(P[(i, c)].get("failure") == "malformed-witness")          # noqa: E731
        u = [err(i, "ungrounded") for i in ids]
        g = [err(i, "grounded") for i in ids]
        gs = [int(err(i, "grounded") or cop(i)) for i in ids]                            # strict: copies = errors
        paired(S, f"wit_{gk}_raw", u, g, rng)
        paired(S, f"wit_{gk}_strict", u, gs, rng)
        # reasoning-only: malformed witnesses (same exception on both versions) are not counted as errors
        ur = [int(err(i, "ungrounded") and not mal(i, "ungrounded")) for i in ids]
        gsr = [int((err(i, "grounded") and not mal(i, "grounded")) or cop(i)) for i in ids]
        paired(S, f"wit_{gk}_strictreason", ur, gsr, rng, test=False)
        S[f"wit_{gk}_malformed_u"] = float(np.mean([mal(i, "ungrounded") for i in ids]))
        S[f"wit_{gk}_malformed_g"] = float(np.mean([mal(i, "grounded") for i in ids]))
        S[f"wit_{gk}_copied"] = float(np.mean([cop(i) for i in ids]))
        S[f"wit_{gk}_own_valid_u"] = int(sum(1 - x for x in u))
        S[f"wit_{gk}_own_valid_g"] = int(sum(1 for i in ids if not err(i, "grounded") and not cop(i)))
        S[f"wit_{gk}_copied_pass"] = int(sum(1 for i in ids if not err(i, "grounded") and cop(i)))
        # near copies: grounded witness within edit distance 3 (on the canonical repr) of a shown input
        from prompts import shown_inputs
        import difflib
        near = 0
        for i in ids:
            w = P[(i, "grounded")].get("witness_repr")
            if w and not cop(i):
                if any(difflib.SequenceMatcher(None, w, s).ratio() >= 0.85 for s in shown_inputs(mm[i])):
                    near += 1
        S[f"wit_{gk}_nearcopy"] = near / len(ids)
        for cond in ("ungrounded", "grounded"):
            c = Counter(P[(i, cond)]["failure"] for i in ids)
            for k, v in sorted(c.items()):
                fail_rows.append({"generator": gen, "condition": cond, "failure": k, "n": v,
                                  "rate": f"{v/len(ids):.4f}"})
            for k in ("unparsable", "no-witness", "malformed-witness", "witness-not-differing",
                      "wrong-original-output", "wrong-mutant-output"):
                S[f"fail_{gk}_{cond}_{k.replace('-', '')}"] = c.get(k, 0) / len(ids)
        for st in ("narrow", "mid", "broad"):
            sub = [i for i in ids if stratum(mm[i]) == st]
            S[f"wit_{gk}_u_{st}"] = float(np.mean([err(i, "ungrounded") for i in sub])) if sub else float("nan")
            S[f"wit_{gk}_gs_{st}"] = float(np.mean([int(err(i, "grounded") or cop(i)) for i in sub])) if sub else float("nan")
        for op in OPERATORS:
            sub = [i for i in ids if mm[i]["op"] == op]
            if sub:
                op_rows.append({"generator": gen, "op": op, "n": len(sub),
                                "wit_u": f"{np.mean([err(i, 'ungrounded') for i in sub]):.4f}",
                                "wit_g": f"{np.mean([err(i, 'grounded') for i in sub]):.4f}",
                                "wit_gs": f"{np.mean([int(err(i, 'grounded') or cop(i)) for i in sub]):.4f}"})
    write_csv("failure_modes.csv", fail_rows, ["generator", "condition", "failure", "n", "rate"])

    # ------------------------------------------------------------------ affected-input predicates
    # Conventions: a predicate is UNSCORABLE if it has no code, is rejected by the static filter, or returns no bool on
    # any input (malformed). Exact error counts unscorable as error ("overall") and is also reported without them.
    # Graded metrics are per-function means: balanced accuracy (unscorable = 0.5, chance), F1 and accuracy (unscorable
    # excluded). The constant "every input affected" predicate is the baseline. Optional predicate form labels
    # (genuine / dual / guard / trivial / malformed) can be loaded from results/predicate_labels.jsonl if present.
    pred_rows = []
    preds = {}
    labels = {}
    lp = os.path.join(RESULTS, "predicate_labels.jsonl")
    if os.path.exists(lp):
        labels = {(r["model"], r["id"], r["condition"]): r["label"] for r in read_jsonl(lp)}
    for gen in (GEN_MODEL, STRONG_MODEL):
        path = os.path.join(RESULTS, f"predicates_{tag(gen)}.jsonl")
        if os.path.exists(path):
            preds[gen] = {(r["id"], r["condition"]): r for r in read_jsonl(path)}

    def unscorable(r):
        return r["status"] != "scored" or r.get("n_invalid") == r.get("n_scored")

    def triv(m):           # metrics of the constant "every input affected" predicate on all of T
        pos = m["n_differ"] / m["n_inputs"]
        return {"bal": 1.0 if m["n_differ"] == m["n_inputs"] else 0.5, "f1": 2 * pos / (1 + pos), "acc": pos,
                "exact": int(m["n_differ"] != m["n_inputs"])}
    for gen, by in preds.items():
        gk = GK[gen]
        ids = [i for i in ids_all if (i, "ungrounded") in by and (i, "grounded") in by]
        S[f"pred_{gk}_n"] = len(ids)
        if not ids:
            continue
        ex = lambda i, c: int(not by[(i, c)].get("exact", False))                       # noqa: E731  error
        ba = lambda i, c: 0.5 if unscorable(by[(i, c)]) else float(by[(i, c)]["bal_acc"])  # noqa: E731
        u, g = [ex(i, "ungrounded") for i in ids], [ex(i, "grounded") for i in ids]
        paired(S, f"pred_{gk}_exact", u, g, rng)
        # grounded prompt reveals |Delta|/|T| ("differ on every tested input"): contrast without all-differ functions
        nad = [i for i in ids if mm[i]["n_differ"] != mm[i]["n_inputs"]]
        paired(S, f"pred_{gk}_exact_notalldiffer", [ex(i, "ungrounded") for i in nad],
               [ex(i, "grounded") for i in nad], rng, test=False)
        bu, bg = [ba(i, "ungrounded") for i in ids], [ba(i, "grounded") for i in ids]
        S[f"pred_{gk}_balacc_u"], S[f"pred_{gk}_balacc_u_lo"], S[f"pred_{gk}_balacc_u_hi"] = boot_rate(bu, rng)
        S[f"pred_{gk}_balacc_g"], S[f"pred_{gk}_balacc_g_lo"], S[f"pred_{gk}_balacc_g_hi"] = boot_rate(bg, rng)
        S[f"pred_{gk}_balacc_d"], S[f"pred_{gk}_balacc_d_lo"], S[f"pred_{gk}_balacc_d_hi"] = boot_diff(bu, bg, rng)
        S[f"pred_{gk}_balacc_p"] = float(stats.wilcoxon(bg, bu).pvalue) if any(x != y for x, y in zip(bg, bu)) else 1.0
        T = [triv(mm[i]) for i in ids]
        for k in ("bal", "f1", "acc", "exact"):
            S[f"pred_{gk}_trivial_{k}"] = float(np.mean([t[k] for t in T]))
        S[f"pred_{gk}_trivial_exact_err"] = S[f"pred_{gk}_trivial_exact"]
        for cond in ("ungrounded", "grounded"):
            c0 = cond[0]
            rows = [by[(i, cond)] for i in ids]
            sc = [r for r in rows if not unscorable(r)]
            S[f"pred_{gk}_{c0}_unscorable_n"] = len(rows) - len(sc)
            S[f"pred_{gk}_{c0}_exact_err_scorable"] = float(np.mean([int(not r["exact"]) for r in sc])) if sc else float("nan")
            S[f"pred_{gk}_{c0}_f1"] = float(np.mean([r["f1"] for r in sc])) if sc else float("nan")
            S[f"pred_{gk}_{c0}_acc"] = float(np.mean([(r["tp"] + r["tn"]) / r["n_scored"] for r in sc])) if sc else float("nan")
            lab = Counter(labels.get((gen, i, cond), "unlabelled") for i in ids)
            for L in ("genuine", "dual", "guard", "trivial", "malformed"):
                S[f"pred_{gk}_{c0}_lab_{L}"] = lab.get(L, 0)
                sub = [i for i in ids if labels.get((gen, i, cond)) == L]
                S[f"pred_{gk}_{c0}_lab_{L}_exact_n"] = sum(1 for i in sub if not ex(i, cond))
            gen_ids = [i for i in ids if labels.get((gen, i, cond)) == "genuine"]
            S[f"pred_{gk}_{c0}_exact_err_genuine"] = float(np.mean([ex(i, cond) for i in gen_ids])) if gen_ids else float("nan")
            exact_ids = [i for i in ids if not ex(i, cond)]
            S[f"pred_{gk}_{c0}_exact_n"] = len(exact_ids)
            S[f"pred_{gk}_{c0}_exact_genuine_share"] = (sum(1 for i in exact_ids if labels.get((gen, i, cond)) == "genuine")
                                                        / len(exact_ids)) if exact_ids else float("nan")
            un = [i for i in ids if by[(i, cond)].get("unshown_n_scored")]
            S[f"pred_{gk}_{cond}_exact_err_unshown"] = float(np.mean(
                [int(not by[(i, cond)].get("unshown_exact", False)) for i in un])) if un else float("nan")
            for st in ("narrow", "mid", "broad"):
                sub = [i for i in ids if stratum(mm[i]) == st]
                S[f"pred_{gk}_n_{st}"] = len(sub)
                S[f"pred_{gk}_{cond}_exact_err_{st}"] = float(np.mean([ex(i, cond) for i in sub])) if sub else float("nan")
                S[f"pred_{gk}_{cond}_balacc_{st}"] = float(np.mean([ba(i, cond) for i in sub])) if sub else float("nan")
                pred_rows.append({"generator": gen, "condition": cond, "stratum": st, "n": len(sub),
                                  "exact_err": f"{S[f'pred_{gk}_{cond}_exact_err_{st}']:.4f}",
                                  "bal_acc": f"{S[f'pred_{gk}_{cond}_balacc_{st}']:.4f}"})
            for op in OPERATORS:
                sub = [i for i in ids if mm[i]["op"] == op]
                for r in op_rows:
                    if r["generator"] == gen and r["op"] == op and sub:
                        r[f"pred_{c0}"] = f"{np.mean([ex(i, cond) for i in sub]):.4f}"
                        r["pred_n"] = len(sub)
        if gen == GEN_MODEL and STRONG_MODEL in preds:     # Qwen restricted to Haiku's subset, for comparison
            sub = [i for i in ids if (i, "ungrounded") in preds[STRONG_MODEL]]
            S["pred_gen_on_strong_subset_u"] = float(np.mean([ex(i, "ungrounded") for i in sub])) if sub else float("nan")
            S["pred_gen_on_strong_subset_g"] = float(np.mean([ex(i, "grounded") for i in sub])) if sub else float("nan")
    write_csv("predicates_by_stratum.csv", pred_rows, ["generator", "condition", "stratum", "n", "exact_err", "bal_acc"])
    write_csv("by_operator.csv", op_rows, ["generator", "op", "n", "wit_u", "wit_g", "wit_gs", "pred_n", "pred_u", "pred_g"])

    # ------------------------------------------------------------------ corpus / operator table
    rows = []
    for op in OPERATORS:
        sub = [m for m in mutants if m["op"] == op]
        if not sub:
            continue
        rows.append({"op": op, "label": OP_LABEL[op], "n": len(sub),
                     "n_he": sum(1 for m in sub if m["source"] == "HumanEval+"),
                     "n_mbpp": sum(1 for m in sub if m["source"] == "MBPP+"),
                     "median_diff_frac": f"{np.median([m['n_differ']/m['n_inputs'] for m in sub]):.2f}",
                     "raise_mostly": sum(1 for m in sub if raises_mostly(m))})
    rows.append({"op": "ALL", "label": "all", "n": len(mutants), "n_he": S["n_humaneval"], "n_mbpp": S["n_mbpp"],
                 "median_diff_frac": f"{S['median_differing_fraction']:.2f}", "raise_mostly": S["n_mutants_raise_mostly"]})
    write_csv("corpus_summary.csv", rows, ["op", "label", "n", "n_he", "n_mbpp", "median_diff_frac", "raise_mostly"])

    # ------------------------------------------------------------------ judges (descriptive only, no tests)
    judge_rows = []
    for gen, by in scores.items():
        gk = GK[gen]
        ids = [i for i in ids_all if (i, "ungrounded") in by and (i, "grounded") in by]
        for jn, jm in enumerate(JUDGE_MODELS, start=1):
            if not all(jm in by[(i, c)].get("judges", {}) for i in ids for c in ("ungrounded", "grounded")):
                continue
            pairs = [(int(by[(i, c)]["programmatic"]["error"]), int(by[(i, c)]["judges"][jm]["error"]))
                     for c in ("ungrounded", "grounded") for i in ids if by[(i, c)]["programmatic"]["parse_ok"]]
            jj = [b for _, b in pairs]
            valid = [b for a, b in pairs if a == 0]
            invalid = [b for a, b in pairs if a == 1]
            jt = f"j{jn}"
            S[f"{jt}_reject_rate_{gk}"] = float(np.mean(jj))
            S[f"{jt}_reject_valid_{gk}"] = float(np.mean(valid)) if valid else float("nan")
            S[f"{jt}_accept_invalid_{gk}"] = float(np.mean([1 - b for b in invalid])) if invalid else float("nan")
            po, k = kappa(jj, [a for a, _ in pairs])
            S[f"{jt}_prog_agree_{gk}"] = po
            S[f"{jt}_prog_kappa_{gk}"] = k if 0 < np.mean(jj) < 1 else float("nan")    # undefined for a constant rater
            S[f"{jt}_n_{gk}"] = len(pairs)
            for c in ("ungrounded", "grounded"):
                S[f"{jt}_err_{gk}_{c}"] = float(np.mean([int(by[(i, c)]["judges"][jm]["error"]) for i in ids]))
            judge_rows.append({"generator": gen, "judge": jm, "n": len(pairs),
                               "reject_rate": f"{S[f'{jt}_reject_rate_{gk}']:.4f}",
                               "reject_valid": f"{S[f'{jt}_reject_valid_{gk}']:.4f}",
                               "accept_invalid": f"{S[f'{jt}_accept_invalid_{gk}']:.4f}",
                               "pct_agree_prog": f"{po:.4f}", "kappa_prog": f"{S[f'{jt}_prog_kappa_{gk}']:.4f}"})
    write_csv("judges_descriptive.csv", judge_rows, ["generator", "judge", "n", "reject_rate", "reject_valid",
                                                    "accept_invalid", "pct_agree_prog", "kappa_prog"])

    # ------------------------------------------------------------------ probe
    from check import claim_matches
    from probe import pick_inputs
    probe_rows = []
    KINDS = ["DESC", "DESC_MUT", "CF", "CF_CTRL"]
    probes = {}
    for variant, prefix in (("s", "probe_stripped_"), ("d", "probe_")):
        for pm in PROBE_MODELS:
            path = os.path.join(RESULTS, f"{prefix}{tag(pm)}.jsonl")
            if os.path.exists(path):
                probes[(variant, pm)] = {(r["id"], r["kind"]): r for r in read_jsonl(path)}
    for (variant, pm), by in probes.items():
        pk = f"{PK[pm]}{variant}"
        for kind in KINDS:
            for src in ("all", "HumanEval+", "MBPP+"):
                ids = [i for i in ids_all if (i, kind) in by and (src == "all" or mm[i]["source"] == src)]
                if not ids:
                    continue
                sk = "" if src == "all" else "_" + SRC[src]
                acc = [int(by[(i, kind)]["correct"]) for i in ids]
                m, lo, hi = boot_rate(acc, rng)
                S[f"probe_{pk}_{kind}{sk}"], S[f"probe_{pk}_{kind}{sk}_lo"], S[f"probe_{pk}_{kind}{sk}_hi"] = m, lo, hi
                S[f"probe_{pk}_{kind}{sk}_n"] = len(ids)
                probe_rows.append({"variant": "stripped" if variant == "s" else "docstring", "model": pm,
                                   "kind": kind, "source": src, "n": len(ids), "acc": f"{m:.4f}",
                                   "lo": f"{lo:.4f}", "hi": f"{hi:.4f}"})
                if kind in ("CF", "DESC_MUT"):
                    rep = [int(by[(i, kind)]["parse_ok"] and claim_matches(by[(i, kind)]["answer"],
                                                                           pick_inputs(mm[i])[0]["orig"])) for i in ids]
                    S[f"probe_{pk}_{kind}{sk}_reverts"] = float(np.mean(rep))
        # paired contrasts (all functions)
        for a_kind, b_kind in (("DESC", "CF"), ("DESC_MUT", "CF")):
            ids = [i for i in ids_all if (i, a_kind) in by and (i, b_kind) in by]
            if not ids:
                continue
            a = [int(by[(i, a_kind)]["correct"]) for i in ids]
            b = [int(by[(i, b_kind)]["correct"]) for i in ids]
            paired(S, f"probe_{pk}_{a_kind}_vs_{b_kind}", a, b, rng, test=(variant == "s"))
        if variant == "s" and (("s", pm) in probes):
            ctrl = [i for i in ids_all if (i, "CF_CTRL") in by]
            if ctrl:   # CF_CTRL: truth = original output; "over-applies" = answer differs from it
                S[f"probe_{pk}_CF_CTRL_overapply"] = float(np.mean([int(not by[(i, "CF_CTRL")]["correct"]) for i in ctrl]))
                # signal detection: "says the answer changes" = answer differs from P(x)
                # hit = on affected x*, answer != P(x*) (1 - reversion); false alarm = on unaffected x0, answer != P(x0)
                cf_ids = [i for i in ids_all if (i, "CF") in by]
                hit = 1 - float(np.mean([int(by[(i, "CF")]["parse_ok"] and claim_matches(
                    by[(i, "CF")]["answer"], pick_inputs(mm[i])[0]["orig"])) for i in cf_ids]))
                fa = S[f"probe_{pk}_CF_CTRL_overapply"]
                S[f"probe_{pk}_hit"], S[f"probe_{pk}_fa"] = hit, fa
                S[f"probe_{pk}_dprime"] = float(stats.norm.ppf(hit) - stats.norm.ppf(fa))
                # the same comparisons restricted to the functions that have an unaffected input
                S[f"probe_{pk}_CF_on_ctrl"] = float(np.mean([int(by[(i, "CF")]["correct"]) for i in ctrl if (i, "CF") in by]))
                S[f"probe_{pk}_DESC_on_ctrl"] = float(np.mean([int(by[(i, "DESC")]["correct"]) for i in ctrl if (i, "DESC") in by]))
    # docstring ablation: same model, same items, docstring/name present (round 1) vs stripped (round 2)
    for pm in PROBE_MODELS:
        if ("s", pm) in probes and ("d", pm) in probes:
            s_, d_ = probes[("s", pm)], probes[("d", pm)]
            for kind in ("DESC", "DESC_MUT"):
                for src in ("HumanEval+", "MBPP+"):
                    ids = [i for i in ids_all if (i, kind) in s_ and (i, kind) in d_ and mm[i]["source"] == src]
                    if not ids:
                        continue
                    key = f"abl_{PK[pm]}_{kind}_{SRC[src]}"
                    paired(S, key, [int(s_[(i, kind)]["correct"]) for i in ids],
                           [int(d_[(i, kind)]["correct"]) for i in ids], rng,
                           test=(pm == PROBE_MODELS[0] and kind == "DESC_MUT" and src == "HumanEval+"))
            pres = [r.get("strip_behaviour_preserved") for r in s_.values()]
            S[f"strip_preserved_{PK[pm]}"] = float(np.mean([bool(x) for x in pres])) if pres else float("nan")
    write_csv("probe.csv", probe_rows, ["variant", "model", "kind", "source", "n", "acc", "lo", "hi"])

    # ------------------------------------------------------------------ Holm across the reported tests
    names = sorted(TESTS, key=lambda k: TESTS[k])
    m_ = len(names)
    running = 0.0
    for rank, k in enumerate(names):
        adj = min(1.0, (m_ - rank) * TESTS[k])
        running = max(running, adj)
        S[f"{k}_p_holm"] = running
    S["holm_family_size"] = m_
    S["holm_family"] = names
    write_csv("tests_holm.csv", [{"test": k, "p": f"{TESTS[k]:.6g}", "p_holm": f"{S[k + '_p_holm']:.6g}"} for k in names],
              ["test", "p", "p_holm"])

    # ------------------------------------------------------------------ planned-study eligibility (materials only)
    if os.path.exists(hp):
        Hm = {h["id"]: h for h in read_jsonl(hp) if h.get("op") and h["unaffected_inputs"]}

        def certified(i, need_genuine):
            for gen, by in preds.items():
                r = by.get((i, "grounded"))
                if r and r.get("exact") and (not need_genuine or labels.get((gen, i, "grounded")) == "genuine"):
                    return True
            return False
        base = [i for i in ids_all if i in Hm and stratum(mm[i]) != "broad"]
        S["n_eligible_mixed_nonbroad"] = len(base)
        S["n_eligible_certified"] = sum(1 for i in base if certified(i, False))
        S["n_eligible_certified_genuine"] = sum(1 for i in base if certified(i, True))
        S["n_eligible_certified_genuine_anybreadth"] = sum(1 for i in ids_all if i in Hm and certified(i, True))

    # ------------------------------------------------------------------ bookkeeping
    S["models"] = {"generator": GEN_MODEL, "strong": STRONG_MODEL, "judges": JUDGE_MODELS, "probe": PROBE_MODELS}
    cache = sorted(os.listdir(os.path.join(RESULTS, "llm_cache")))
    S["llm_cache_files"] = len(cache)
    counts = Counter()
    for f in cache:
        with open(os.path.join(RESULTS, "llm_cache", f)) as fh:
            counts[json.load(fh)["model"]] += 1
    S["llm_calls"] = dict(sorted(counts.items()))
    S["llm_calls_strong"] = counts.get(STRONG_MODEL, 0)
    S["llm_calls_local"] = sum(v for k, v in counts.items() if k != STRONG_MODEL)
    S["note"] = ("All LLM outputs are real model responses (local Ollama models at temperature 0 with fixed seed; "
                 "claude-haiku-5-5 via the Anthropic API at default sampling, one sample per item), cached on disk. "
                 "The probe uses models as stand-ins; it is NOT human data. H2-H3 are a planned protocol only.")
    with open(os.path.join(RESULTS, "summary.json"), "w") as f:
        json.dump(S, f, indent=1, sort_keys=True, default=float)
    for k in sorted(S):
        if k.endswith("_p_holm"):
            print(f"{k:45s} p={S[k[:-5]]:.3g} holm={S[k]:.3g}")


if __name__ == "__main__":
    main()
