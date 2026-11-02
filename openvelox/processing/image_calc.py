"""Image calculator: named ops and safe arithmetic expressions."""

from __future__ import annotations

import ast
from typing import Literal

import numpy as np

Op = Literal["add", "sub", "mul", "div", "invert", "normalize"]

_NAMED_OPS = {"add", "sub", "mul", "div", "invert", "normalize"}
_FUNCS = {
    "abs": np.abs,
    "log": np.log,
    "log10": np.log10,
    "sqrt": np.sqrt,
    "exp": np.exp,
}


def _match(a: np.ndarray, b: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None]:
    aa = np.asarray(a, dtype=np.float64)
    if b is None:
        return aa, None
    bb = np.asarray(b, dtype=np.float64)
    if aa.shape != bb.shape:
        raise ValueError(f"Shape mismatch: {aa.shape} vs {bb.shape}")
    return aa, bb


def _safe_div(num: np.ndarray, den: np.ndarray | float) -> np.ndarray:
    den_arr = np.asarray(den, dtype=np.float64)
    safe = np.where(np.abs(den_arr) < 1e-12, np.nan, den_arr)
    return np.asarray(num, dtype=np.float64) / safe


def image_calculate(op: Op | str, a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    """Named op or an expression such as ``A/(A+B)`` / ``abs(A-B)``."""
    name = str(op or "add").strip()
    if name not in _NAMED_OPS:
        return evaluate_expression(name, a, b)
    aa, bb = _match(a, b)
    if name == "add":
        if bb is None:
            raise ValueError("add requires two images")
        return aa + bb
    if name == "sub":
        if bb is None:
            raise ValueError("sub requires two images")
        return aa - bb
    if name == "mul":
        if bb is None:
            raise ValueError("mul requires two images")
        return aa * bb
    if name == "div":
        if bb is None:
            raise ValueError("div requires two images")
        return _safe_div(aa, bb)
    if name == "invert":
        return aa.max() - aa
    if name == "normalize":
        lo, hi = float(np.nanmin(aa)), float(np.nanmax(aa))
        if hi <= lo:
            return np.zeros_like(aa)
        return (aa - lo) / (hi - lo)
    raise ValueError(f"Unknown op {op}")


def evaluate_expression(
    expr: str,
    a: np.ndarray,
    b: np.ndarray | None = None,
) -> np.ndarray:
    """Evaluate a restricted expression over images A and B.

    Allowed: ``+ - * / **``, constants, ``abs``, ``log``, ``log10``, ``sqrt``,
    ``exp``. Division is safe (zeros → NaN). Shapes must match when B is used.
    """
    text = str(expr or "").strip()
    if not text:
        raise ValueError("Empty expression")
    if text in _NAMED_OPS:
        return image_calculate(text, a, b)
    aa, bb = _match(a, b)
    env = {"A": aa, "a": aa}
    if bb is not None:
        env["B"] = bb
        env["b"] = bb
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {text}") from exc
    return np.asarray(_eval_node(tree.body, env), dtype=np.float64)


def _eval_node(node: ast.AST, env: dict[str, np.ndarray]) -> np.ndarray | float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError("Only numeric constants are allowed")
    if isinstance(node, ast.UnaryOp):
        val = _eval_node(node.operand, env)
        if isinstance(node.op, ast.UAdd):
            return val
        if isinstance(node.op, ast.USub):
            return -np.asarray(val)
        raise ValueError("Unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return np.asarray(left) + np.asarray(right)
        if isinstance(node.op, ast.Sub):
            return np.asarray(left) - np.asarray(right)
        if isinstance(node.op, ast.Mult):
            return np.asarray(left) * np.asarray(right)
        if isinstance(node.op, ast.Div):
            return _safe_div(np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64))
        if isinstance(node.op, ast.Pow):
            return np.asarray(left, dtype=np.float64) ** np.asarray(right, dtype=np.float64)
        raise ValueError("Unsupported operator")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"Unknown name {node.id!r} — use A and B")
        return env[node.id]
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("Allowed functions: abs, log, log10, sqrt, exp")
        if node.keywords:
            raise ValueError("Keyword arguments are not allowed")
        args = [_eval_node(arg, env) for arg in node.args]
        result = _FUNCS[node.func.id](*args)
        return np.asarray(result, dtype=np.float64)
    raise ValueError("Unsupported expression")
