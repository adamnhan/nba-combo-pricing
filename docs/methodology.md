# Methodology

## Pricing question

For verified leg events A and B, the target is the joint probability P(A and B). Multiplying leg probabilities assumes independence. Shared simulated NBA outcomes provide a dependence structure; externally supplied probabilities anchor each leg.

The package supports more than two legs and mixed YES/NO directions. It checks game identity, exact threshold semantics, participant identity and logical contradictions. Integer thresholds are inclusive: a line of over 220.5 becomes total >= 221. A selected NO side complements the verified event.

## Observed state and shared paths

The state includes period and clock, score, player participation, accumulated statistics, playing time, current lineups and availability. These still matter when leg probabilities come from markets because remaining time, rotations, score and accumulated statistics affect dependence and exact payout logic.

The frozen simulator samples remaining minutes, lineups, team actions and player statistics, including overtime. All selected events are evaluated on the same paths. A player's three-pointer therefore contributes to the same path's points and team score.

The research configuration uses two independent seeds with 4,096 paths per seed. Each state can be simulated once and reused across alternative legs and references. The pricing code is identical to the research core apart from package imports; the manifest records both hashes.

## Market anchoring

`fit_marginals` starts with the empirical probabilities of the observed outcome cells. Iterative proportional fitting adjusts their weights until the requested marginal probabilities are matched to within 1e-7, or rejects incompatible support/nonconvergence.

For a positive two-by-two table this preserves the cross-product odds ratio of the original simulated cells while changing the marginals. It does not hold Pearson correlation fixed. No previously unseen outcome cell is introduced.

The pooled quote must remain within the binary probability range. Per-seed anchored estimates differing by more than 1c are rejected. Missing prices, possible nonbinary payouts, sample boundaries and contradictory events have separate statuses. A missing price is not replaced silently with an invented reference.

`price_combo` validates game/subject identities before simulation. `price_shared_paths` is the lower-level path-reuse API; its caller must perform that validation and supply aligned batches. `normalize_rfq` checks exchange market definitions against an explicit fixture mapping.

## Reference construction

Historical consolidated references prioritize eligible Predexon Kalshi bid/ask midpoints. Eligible archived alternatives use the configured age and spread bounds:

| Reference | Historical maximum age | Additional rule |
|---|---:|---|
| Predexon / Kalshi two-sided midpoint | 120 seconds | Spread at most 20c |
| Archived exact sportsbook reference | 300 seconds | Exact matched event and line |
| Synthetic spread × total study | 90 seconds | Exact two-sided half-point lines |

These were study settings rather than universal live recommendations. An observation must precede valuation. Provider market-update timestamps do not prove the exact time a displayed price changed or became available to a historical client.

For decimal odds d1 and d2, let u1=1/d1 and u2=1/d2. The margin-removal comparison uses:

- **Proportional:** pi=ui/(u1+u2).
- **Additive:** pi=ui−(u1+u2−1)/2; invalid probabilities are rejected.
- **Power:** choose k so u1^k+u2^k=1, and use pi=ui^k.

Each conversion requires two exhaustive sides of the same exact line. Probabilities are computed per bookmaker before taking the median across eligible books. None of these assumptions observes true fair value.

## Calibration and uncertainty

Let p be predicted combo YES probability and y the binary YES payout. The reported conventions are:

- YES overprediction: 100 × mean(p−y).
- NO overvaluation: 100 × mean(y−p).

Positive NO overvaluation means the model assigns more value to NO than its observed payout frequency supports. Individual realizations are not observations of latent fair probability; calibration concerns repeated forecasts and outcomes.

Maker diagnostics use actual filled contract sizes. Standalone expanded player-prop calibration uses equal trade weights. Equal-game checks and game-cluster bootstrap intervals keep repeated trades from being counted as independent games. Groups with constant outcomes or very few games require special caution; a narrow-looking interval in such a group is not evidence of general accuracy.

Four complementary outcomes partition each spread/total checkpoint. Their pooled average errors cancel mechanically. Directions are therefore scored separately, with an additional four-class Brier score per checkpoint. Its range of 0–2 differs from a single binary ticket's 0–1 score.

## Historical NO-maker replay

For fair combo YES probability p and gross premium m, the replay posts the first allowed YES price q >= p+m/100. Its equivalent NO purchase price is 1−q. It assumes a fill only when q is strictly below the historical YES traded price. Price ties do not fill.

Actual print quantities are preserved, subject to resizing at a 0.01-contract quantum. Historical maker-fee rates, price grids and cash-rounding steps are inputs. For quantity n and fee rate r:

```text
fee  = ceil_to_0.000001(r × n × q × (1−q))
cost = ceil_to_balance_step(n × (1−q) + fee)
P&L  = n × NO_payout − cost
```

One $500 cash budget per game is shared by all families and quarters, including fees. Cash is reserved cumulatively; no within-game recycling is assumed. Fees or rate multipliers are not inferred from today's terms.

The fill rule is a counterfactual historical price comparison. It cannot establish queue position, response latency, quote visibility, customer acceptance or competing RFQ quotes. Historical sizes are not proof those sizes would execute against the counterfactual quote.

## Temporal margin selection

The original proportional-model 50–80% spread-cover + over cohort is fixed before comparing methods. On 227 earlier cases across 192 games, the method minimizing equal-game binary Brier score is selected from common priceable cases. The choice is saved before pricing the later group.

The primary later test contains 242 cases across 206 games, with dates strictly after the last training date. Two same-date boundary games are excluded. Later results cannot alter the selection. The same simulator, seeds, exact lines and correlation procedure are reused; the method changes only the marginal inputs.

These games had been inspected in earlier analyses. The split measures temporal consistency within this research archive and is not a fresh prospective test.
