"""Stage 1: download HumanEval+ and MBPP+ (EvalPlus) from Hugging Face and build the corpus.
Each record: id, source, entry_point, program (canonical solution), inputs (argument lists),
set_compare flag (MBPP+ tasks whose oracle compares as sets). Stored under artifact/data/."""
import ast
import json
import os
import random
import re
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, N_PER_SOURCE, MAX_INPUTS, SEED, safe_literal, write_jsonl  # noqa: E402


# Hugging Face dataset revisions (commit SHAs) pinned on 2026-11-10; rebuilding from them reproduces data/corpus.jsonl.
REVISIONS = {"evalplus/humanevalplus": "d32357cf319e50e9c8d8dab5ea876c72b0fd321b",
             "evalplus/mbppplus": "b2d74c91837c3f2a20c1299ae98133cbe7cfa077"}


def _extract_inputs(test_src):
    m = re.search(r"^\s*inputs\s*=\s*(.*)$", test_src, re.M)
    if not m:
        return None
    return safe_literal(m.group(1))


def _program_humaneval(r):
    return r["prompt"].rstrip("\n") + "\n" + r["canonical_solution"].rstrip() + "\n"


def _program_mbpp(r):
    imports = "\n".join(r.get("test_imports") or [])
    code = r["code"].strip("\n")
    return (imports + "\n\n" if imports else "") + code + "\n"


def _entry_point_mbpp(r):
    # the test harness calls `<name>(*inp)`; find that name
    m = re.search(r"assertion\((\w+)\(\*inp\)", r["test"])
    if m:
        return m.group(1)
    tree = ast.parse(r["code"])
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    return names[-1] if names else None


def _sample_inputs(inputs, rng):
    if len(inputs) <= MAX_INPUTS:
        return inputs
    head = inputs[:30]
    tail = rng.sample(inputs[30:], MAX_INPUTS - 30)
    return head + tail


def main():
    from datasets import load_dataset
    os.makedirs(DATA, exist_ok=True)
    rng = random.Random(SEED)
    corpus, dropped = [], []
    for source, hf_name in (("HumanEval+", "evalplus/humanevalplus"), ("MBPP+", "evalplus/mbppplus")):
        ds = load_dataset(hf_name, split="test", revision=REVISIONS[hf_name])
        rows = list(ds)
        rows.sort(key=lambda r: str(r["task_id"]))
        rng_src = random.Random(f"{SEED}-{source}")
        rng_src.shuffle(rows)
        taken = 0
        for r in rows:
            if taken >= N_PER_SOURCE:
                break
            try:
                inputs = _extract_inputs(r["test"])
                if inputs is None or len(inputs) < 5:
                    dropped.append((source, r["task_id"], "no inputs"))
                    continue
                if source == "HumanEval+":
                    program, entry = _program_humaneval(r), r["entry_point"]
                else:
                    program, entry = _program_mbpp(r), _entry_point_mbpp(r)
                ast.parse(program)
                if entry is None:
                    dropped.append((source, r["task_id"], "no entry point"))
                    continue
                set_compare = "out = set(out)" in r["test"]
                inputs = _sample_inputs([list(i) for i in inputs], rng)
                corpus.append({
                    "id": f"{source.replace('+', 'P')}/{r['task_id']}".replace("HumanEval/", ""),
                    "source": source, "task_id": str(r["task_id"]), "entry_point": entry,
                    "program": program, "inputs_repr": [repr(i) for i in inputs],
                    "n_inputs_total": len(_extract_inputs(r["test"])), "set_compare": set_compare,
                    "description": (r["prompt"] if source == "MBPP+" else "")})
                taken += 1
            except Exception as e:  # unparsable inputs etc.
                dropped.append((source, r["task_id"], f"{type(e).__name__}: {e}"[:80]))
    write_jsonl(os.path.join(DATA, "corpus.jsonl"), corpus)
    with open(os.path.join(DATA, "corpus_dropped.json"), "w") as f:
        json.dump(dropped, f, indent=1)
    by_src = {}
    for c in corpus:
        by_src[c["source"]] = by_src.get(c["source"], 0) + 1
    print(f"corpus: {len(corpus)} functions {by_src}; dropped {len(dropped)}")


if __name__ == "__main__":
    main()
