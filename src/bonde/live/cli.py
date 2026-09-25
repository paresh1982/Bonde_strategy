"""
Stage 3.1 Live Paper-Trading CLI Runner
Entry point for running controlled live US paper-trading sessions in OBSERVE or PAPER mode.
"""

import argparse
from datetime import date, datetime
import logging
from pathlib import Path
import sys

from bonde.data.models import NY_TZ
from bonde.live.adapters.alpaca import AlpacaConfig, AlpacaMarketDataAdapter
from bonde.live.calendar import USMarketCalendar
from bonde.live.operational_modes import OperationalMode
from bonde.live.runner import LivePaperRunner
from bonde.live.session import LiveSessionEngine
from bonde.live.validation import LiveDataValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bonde.live.cli")


def main():
    parser = argparse.ArgumentParser(description="Bonde Strategy — Stage 3.1 Live Paper Runner")
    parser.add_argument(
        "--mode",
        choices=["OBSERVE", "PAPER"],
        default="OBSERVE",
        help="Operational mode: OBSERVE (listen/calculate, 0 positions) or PAPER (local paper trading)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["AAPL", "TSLA", "NVDA", "MSFT", "AMD"],
        help="List of US equity ticker symbols to stream",
    )
    parser.add_argument(
        "--feed",
        choices=["iex", "sip"],
        default="iex",
        help="Data feed tier: iex (free real-time) or sip (consolidated, $99/mo)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Session date (YYYY-MM-DD), default today",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for multi-session run (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for multi-session run (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--data-root",
        type=str,
        default="data/stage1d",
        help="Path to historical daily bars and security master for premarket prep",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/paper_live",
        help="Output directory for reports and telemetry",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and exit without connecting",
    )

    args = parser.parse_args()

    # Determine date(s)
    if args.start_date and args.end_date:
        start_d = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        is_multi_session = True
        session_dates = USMarketCalendar().get_trading_days_between(start_d, end_d)
    else:
        is_multi_session = False
        session_d = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.now(NY_TZ).date()
        session_dates = [session_d]

    logger.info(f"=== STAGE 3.2 LIVE SESSION INITIALIZING ===")
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Symbols ({len(args.symbols)}): {', '.join(args.symbols)}")
    logger.info(f"Feed: {args.feed.upper()} (Data source: IEX single-exchange feed)")
    logger.info(f"Session Dates ({len(session_dates)}): {[d.isoformat() for d in session_dates]}")
    logger.info(f"Local Paper Execution: ENFORCED (Zero real broker connectivity)")

    # 1. Config from environment
    try:
        config = AlpacaConfig.from_env(symbols=args.symbols)
    except Exception as e:
        logger.warning(
            f"Alpaca credentials not in environment ({e}). Using mock/paper test credentials for dry run."
        )
        config = AlpacaConfig(api_key="DRY_RUN_KEY", secret_key="DRY_RUN_SECRET", symbols=args.symbols, feed=args.feed)

    if args.dry_run:
        logger.info("Dry run complete. Configuration is valid.")
        sys.exit(0)

    # 2. Execution
    if is_multi_session:
        from bonde.live.multi_session import MultiSessionRunner
        multi_runner = MultiSessionRunner(
            output_dir=Path(args.output_dir),
            data_root=Path(args.data_root),
            mode=OperationalMode(args.mode),
        )
        adapter = AlpacaMarketDataAdapter(config)
        adapter.start(args.symbols)
        try:
            for s_date in session_dates:
                logger.info(f"Running multi-session for {s_date}...")
                multi_runner.run_session(s_date, adapter, args.symbols)
            agg = multi_runner.generate_aggregate_report()
            print("\n" + agg.to_markdown())
        finally:
            adapter.stop()
    else:
        adapter = AlpacaMarketDataAdapter(config)
        engine = LiveSessionEngine(
            session_date=session_dates[0],
            data_root=Path(args.data_root),
            output_dir=Path(args.output_dir),
            initial_equity=100_000.0,
        )
        validator = LiveDataValidator()
        runner = LivePaperRunner(
            adapter=adapter,
            engine=engine,
            validator=validator,
            mode=OperationalMode(args.mode),
            session_date=session_dates[0],
        )

        try:
            adapter.start(args.symbols)
            summary = runner.run_session(session_date=session_dates[0], symbols=args.symbols)
            report = runner.generate_daily_report()
            rep_path = Path(args.output_dir) / session_dates[0].strftime("%Y-%m-%d") / "daily_operational_report.json"
            report.to_json(rep_path)
            logger.info(f"Report exported to {rep_path}")
            print("\n" + report.to_markdown())
        except KeyboardInterrupt:
            logger.info("Session interrupted by user.")
            runner.halt("USER_INTERRUPT")
        finally:
            adapter.stop()
            logger.info("Adapter disconnected. Session closed.")


if __name__ == "__main__":
    main()
