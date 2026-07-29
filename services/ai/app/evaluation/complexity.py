"""Time-complexity classifier (Phase 2 Slice 7, see
docs/design-ai-evaluation.md). Pure, no LLM call, no I/O. Python gets real
AST analysis; Java/C++ get a basic brace-nesting heuristic since there's no
AST available for them here — deliberately simple, per the slice's own
"basic heuristics for Java/C++" scope.
"""

import ast
import re

_SORT_CALL_RE = re.compile(r"\bsort\(|\bsorted\(")
_LOOP_OR_BRACE_RE = re.compile(r"\bfor\b|\bwhile\b|\{|\}")


def classify(language: str, source: str) -> str:
    if language == "python":
        return _classify_python(source)
    return _classify_brace_heuristic(source)


def _classify_python(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "unknown"

    depth = _max_loop_depth(tree)
    if depth == 0:
        return "O(2^n)" if _has_self_recursion(tree) else "O(1)"
    if depth == 1:
        return "O(n log n)" if _SORT_CALL_RE.search(source) else "O(n)"
    if depth == 2:
        return "O(n^2)"
    return f"O(n^{depth})"


def _max_loop_depth(node: ast.AST, depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.For | ast.While):
            best = max(best, _max_loop_depth(child, depth + 1))
        else:
            best = max(best, _max_loop_depth(child, depth))
    return best


def _has_self_recursion(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == node.name
            ):
                return True
    return False


def _classify_brace_heuristic(source: str) -> str:
    """Java/C++: no AST available, so track brace-scope depth and mark a
    scope as a loop scope if a `for`/`while` keyword preceded the `{` that
    opened it — the nesting depth is the max number of loop scopes
    simultaneously open."""
    depth_stack: list[bool] = []
    pending_loop = False
    max_depth = 0
    for match in _LOOP_OR_BRACE_RE.finditer(source):
        token = match.group()
        if token in ("for", "while"):
            pending_loop = True
        elif token == "{":
            depth_stack.append(pending_loop)
            pending_loop = False
            max_depth = max(max_depth, sum(depth_stack))
        elif token == "}" and depth_stack:
            depth_stack.pop()

    if max_depth == 0:
        return "O(1)"
    if max_depth == 1:
        return "O(n)"
    if max_depth == 2:
        return "O(n^2)"
    return f"O(n^{max_depth})"
