# Stage 3 Provider Evaluation

## Overview
As part of Stage 3, we evaluated 7 different market data providers to find the most suitable candidate for paper trading and infrastructure validation.

## Providers Evaluated
1. **Alpaca (IEX and SIP)**
2. Polygon.io
3. Interactive Brokers
4. Tradier
5. Finnhub
6. Tiingo
7. AlphaVantage

## Selection Criteria
- **Cost**: Free tier preferred for initial testing.
- **WebSocket Streaming**: Essential for minute bars.
- **REST Backfill**: Needed for gap recovery upon disconnects.
- **Library Support**: Existing robust Python SDKs.
- **Symbol Limits**: Enough to cover our standard backtest portfolio.

## Selection: Alpaca IEX
**Alpaca IEX** was selected due to the robust `alpaca-py` library, easy onboarding, and sufficient limits on the free tier (up to 30 symbols on WS, no delays for REST).

## IEX Coverage Limitations
- Represents only ~2.5% of total US market volume.
- Only reports trades executed on the Investors Exchange (IEX).
- Prone to generating empty bars (gaps) for stocks that are not highly liquid.
- Should NOT be used for robust P&L calculations.

## Upgrade Path
To move towards real money trading and highly accurate signals, the plan is to upgrade to the **Alpaca SIP** feed ($99/month), which aggregates all US exchanges. The infrastructure built in Stage 3 is agnostic to the feed (IEX vs. SIP), making this transition a one-line config change.
