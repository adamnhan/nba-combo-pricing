# Data, provenance and reproduction

## What this checkout can reproduce

The bundled code and frozen numeric model run the illustrative RFQ offline. The replay example demonstrates exact price-grid rounding, fee/cash rounding, actual-size handling and a shared game cap. Tests exercise anchoring, contradictions, possible nonbinary payouts, seed rejection, as-of timestamps, game-level resampling and earlier-only selection.

`python analysis/render_figures.py` rebuilds the figures from the aggregate CSV files. The CSVs permit independent checking of reported tables and study accounting. They do not recreate the underlying observations or bootstrap draws.

The portable replay implementation was also checked against the full original private research input: both 2c and 3c baseline fill IDs, quantities, quotes and P&L must match before release. The published validation receipt contains aggregate counts and totals.

## What an independent historical rerun needs

A complete rerun requires separately acquired and verified:

1. Actual historical combo prints, sizes, sides and settlement outcomes.
2. Exact constituent market definitions and fixture/participant mappings.
3. Pre-request two-sided reference books or exact paired sportsbook lines, with timestamps.
4. Timestamped NBA play-by-play, player participation, rosters and historical minutes priors.
5. Applicable historical price grids, fee rates and rounding steps.

The research used Kalshi trade/market histories, Predexon historical Kalshi books, The Odds API sportsbook snapshots and NBA game records. The public release contains aggregate research outputs and fitted numeric model arrays, with no raw paid-provider responses or account/order history. Users must obtain underlying sources under their own access and redistribution terms. Polymarket is not used in the reported results.

Candles are an optional source of references. Their absence alone is not a trade exclusion. Exact leg identities, price eligibility, timing quality, model support and binary settlement eligibility determine coverage.

## Dataset boundaries

- **Consolidated maker replay:** all supported families, mixed eligible historical references, 28,064 actual trades across 1,233 games. P&L uses only the subset satisfying the counterfactual quote and cash-cap rules.
- **Standalone non-player calibration:** both legs undecided; its moneyline × total count is 20,356 rather than the maker eligibility count of 20,496. The difference is a population restriction, not missing fills.
- **Expanded player-prop calibration:** 2025–26 Q3–Q4, newly priceable actual trades, both legs undecided, equal trade weights. It is separate from the earlier consolidated maker-fill replay.
- **Synthetic spread × total:** 2025–26 outcome-blind archived line choices, one mid-quarter checkpoint per available game/quarter. It includes neither synthetic trade prices nor simulated acceptance labels.
- **Margin test:** the original proportional 50–80% cover+over cohort. Method choice uses earlier outcomes only. The primary test excludes two same-date boundary games.
- **Premium sensitivity:** original consolidated prices remain frozen. Only moneyline × total premiums change, with other families retaining their baseline premiums and the same shared game cap. The extra “observed miss” surcharges are full-sample diagnostics.

## Files

| File | Population / interpretation |
|---|---|
| `results/real_trade_backtest.csv` | Overall/family capped replay P&L and uncertainty |
| `results/real_trade_coverage.csv` | Considered and included trades, reference coverage and exclusion reasons |
| `results/family_quarter_maker.csv` | NO-overvaluation sign convention; 2c/3c simulated fills |
| `results/non_player_calibration.csv` | Standalone non-player calibration by season; original YES-overprediction convention |
| `results/expanded_player_prop_calibration.csv` | NO-overvaluation convention; all newly priceable undecided-leg prop trades |
| `results/same_fill_correlation_ablation.csv` | Actual-size-weighted independent/correlated comparison on identical fills |
| `results/synthetic_spread_total_calibration.csv` | YES-overprediction convention, four directions kept separate |
| `results/synthetic_reliability_bins.csv` | Probability-band diagnostics and whole-game intervals |
| `results/synthetic_joint_scores.csv` | Four-class Brier, one categorical outcome per checkpoint |
| `results/margin_removal_walkforward.csv` | Earlier selection, frozen later test and same-case freshness checks |
| `results/premium_sensitivity*.csv` | Hypothetical moneyline × total premiums using original reference estimates |
| `results/study_manifest.json` | Population counts, original artifact hashes and aggregate export hashes |
| `results/release_validation.json` | Public package checks and original-replay equivalence |

Column names retain explicit sign conventions. A NO error must not be confused with YES overprediction, nor with net P&L after premiums and fees.

## Bring your own normalized trades

Each line of the replay input is a JSON object with the fields shown in `examples/illustrative_trades.jsonl`. Required economic inputs are `fair_yes`, `trade_yes`, `contracts`, binary `payout_yes`, `price_ranges`, `maker_fee_rate` and `balance_step`; IDs and timezone-aware timestamps establish ordering and game grouping.

All constituent-leg identity checks and reference eligibility checks must occur before the normalized trade enters the replay. `references.validated_midpoint` supplies a strict pre-request timestamp and spread check; it cannot verify market identity by itself.

The packaged model is frozen for the reported research. `pricer.MODEL_SHA256` identifies the fitted artifact. Replacing or refitting it creates a new experiment; the published results must not be attributed to the new artifact without a new evaluation.
