"""
Operational Script: Run Daily Pre-Market Preparation (Stage 2)
Generates the deterministic Daily Focus List before market open.
Usage:
  python scripts/run_daily_prep.py [--date YYYY-MM-DD]
"""

import argparse
from datetime import date
from pathlib import Path
import sys

from bonde.live.calendar import USMarketCalendar
from bonde.live.prep import DailyPrepPipeline


def main():
    parser = argparse.ArgumentParser(description="Run Daily Pre-Market Preparation Pipeline")
    parser.add_argument("--date", type=str, default=None, help="Session date (YYYY-MM-DD), default=today/most recent")
    parser.add_argument("--data-root", type=str, default="data/stage1d", help="Data root path")
    parser.add_argument("--output-dir", type=str, default="data/paper", help="Output directory for focus list")
    args = parser.parse_args()

    cal = USMarketCalendar()
    session_d = date.fromisoformat(args.date) if args.date else date.today()
    if not cal.is_trading_day(session_d):
        prior = cal.get_prior_trading_day(session_d)
        print(f"Date {session_d.isoformat()} is not a trading day; using prior session {prior.isoformat()}")
        session_d = prior

    print(f"=== [PRE-MARKET] Running Daily Prep for {session_d.isoformat()} ===")
    pipeline = DailyPrepPipeline(data_root=Path(args.data_root))
    focus_list = pipeline.run_prep(session_date=session_d)

    out_path = Path(args.output_dir) / session_d.strftime("%Y-%m-%d")
    focus_list.save_parquet(out_path / "focus_list.parquet")
    focus_list.save_json(out_path / "focus_list.json")

    print(f"Market Regime: {focus_list.regime.value}")
    print(f"Daily Budget: {focus_list.daily_budget_r}R | Total Allocated: {focus_list.total_allocated_r}R")
    print(f"Approved Candidates: {len(focus_list.approved_candidates)}")
    for c in focus_list.approved_candidates:
        print(f"  + [{c.module}] {c.ticker} ({c.security_id}) | Trigger: ${c.trigger_price:.2f} | Stop: ${c.structural_stop:.2f} | Alloc: {c.allocated_shares} shs ({c.fractional_r:.2f}R)")

    print(f"Rejected Candidates: {len(focus_list.rejected_candidates)}")
    print(f"Snapshot written to: {out_path / 'focus_list.parquet'}")


if __name__ == "__main__":
    main()
