from __future__ import annotations

import argparse
import sys

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="", help="CSV path")
    ap.add_argument("--mock", action="store_true", help="Force mock mode")
    ap.add_argument("--cli", action="store_true", help="Run in CLI mode (recommended on macOS)")
    ap.add_argument("--pcsc", action="store_true", help="Use PC/SC reader")
    ap.add_argument("--reader-contains", default="", help="PC/SC reader name contains (empty=auto)")
    args = ap.parse_args(argv)

    if args.cli:
        from .cli import run_cli

        mock = args.mock or (not args.pcsc)
        return run_cli(
            csv_path=args.csv or "sample.csv",
            mock=mock,
            pcsc=args.pcsc,
            reader_contains=args.reader_contains,
        )

    try:
        from .gui import run_gui

        return run_gui(csv_path=args.csv, mock=args.mock)
    except Exception as e:
        print(f"GUI起動に失敗したためCLIにフォールバックします: {e}", file=sys.stderr)
        from .cli import run_cli

        mock = args.mock or (not args.pcsc)
        return run_cli(
            csv_path=args.csv or "sample.csv",
            mock=mock,
            pcsc=args.pcsc,
            reader_contains=args.reader_contains,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

