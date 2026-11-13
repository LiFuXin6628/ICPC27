"""Prompt construction shared by explanation generation, checking, and the model-side probe."""
import ast
import json
import os
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import outcome_str, try_literal  # noqa: E402

SYSTEM_JSON = ("You are a precise program-comprehension assistant. You answer with exactly one JSON object "
               "and no other text.")

K_DIFF_SHOWN = 3      # differing examples shown in the grounded condition
K_AGREE_SHOWN = 2     # agreeing examples shown in the grounded condition
K_DIFF_JUDGE = 6
K_AGREE_JUDGE = 3


def shortest(examples, k):
    return sorted(examples, key=lambda e: (len(e["input"]), e["input"]))[:k]


def evidence_block(rec, k_diff=K_DIFF_SHOWN, k_agree=K_AGREE_SHOWN):
    lines = [f"Execution evidence: ORIGINAL and MUTANT were run on {rec['n_inputs']} test inputs; "
             f"their results differ on {rec['n_differ']} of them.",
             "Differing inputs (positional arguments -> ORIGINAL result | MUTANT result):"]
    for e in shortest(rec["differing"], k_diff):
        lines.append(f"  {e['input']} -> {outcome_str(e['orig'])} | {outcome_str(e['mut'])}")
    if rec["agreeing_examples"]:
        lines.append("Inputs on which both give the same result (positional arguments -> result):")
        for e in shortest(rec["agreeing_examples"], k_agree):
            lines.append(f"  {e['input']} -> {outcome_str(e['orig'])}")
    else:
        lines.append("Both versions differ on every tested input.")
    return "\n".join(lines)


def shown_inputs(rec, k_diff=K_DIFF_SHOWN, k_agree=K_AGREE_SHOWN):
    return [e["input"] for e in shortest(rec["differing"], k_diff)] + \
           [e["input"] for e in shortest(rec["agreeing_examples"], k_agree)]


def explain_prompt(rec, grounded):
    parts = ["ORIGINAL Python function:", "```python", rec["program"].rstrip(), "```",
             "A single edit produces the MUTANT. Unified diff (ORIGINAL -> MUTANT):", "```diff",
             rec["diff"].rstrip(), "```"]
    if grounded:
        parts += ["", evidence_block(rec)]
    witness_rule = (" It must be a NEW input that does not appear in the evidence above." if grounded else "")
    parts += ["",
              "Task: explain how the MUTANT's behaviour differs from the ORIGINAL's. Respond with exactly one JSON "
              "object with these keys:",
              '- "affected_inputs": a precise description of which inputs behave differently (and which do not);',
              '- "difference": how the result changes for those inputs, stated as ORIGINAL -> MUTANT '
              "(return value or raised exception);",
              '- "witness_input": a JSON list of the positional argument values of ONE input on which ORIGINAL and '
              f"MUTANT give different results.{witness_rule}",
              '- "original_output": ORIGINAL\'s return value on witness_input as a JSON value, or the string '
              '"raises <ExceptionName>";',
              '- "mutant_output": the same for MUTANT.',
              "Use JSON syntax (true/false/null, double quotes, lists for tuples). No text outside the JSON object."]
    return "\n".join(parts)


def judge_prompt(rec, affected_inputs, difference):
    ev = evidence_block(rec, K_DIFF_JUDGE, K_AGREE_JUDGE)
    return "\n".join([
        "You are grading an explanation of how a one-line code change alters a Python function's behaviour.",
        "ORIGINAL function:", "```python", rec["program"].rstrip(), "```",
        "Change (ORIGINAL -> MUTANT):", "```diff", rec["diff"].rstrip(), "```",
        "GROUND TRUTH from executing both versions:", ev, "",
        "EXPLANATION under review:",
        f"  affected_inputs: {json.dumps(affected_inputs)}",
        f"  difference: {json.dumps(difference)}", "",
        "Grade the explanation against the ground truth only. Respond with exactly one JSON object:",
        '{"affected_inputs_correct": true/false  (does it correctly characterise which inputs change behaviour?),',
        ' "difference_correct": true/false  (does it correctly state how the result changes, ORIGINAL -> MUTANT, '
        "including the direction and any exception?),",
        ' "false_claim": true/false  (does it assert any behaviour that the ground truth contradicts?),',
        ' "rationale": "<one sentence>"}',
    ])


def call_str(entry_point, input_repr):
    ok, args = try_literal(input_repr)
    if ok and isinstance(args, (list, tuple)):
        return f"{entry_point}({', '.join(repr(a) for a in args)})"
    return f"{entry_point}(*{input_repr})"


def n_params(program, entry_point):
    tree = ast.parse(program)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == entry_point:
            return len(n.args.args) + len(n.args.kwonlyargs), n.args.vararg is not None
    return None, False


def probe_prompt(rec, kind, input_repr):
    """kind in {'DESC', 'CF', 'CF_CTRL', 'DESC_MUT'}."""
    call = call_str(rec["entry_point"], input_repr)
    if kind in ("DESC",):
        code, question = rec["program"], f"What does `{call}` return?"
    elif kind == "DESC_MUT":
        code, question = rec["mutant"], f"What does `{call}` return?"
    else:
        code = rec["program"]
        question = (f"Suppose a developer makes exactly one change to this function: {rec['intervention']} "
                    f"(line {rec['line']}). The diff is:\n```diff\n{rec['diff'].rstrip()}\n```\n"
                    f"Nothing else changes. What would the MODIFIED function return for `{call}`?")
    return "\n".join([
        "Python function:", "```python", code.rstrip(), "```", question,
        'Answer with exactly one JSON object: {"output": <the return value as a JSON value (lists for tuples), '
        'or the string "raises <ExceptionName>" if it raises>}. No other text.'])


def probe_prompt_stripped(so, sm, diff, line, kind, input_repr):
    """Round-2 probe: code without docstrings/comments, entry renamed to `f`; the edit is located by the line
    number in the code actually shown (round 1 cited raw-source line numbers, wrong for 84/129 prompts)."""
    call = call_str("f", input_repr)
    if kind == "DESC":
        code, question = so, f"What does `{call}` return?"
    elif kind == "DESC_MUT":
        code, question = sm, f"What does `{call}` return?"
    else:  # CF, CF_CTRL
        code = so
        question = (f"Suppose a developer makes exactly one change to this function, at line {line} of the code "
                    f"above. The diff is:\n```diff\n{diff.rstrip()}\n```\n"
                    f"Nothing else changes. What would the MODIFIED function return for `{call}`?")
    return "\n".join([
        "Python function:", "```python", code.rstrip(), "```", question,
        'Answer with exactly one JSON object: {"output": <the return value as a JSON value (lists for tuples), '
        'or the string "raises <ExceptionName>" if it raises>}. No other text.'])


def predicate_prompt(rec, grounded, signature):
    parts = ["ORIGINAL Python function:", "```python", rec["program"].rstrip(), "```",
             "A single edit produces the MUTANT. Unified diff (ORIGINAL -> MUTANT):", "```diff",
             rec["diff"].rstrip(), "```"]
    if grounded:
        parts += ["", evidence_block(rec)]
    parts += ["",
              "Task: characterise exactly which inputs the edit affects. Write a Python function",
              f"    def affected{signature} -> bool:",
              "that returns True if and only if ORIGINAL and MUTANT give different results (a different return value, "
              "or one raises and the other does not, or they raise different exceptions) on these arguments.",
              "Express the condition directly on the arguments. Do NOT copy, call or re-implement ORIGINAL or MUTANT "
              "and compare their results. Use at most 12 lines, standard library only, no imports of os/sys/"
              "subprocess, no file or network access.",
              "Answer with one ```python code block containing only the function `affected`."]
    return "\n".join(parts)
