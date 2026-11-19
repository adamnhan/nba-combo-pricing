# Frozen NBA simulator

## Artifact

- File: `models/fitted_model.npz`
- SHA256: `25f5dc57dcae0c707cde4f558b08b074db7f4dbfe471bb65cd2a9f039a1a7652`
- Contents: 43 numeric arrays; no Python pickle objects or credentials.
- Training seasons: 2022–23, 2023–24 and 2024–25.
- The portable artifact contains fitted rotation coefficients, empirical residual banks, pooled player rates, player minutes summaries, team context and event-model parameters.

## Intended use

Research on coherent full-game NBA outcomes conditional on a verified observed state. The simulator supplies dependence to a combo pricer whose individual leg probabilities can be externally anchored. The unanchored simulator is also available for diagnostics; it is not interchangeable with a market-anchored estimate.

The model samples player minutes and lineups, then allocates basketball actions and statistics on shared paths. The artifact includes learned empirical residual distributions rather than only parametric coefficients.

## Known limitations

The model needs correctly reconstructed game states and current availability. Historical future-game outcomes, post-request prices and future rosters must not enter that state. Rookies and unfamiliar players rely more heavily on pooled rate information. Rotation, injury and late-game behavior may shift across seasons.

Leg anchoring does not guarantee calibrated dependence. Conversely, a poor reference probability can produce a poor joint price even when simulated dependence is useful. Numerical seed guards check simulation stability, not economic accuracy.

Evaluations include later seasons, but those games were repeatedly inspected during research. The reported chronological margin test therefore does not establish untouched prospective performance. The illustrative demo uses fictional player identifiers and reference values; it is a software demonstration rather than an accuracy benchmark.

The model is not a live execution service. Historical quote comparisons do not establish realized RFQ fills, production latency, exchange acceptance or reliable profitability.
