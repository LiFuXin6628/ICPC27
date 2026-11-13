"""AST-based semantic mutation operators. Each operator enumerates candidate sites in the entry
function; applying a candidate returns the mutated source plus a human-readable description of the
intervention (used both for the diff shown to models and for the counterfactual probe questions).

Operators (one mutant per function is selected downstream):
  NEG_GUARD    negate the condition of an `if` / `elif` / `while`
  DEL_GUARD    remove an `if` whose body is an early exit (return / raise / continue / break)
  CMP_OP       change a comparison operator (< <-> <=, > <-> >=, == <-> !=)
  DEF_ARG      change a default argument constant
  ARITH_OP     swap an arithmetic operator (+ <-> -, * <-> //, % -> //, / -> *, ** -> *)
  BOUND_CONST  change an integer constant appearing in a comparison, range(), or slice by +-1
"""
import ast
import copy
import difflib

OPERATORS = ["NEG_GUARD", "DEL_GUARD", "CMP_OP", "DEF_ARG", "ARITH_OP", "BOUND_CONST"]

_CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
             ast.NotEq: ast.Eq}
_CMP_TXT = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}
_ARITH_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult,
               ast.Mod: ast.FloorDiv, ast.Div: ast.Mult, ast.Pow: ast.Mult}
_ARITH_TXT = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.FloorDiv: "//", ast.Mod: "%", ast.Div: "/",
              ast.Pow: "**"}


def _find_func(tree, entry_point):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == entry_point:
            return node
    return None


def _is_early_exit(body):
    return len(body) == 1 and isinstance(body[0], (ast.Return, ast.Raise, ast.Continue, ast.Break))


def _in_cmp_range_slice(func):
    """Yield (parent_kind, Constant node) for integer constants used in comparisons/range()/slices."""
    for node in ast.walk(func):
        if isinstance(node, ast.Compare):
            for c in [node.left] + node.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, int) and not isinstance(c.value, bool):
                    yield "comparison", c
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, int) and not isinstance(a.value, bool):
                    yield "range()", a
                if isinstance(a, ast.BinOp) and isinstance(a.right, ast.Constant) and \
                        isinstance(a.right.value, int) and not isinstance(a.right.value, bool):
                    yield "range()", a.right
        elif isinstance(node, ast.Slice):
            for a in (node.lower, node.upper, node.step):
                if isinstance(a, ast.Constant) and isinstance(a.value, int) and not isinstance(a.value, bool):
                    yield "slice", a


def enumerate_candidates(program, entry_point):
    """Return a list of candidate dicts {op, site, line, label}; `site` is an index into a
    deterministic AST walk so that `apply` can relocate the node in a fresh copy."""
    tree = ast.parse(program)
    func = _find_func(tree, entry_point)
    if func is None:
        return []
    cands = []
    nodes = list(ast.walk(func))
    index = {id(n): i for i, n in enumerate(nodes)}

    for n in nodes:
        if isinstance(n, (ast.If, ast.While)):
            cands.append({"op": "NEG_GUARD", "site": index[id(n)], "line": n.test.lineno,
                          "label": f"negate the condition `{ast.unparse(n.test)}`"})
        if isinstance(n, ast.If) and _is_early_exit(n.body) and not n.orelse:
            cands.append({"op": "DEL_GUARD", "site": index[id(n)], "line": n.lineno,
                          "label": f"remove the check `if {ast.unparse(n.test)}: {ast.unparse(n.body[0])}`"})
        if isinstance(n, ast.Compare):
            for k, op in enumerate(n.ops):
                if type(op) in _CMP_SWAP:
                    cands.append({"op": "CMP_OP", "site": index[id(n)], "k": k, "line": n.lineno,
                                  "label": f"change `{_CMP_TXT[type(op)]}` to `{_CMP_TXT[_CMP_SWAP[type(op)]]}` in "
                                           f"`{ast.unparse(n)}`"})
        if isinstance(n, ast.BinOp) and type(n.op) in _ARITH_SWAP:
            cands.append({"op": "ARITH_OP", "site": index[id(n)], "line": n.lineno,
                          "label": f"change `{_ARITH_TXT[type(n.op)]}` to `{_ARITH_TXT[_ARITH_SWAP[type(n.op)]]}` in "
                                   f"`{ast.unparse(n)}`"})
    # default arguments of the entry function
    for d in func.args.defaults + [d for d in func.args.kw_defaults if d is not None]:
        if isinstance(d, ast.Constant) and isinstance(d.value, (int, float, bool, str)) and d.value is not None:
            cands.append({"op": "DEF_ARG", "site": index[id(d)], "line": d.lineno,
                          "label": f"change the default argument `{ast.unparse(d)}`"})
    seen = set()
    for kind, c in _in_cmp_range_slice(func):
        if id(c) in seen:
            continue
        seen.add(id(c))
        cands.append({"op": "BOUND_CONST", "site": index[id(c)], "line": c.lineno,
                      "label": f"change the constant `{c.value}` in a {kind} by one"})
    return cands


def _new_default(v, direction):
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        return v + direction
    if isinstance(v, float):
        return v + direction * 1.0 if v != 0 else 1.0
    if isinstance(v, str):
        return "" if v else " "
    return v


def apply(program, entry_point, cand, direction=1):
    """Return (mutant_source, intervention_text, unified_diff) for a candidate."""
    tree = ast.parse(program)
    func = _find_func(tree, entry_point)
    nodes = list(ast.walk(func))
    n = nodes[cand["site"]]
    op = cand["op"]
    text = cand["label"]
    if op == "NEG_GUARD":
        n.test = ast.UnaryOp(op=ast.Not(), operand=n.test)
    elif op == "DEL_GUARD":
        # replace the If with `pass` where it appears in its parent's body
        parent = _parent_of(func, n)
        for field in ("body", "orelse", "finalbody"):
            lst = getattr(parent, field, None)
            if isinstance(lst, list) and n in lst:
                i = lst.index(n)
                lst[i] = ast.Pass() if len(lst) == 1 else None
                if lst[i] is None:
                    del lst[i]
                break
    elif op == "CMP_OP":
        k = cand["k"]
        n.ops[k] = _CMP_SWAP[type(n.ops[k])]()
    elif op == "ARITH_OP":
        n.op = _ARITH_SWAP[type(n.op)]()
    elif op == "DEF_ARG":
        new = _new_default(n.value, direction)
        text = f"change the default argument `{n.value!r}` to `{new!r}`"
        n.value = new
    elif op == "BOUND_CONST":
        new = n.value + direction
        text = f"change the constant `{n.value}` to `{new}` on line {n.lineno}"
        n.value = new
    else:
        raise ValueError(op)
    ast.fix_missing_locations(tree)
    mutant = ast.unparse(tree) + "\n"
    orig_norm = ast.unparse(ast.parse(program)) + "\n"
    diff = "".join(difflib.unified_diff(orig_norm.splitlines(True), mutant.splitlines(True),
                                        "original", "mutant", n=2))
    return mutant, text, diff, orig_norm


def _parent_of(root, target):
    for node in ast.walk(root):
        for child in ast.iter_child_nodes(node):
            if child is target:
                return node
    return None
