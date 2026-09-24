"""
Operational Script: Run Live Paper-Trading Session (Stage 2)
Executes the live state machine chronologically across a trading session.
Usage:
  python scripts/run_paper_session.py [--date YYYY-MM-DD] [--synthetic]
"""

import argparse
from datetime import date
from pathlib import Path
import sys

from bonde.live.calendar import USMarketCalendar
from bonde.live.session import LiveSessionEngine
from bonde.live.synthetic_session import SyntheticSessionReplayer


def main():
    parser = argparse.ArgumentParser(description="Run Live Paper-Trading Session")
    parser.add_argument("--date", type=str, default=None, help="Session date (YYYY-MM-DD)")
    parser.add_argument("--synthetic", action="store_true", help="Run deterministic synthetic streaming session")
    parser.add_argument("--data-root", type=str, default="data/stage1d", help="Data root path")
    parser.add_argument("--output-dir", type=str, default="data/paper", help="Output directory")
    args = parser.parse_args()

    cal = USMarketCalendar()
    session_d = date.fromisoformat(args.date) if args.date else (date(2023, 6, 15) if args.synthetic else date.today())
    if not cal.is_trading_day(session_d) and not args.synthetic:
        session_d = cal.get_prior_trading_day(session_d)

    print(f"=== [LIVE SESSION] Initializing Paper Session for {session_d.isoformat()} ===")

    if args.synthetic:
        print("Replaying deterministic synthetic session...")
        result = SyntheticSessionReplayer.run_synthetic_session(
            session_date=session_d,
            data_root=Path(args.data_root),
            output_dir=Path(args.output_dir),
        )
        print("Session completed successfully.")
        print(f"Result summary: {result['summary']}")
        print(f"Artifacts exported to: {Path(args.output_dir) / session_d.strftime('%Y-%m-%d')}")
    else:
        engine = LiveSessionEngine(
            session_date=session_d,
            data_root=Path(args.data_root),
            output_dir=Path(args.output_dir),
        )
        focus = engine.run_premarket()
        engine.open_session()
        summary = engine.close_session()
        print(f"Session closed. Summary: {summary}")
        print(f"Artifacts exported to: {engine.output_dir}")


if __name__ == "__main__":
    main()
