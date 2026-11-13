"""Round-2 probe materials: remove the specification cues from a program.
strip_cues() deletes every docstring (module, function, class), drops comments (ast.unparse does), and renames the
entry function -- and recursive references to it -- to the neutral name `f`. Applied identically to ORIGINAL and
MUTANT, so HumanEval+ mutants no longer carry a docstring (with doctests) that describes the ORIGINAL's behaviour."""
import ast
import difflib

NEUTRAL = "f"


class _Rename(ast.NodeTransformer):
    def __init__(self, old):
        self.old = old

    def visit_FunctionDef(self, node):
        if node.name == self.old:
            node.name = NEUTRAL
        self.generic_visit(node)
        return node

    def visit_Name(self, node):
        if node.id == self.old:
            node.id = NEUTRAL
        return node


def _drop_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                del body[0]
                if not body and not isinstance(node, ast.Module):
                    body.append(ast.Pass())
    return tree


def strip_cues(program, entry_point):
    tree = ast.parse(program)
    if any(isinstance(n, ast.Name) and n.id == NEUTRAL for n in ast.walk(tree)) or \
            any(isinstance(n, ast.arg) and n.arg == NEUTRAL for n in ast.walk(tree)):
        raise ValueError("name clash with neutral name")
    tree = _Rename(entry_point).visit(_drop_docstrings(tree))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def stripped_pair(rec):
    """(stripped original, stripped mutant, unified diff, 1-based changed line in the stripped original)."""
    so, sm = strip_cues(rec["program"], rec["entry_point"]), strip_cues(rec["mutant"], rec["entry_point"])
    diff = "".join(difflib.unified_diff(so.splitlines(True), sm.splitlines(True), "original", "modified", n=2))
    la, lb = so.splitlines(), sm.splitlines()
    line = next((i + 1 for i, (x, y) in enumerate(zip(la, lb)) if x != y), min(len(la), len(lb)) + 1)
    return so, sm, diff, line
