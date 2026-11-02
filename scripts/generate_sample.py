#!/usr/bin/env python3
"""Generate the synthetic Velox-style .emd used for demos and tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openvelox.io.synthetic import write_synthetic_emd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        default=str(ROOT / "samples" / "synthetic_velox.emd"),
        help="Output .emd path",
    )
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    path = write_synthetic_emd(args.output, seed=args.seed)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
