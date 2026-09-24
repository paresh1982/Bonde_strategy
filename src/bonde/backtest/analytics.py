"""
Performance Analytics, Expectancy, and Distribution Engine (Phases 9 & 10)
Computes all 22 required performance metrics across engines, regimes, modules, and years.
Performs full right-tail dependency analysis (top 1%, 5%, 10% profit contribution).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
import math
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


@dataclass
class PerformanceSummary:
    name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    scratch_trades: int
    win_rate: float
    loss_rate: float
    avg_r: float
    median_r: float
    expectancy_r: float
    avg_winner_r: float
    avg_loser_r: float
    payoff_ratio: float
    profit_factor: float
    total_realized_pnl: float
    max_drawdown_dollars: float
    max_drawdown_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_mae_dollars: float
    avg_mfe_dollars: float
    avg_holding_period_bars: float
    time_to_1r_avg_bars: Optional[float]
    time_to_2r_avg_bars: Optional[float]
    exposure_pct: float
    avg_cash_pct: float
    annual_turnover: float
    total_slippage_cost: float
    total_commission_cost: float


@dataclass
class DistributionMetrics:
    total_trades: int
    r_skewness: float
    r_kurtosis: float
    median_trade_r: float
    median_winner_r: float
    median_loser_r: float
    percentile_5th_r: float
    percentile_25th_r: float
    percentile_50th_r: float
    percentile_75th_r: float
    percentile_95th_r: float
    top_1_pct_profit_share: float
    top_5_pct_profit_share: float
    top_10_pct_profit_share: float
    bottom_1_pct_loss_share: float
    bottom_5_pct_loss_share: float
    bottom_10_pct_loss_share: float
    top_1_winner_dollars: float
    top_5_winners_profit_share: float
    top_10_winners_profit_share: float


class BacktestAnalyticsEngine:
    """
    Computes rigorous descriptive metrics and distribution statistics from trade telemetry.
    Strictly avoids optimization or ranking biases.
    """

    @staticmethod
    def calculate_performance(
        trades_df: pd.DataFrame,
        equity_df: Optional[pd.DataFrame] = None,
        name: str = "Portfolio",
        initial_equity: float = 100_000.0,
    ) -> PerformanceSummary:
        if trades_df.empty:
            return PerformanceSummary(
                name=name,
                total_trades=0, winning_trades=0, losing_trades=0, scratch_trades=0,
                win_rate=0.0, loss_rate=0.0, avg_r=0.0, median_r=0.0, expectancy_r=0.0,
                avg_winner_r=0.0, avg_loser_r=0.0, payoff_ratio=0.0, profit_factor=0.0,
                total_realized_pnl=0.0, max_drawdown_dollars=0.0, max_drawdown_pct=0.0,
                cagr_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
                avg_mae_dollars=0.0, avg_mfe_dollars=0.0, avg_holding_period_bars=0.0,
                time_to_1r_avg_bars=None, time_to_2r_avg_bars=None,
                exposure_pct=0.0, avg_cash_pct=100.0, annual_turnover=0.0,
                total_slippage_cost=0.0, total_commission_cost=0.0,
            )

        n = len(trades_df)
        winners = trades_df[trades_df["realized_pnl"] > 0]
        losers = trades_df[trades_df["realized_pnl"] < 0]
        scratches = trades_df[trades_df["realized_pnl"] == 0]

        n_win = len(winners)
        n_loss = len(losers)
        n_scratch = len(scratches)

        win_rate = (n_win / n) if n > 0 else 0.0
        loss_rate = (n_loss / n) if n > 0 else 0.0

        r_series = trades_df["r_multiple"]
        avg_r = float(r_series.mean()) if n > 0 else 0.0
        median_r = float(r_series.median()) if n > 0 else 0.0

        avg_win_r = float(winners["r_multiple"].mean()) if n_win > 0 else 0.0
        avg_loss_r = float(losers["r_multiple"].mean()) if n_loss > 0 else 0.0
        payoff_ratio = abs(avg_win_r / avg_loss_r) if avg_loss_r != 0 else 0.0

        expectancy_r = (win_rate * avg_win_r) + (loss_rate * avg_loss_r)

        gross_profits = float(winners["realized_pnl"].sum())
        gross_losses = abs(float(losers["realized_pnl"].sum()))
        profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else (999.0 if gross_profits > 0 else 0.0)

        total_realized = float(trades_df["realized_pnl"].sum())

        # Slippage & Commission costs
        slip_cost = float(trades_df["slippage_cost"].sum()) if "slippage_cost" in trades_df else 0.0
        comm_cost = float(trades_df["commission_cost"].sum()) if "commission_cost" in trades_df else 0.0

        # Holding periods and MAE/MFE
        avg_holding = float(trades_df["holding_period_bars"].mean()) if "holding_period_bars" in trades_df else 0.0
        avg_mae = float(trades_df["mae_dollars"].mean()) if "mae_dollars" in trades_df else 0.0
        avg_mfe = float(trades_df["mfe_dollars"].mean()) if "mfe_dollars" in trades_df else 0.0

        t1r = trades_df["time_to_1r_bars"].dropna() if "time_to_1r_bars" in trades_df else pd.Series()
        t2r = trades_df["time_to_2r_bars"].dropna() if "time_to_2r_bars" in trades_df else pd.Series()
        time_to_1r = float(t1r.mean()) if not t1r.empty else None
        time_to_2r = float(t2r.mean()) if not t2r.empty else None

        # Drawdown, CAGR, Sharpe, Sortino from equity curve
        max_dd_dollars = 0.0
        max_dd_pct = 0.0
        cagr = 0.0
        sharpe = 0.0
        sortino = 0.0
        exposure_pct = 0.0
        avg_cash_pct = 100.0
        turnover = 0.0

        if equity_df is not None and not equity_df.empty:
            eq = equity_df["total_equity"]
            peak = eq.cummax()
            dd_dollars = peak - eq
            dd_pct = (dd_dollars / peak) * 100.0
            max_dd_dollars = float(dd_dollars.max())
            max_dd_pct = float(dd_pct.max())

            days = len(equity_df)
            years = max(days / 252.0, 0.1)
            ending_eq = float(eq.iloc[-1])
            if ending_eq > 0 and initial_equity > 0:
                cagr = ((ending_eq / initial_equity) ** (1.0 / years) - 1.0) * 100.0

            daily_returns = eq.pct_change().dropna()
            if len(daily_returns) > 1 and daily_returns.std() > 0:
                sharpe = float((daily_returns.mean() / daily_returns.std()) * math.sqrt(252))
                downside_returns = daily_returns[daily_returns < 0]
                downside_std = downside_returns.std() if len(downside_returns) > 1 else daily_returns.std()
                sortino = float((daily_returns.mean() / downside_std) * math.sqrt(252)) if downside_std > 0 else 0.0

            if "cash_pct" in equity_df:
                avg_cash_pct = float(equity_df["cash_pct"].mean())
                exposure_pct = 100.0 - avg_cash_pct
            if "daily_turnover" in equity_df:
                turnover = float(equity_df["daily_turnover"].sum() / years)

        return PerformanceSummary(
            name=name,
            total_trades=n,
            winning_trades=n_win,
            losing_trades=n_loss,
            scratch_trades=n_scratch,
            win_rate=round(win_rate * 100.0, 2),
            loss_rate=round(loss_rate * 100.0, 2),
            avg_r=round(avg_r, 3),
            median_r=round(median_r, 3),
            expectancy_r=round(expectancy_r, 3),
            avg_winner_r=round(avg_win_r, 3),
            avg_loser_r=round(avg_loss_r, 3),
            payoff_ratio=round(payoff_ratio, 2),
            profit_factor=round(profit_factor, 2),
            total_realized_pnl=round(total_realized, 2),
            max_drawdown_dollars=round(max_dd_dollars, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            cagr_pct=round(cagr, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            avg_mae_dollars=round(avg_mae, 2),
            avg_mfe_dollars=round(avg_mfe, 2),
            avg_holding_period_bars=round(avg_holding, 1),
            time_to_1r_avg_bars=round(time_to_1r, 1) if time_to_1r else None,
            time_to_2r_avg_bars=round(time_to_2r, 1) if time_to_2r else None,
            exposure_pct=round(exposure_pct, 2),
            avg_cash_pct=round(avg_cash_pct, 2),
            annual_turnover=round(turnover, 2),
            total_slippage_cost=round(slip_cost, 2),
            total_commission_cost=round(comm_cost, 2),
        )

    @staticmethod
    def calculate_distribution(trades_df: pd.DataFrame) -> DistributionMetrics:
        """
        Calculates trade distribution percentiles and right-tail dependency.
        Specifically answers: What % of total profit comes from top 1%, 5%, 10% winners?
        """
        if trades_df.empty:
            return DistributionMetrics(
                total_trades=0, r_skewness=0.0, r_kurtosis=0.0,
                median_trade_r=0.0, median_winner_r=0.0, median_loser_r=0.0,
                percentile_5th_r=0.0, percentile_25th_r=0.0, percentile_50th_r=0.0,
                percentile_75th_r=0.0, percentile_95th_r=0.0,
                top_1_pct_profit_share=0.0, top_5_pct_profit_share=0.0, top_10_pct_profit_share=0.0,
                bottom_1_pct_loss_share=0.0, bottom_5_pct_loss_share=0.0, bottom_10_pct_loss_share=0.0,
                top_1_winner_dollars=0.0, top_5_winners_profit_share=0.0, top_10_winners_profit_share=0.0,
            )

        r_series = trades_df["r_multiple"]
        pnl_series = trades_df["realized_pnl"]
        n = len(trades_df)

        skew = float(r_series.skew()) if n > 2 else 0.0
        kurt = float(r_series.kurt()) if n > 3 else 0.0

        median_trade_r = float(r_series.median())
        winners = trades_df[trades_df["realized_pnl"] > 0]
        losers = trades_df[trades_df["realized_pnl"] < 0]

        median_win = float(winners["r_multiple"].median()) if not winners.empty else 0.0
        median_loss = float(losers["r_multiple"].median()) if not losers.empty else 0.0

        # Percentiles
        p5 = float(np.percentile(r_series, 5))
        p25 = float(np.percentile(r_series, 25))
        p50 = float(np.percentile(r_series, 50))
        p75 = float(np.percentile(r_series, 75))
        p95 = float(np.percentile(r_series, 95))

        # Right-Tail Dependency
        total_positive_profit = float(winners["realized_pnl"].sum()) if not winners.empty else 0.0
        total_negative_loss = abs(float(losers["realized_pnl"].sum())) if not losers.empty else 0.0

        sorted_profits = winners["realized_pnl"].sort_values(ascending=False).reset_index(drop=True)
        sorted_losses = losers["realized_pnl"].sort_values(ascending=True).reset_index(drop=True)

        k_1pct = max(1, math.ceil(n * 0.01))
        k_5pct = max(1, math.ceil(n * 0.05))
        k_10pct = max(1, math.ceil(n * 0.10))

        top_1pct_pnl = float(sorted_profits.head(k_1pct).sum()) if not sorted_profits.empty else 0.0
        top_5pct_pnl = float(sorted_profits.head(k_5pct).sum()) if not sorted_profits.empty else 0.0
        top_10pct_pnl = float(sorted_profits.head(k_10pct).sum()) if not sorted_profits.empty else 0.0

        top_1_winner = float(sorted_profits.iloc[0]) if not sorted_profits.empty else 0.0
        top_5_winners = float(sorted_profits.head(5).sum()) if not sorted_profits.empty else 0.0
        top_10_winners = float(sorted_profits.head(10).sum()) if not sorted_profits.empty else 0.0

        bot_1pct_loss = abs(float(sorted_losses.head(k_1pct).sum())) if not sorted_losses.empty else 0.0
        bot_5pct_loss = abs(float(sorted_losses.head(k_5pct).sum())) if not sorted_losses.empty else 0.0
        bot_10pct_loss = abs(float(sorted_losses.head(k_10pct).sum())) if not sorted_losses.empty else 0.0

        top_1pct_share = (top_1pct_pnl / total_positive_profit * 100.0) if total_positive_profit > 0 else 0.0
        top_5pct_share = (top_5pct_pnl / total_positive_profit * 100.0) if total_positive_profit > 0 else 0.0
        top_10pct_share = (top_10pct_pnl / total_positive_profit * 100.0) if total_positive_profit > 0 else 0.0

        top_5_win_share = (top_5_winners / total_positive_profit * 100.0) if total_positive_profit > 0 else 0.0
        top_10_win_share = (top_10_winners / total_positive_profit * 100.0) if total_positive_profit > 0 else 0.0

        bot_1pct_share = (bot_1pct_loss / total_negative_loss * 100.0) if total_negative_loss > 0 else 0.0
        bot_5pct_share = (bot_5pct_loss / total_negative_loss * 100.0) if total_negative_loss > 0 else 0.0
        bot_10pct_share = (bot_10pct_loss / total_negative_loss * 100.0) if total_negative_loss > 0 else 0.0

        return DistributionMetrics(
            total_trades=n,
            r_skewness=round(skew, 3),
            r_kurtosis=round(kurt, 3),
            median_trade_r=round(median_trade_r, 3),
            median_winner_r=round(median_win, 3),
            median_loser_r=round(median_loss, 3),
            percentile_5th_r=round(p5, 3),
            percentile_25th_r=round(p25, 3),
            percentile_50th_r=round(p50, 3),
            percentile_75th_r=round(p75, 3),
            percentile_95th_r=round(p95, 3),
            top_1_pct_profit_share=round(top_1pct_share, 2),
            top_5_pct_profit_share=round(top_5pct_share, 2),
            top_10_pct_profit_share=round(top_10pct_share, 2),
            bottom_1_pct_loss_share=round(bot_1pct_share, 2),
            bottom_5_pct_loss_share=round(bot_5pct_share, 2),
            bottom_10_pct_loss_share=round(bot_10pct_share, 2),
            top_1_winner_dollars=round(top_1_winner, 2),
            top_5_winners_profit_share=round(top_5_win_share, 2),
            top_10_winners_profit_share=round(top_10_win_share, 2),
        )
