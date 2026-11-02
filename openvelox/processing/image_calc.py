"""Two-image calculator (add / subtract / multiply / divide / invert / normalize)."""

from __future__ import annotations

from typing import Literal

import numpy as np

Op = Literal["add", "sub", "mul", "div", "invert", "normalize"]


def _match(a: np.ndarray, b: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None]:
    aa = np.asarray(a, dtype=np.float64)
    if b is None:
        return aa, None
    bb = np.asarray(b, dtype=np.float64)
    if aa.shape != bb.shape:
        raise ValueError(f"Shape mismatch: {aa.shape} vs {bb.shape}")
    return aa, bb


def image_calculate(op: Op, a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    aa, bb = _match(a, b)
    if op == "add":
        if bb is None:
            raise ValueError("add requires two images")
        return aa + bb
    if op == "sub":
        if bb is None:
            raise ValueError("sub requires two images")
        return aa - bb
    if op == "mul":
        if bb is None:
            raise ValueError("mul requires two images")
        return aa * bb
    if op == "div":
        if bb is None:
            raise ValueError("div requires two images")
        return aa / np.where(np.abs(bb) < 1e-12, np.nan, bb)
    if op == "invert":
        return aa.max() - aa
    if op == "normalize":
        lo, hi = float(np.nanmin(aa)), float(np.nanmax(aa))
        if hi <= lo:
            return np.zeros_like(aa)
        return (aa - lo) / (hi - lo)
    raise ValueError(f"Unknown op {op}")
