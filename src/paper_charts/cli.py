"""Command-line interface for figure extraction."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

import fitz

from paper_charts.extractor import extract_figures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper-charts",
        description="Find and crop captioned figures from one research paper PDF.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract_parser = subparsers.add_parser("extract", help="Extract figure crops from a PDF.")
    extract_parser.add_argument("pdf", type=Path, help="Path to the PDF article.")
    extract_parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory (default: ./output).")
    extract_parser.add_argument("--dpi", type=int, default=200, help="Crop resolution from 72 to 600 DPI (default: 200).")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        figures = extract_figures(args.pdf, args.output, args.dpi)
    except (ValueError, fitz.FileDataError, fitz.FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Found and cropped {len(figures)} figure(s).")
    print(f"Manifest: {(args.output.resolve() / 'figures.csv')}")
    print(f"Images: {(args.output.resolve() / 'figures')}")
    if not figures:
        print("No captioned figures could be associated with nearby PDF graphics.")
        return 1
    return 0
