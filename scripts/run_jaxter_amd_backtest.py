from __future__ import annotations

import argparse
import json

import pandas as pd

from lilith.jaxter import JaxterResearchRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jaxter AMD-Structure research on completed OHLC candles.")
    parser.add_argument("csv", help="CSV containing timestamp, open, high, low and close columns")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--months", type=int, choices=range(3, 7), default=6)
    parser.add_argument("--output", default="data/jaxter")
    args = parser.parse_args()

    frame = pd.read_csv(args.csv)
    runner = JaxterResearchRunner()
    trades, report = runner.run(
        frame,
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback_months=args.months,
    )
    runner.persist(trades, report, args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
