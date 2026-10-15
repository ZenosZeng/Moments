from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import (
    DEFAULT_SOURCE_PARENT,
    DEFAULT_SOURCE_PREFIX,
    analyze_archive,
    find_source_root,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze a monthly photo archive and generate daily-count charts."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Exact source archive path. By default, find the unique directory "
            f"starting with {DEFAULT_SOURCE_PREFIX!r} under {DEFAULT_SOURCE_PARENT}."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/photo_timeline"),
        help="Report output directory",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("data/db/photo_index.sqlite3"),
        help="Incremental SQLite index path",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached metadata and rescan every photo",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = args.source.resolve() if args.source else find_source_root()
    print(f"Source: {source_root}")
    result = analyze_archive(
        source_root=source_root,
        output_root=args.output,
        index_path=args.index,
        refresh=args.refresh,
    )
    print(f"Photos: {result['photo_count']}")
    print(f"Included photos: {result['included_count']}")
    print(f"Excluded missing dates: {result['missing_date_count']}")
    print(f"Month mismatches: {result['mismatch_count']}")
    print(f"Extraction errors: {result['error_count']}")
    print(f"Charts: {result['chart_count']}")
    print(f"Report: {result['report_path']}")
    return 0
