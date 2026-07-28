# Edith Phase 2 — Evidence-Gated Research

This phase adds analytical research components only. It does not alter signal generation, entries, stops, targets, live lot sizing, or broker submission.

## Feature Sculptor

`FeatureSculptor` groups historical `TradeObservation` records into one- and two-feature fingerprints and ranks them by:

- sample size
- win rate
- USD expectancy
- R expectancy
- profit factor
- maximum cash drawdown
- split-sample stability

A fingerprint is marked `approved` only when every configured gate passes. Approval means eligible for further replay and out-of-sample validation; it does not authorize deployment.

## Position-sizing research

`PositionSizingResearch` compares fixed-risk, confidence-scaled, and volatility-scaled policies counterfactually. It returns final equity, net PnL, maximum drawdown, and whether a configured ruin floor was reached.

The module has no broker adapter and cannot submit or modify orders.

## Dashboard

The Replit/Streamlit command centre now:

- displays monetary values in US dollars (`$`)
- exposes a Feature Sculptor leaderboard
- separates approved fingerprints from rejected candidates
- shows rejection reasons and stability evidence
- continues to show no fabricated data when source files are absent

## Required next integration

The Edith notebook/runtime must serialize completed trade observations with immutable feature values and outcomes. Those records can then be passed to the sculptor and its results written to `data/feature_sculptor_results.jsonl`.
