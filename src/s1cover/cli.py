"""Command-line interface for s1cover."""

import argparse
import sys
from datetime import date
from pathlib import Path

from .query import QueryError, aoi_options, search_tracks
from .report import render_report, write_report


def iso_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("use a date in YYYY-MM-DD format")


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("use a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s1cover",
        description="Summarize Sentinel-1 SLC scenes by track, imaging mode and polarization.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check", help="Search for scenes intersecting a bbox or GeoJSON AOI"
    )
    aoi = check.add_mutually_exclusive_group(required=True)
    aoi.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
        help="Bounding box in WGS84 degrees",
    )
    aoi.add_argument("--geojson", type=Path, help="GeoJSON file with one WGS84 Polygon")
    check.add_argument(
        "--start", type=iso_date, help="First day of the ASF query window (UTC)"
    )
    check.add_argument(
        "--end", type=iso_date, help="Last day of the ASF query window (UTC)"
    )
    check.add_argument(
        "--max-results",
        type=positive_int,
        default=2000,
        help="Maximum ASF records to return (default: %(default)s)",
    )
    check.add_argument(
        "--output",
        type=Path,
        default=Path("output/s1cover-report.md"),
        help="Path for a new Markdown report (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start and args.end and args.start > args.end:
        parser.error("--start must be on or before --end")
    try:
        aoi = aoi_options(args.bbox, args.geojson)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(args.output)
        tracks = search_tracks(
            aoi, start=args.start, end=args.end, max_results=args.max_results
        )
        report = render_report(
            tracks, start=args.start, end=args.end, max_results=args.max_results
        )
        write_report(args.output, report)
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileExistsError:
        print(
            "error: output already exists; choose a new --output path", file=sys.stderr
        )
        return 1
    except OSError as exc:
        print(f"error: could not write the report ({exc.strerror})", file=sys.stderr)
        return 1

    print(report, end="")
    print(f"\nReport written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
