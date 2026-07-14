#!/usr/bin/env python3
"""Validate and normalize Find First Customers report JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from report_model import ReportValidationError, audit_report, load_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input analysis JSON")
    parser.add_argument(
        "--normalized",
        type=Path,
        help="Optional path for validated JSON with calculated scores and stable ordering",
    )
    args = parser.parse_args()

    try:
        result = audit_report(load_json(args.input))
    except ReportValidationError as error:
        print(error, file=sys.stderr)
        return 1

    for issue in result.issues:
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(issue, file=stream)

    if result.errors:
        print(f"Validation failed with {len(result.errors)} error(s).", file=sys.stderr)
        return 1

    if args.normalized:
        write_json(args.normalized, result.data)
        print(f"Normalized report: {args.normalized.resolve()}")

    print(
        f"Report is valid: {len(result.data.get('prospects', []))} prospect(s), "
        f"{len(result.warnings)} warning(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

