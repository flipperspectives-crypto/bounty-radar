"""CLI: python -m bands_compare --baseline --sensitivity

Research-only. Refuses BANDS_COMPARE_LIVE=1.
"""

from __future__ import annotations

import argparse
import sys

from .schemas import assert_research_only
from .simulate import write_reports


def main(argv: list[str] | None = None) -> int:
    assert_research_only()
    parser = argparse.ArgumentParser(
        description="DLMM / Mr Bands comparator (simulation only, no live funds)"
    )
    parser.add_argument("--baseline", action="store_true", help="Run baseline weights and write reports")
    parser.add_argument("--sensitivity", action="store_true", help="Include weight sensitivity CSV")
    parser.add_argument("--out-dir", default=None, help="Report directory (default: reports/)")
    args = parser.parse_args(argv)

    if not args.baseline and not args.sensitivity:
        args.baseline = True
        args.sensitivity = True

    paths = write_reports(out_dir=args.out_dir)
    print("bands_compare: simulation complete (no live funds, no signatures)")
    for key, path in paths.items():
        print(f"  {key}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
