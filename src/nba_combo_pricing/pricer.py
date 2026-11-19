"""Price full-game NBA same-game combos from the frozen simulator's shared paths."""

import argparse
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np

from .simulator import Simulator
from .state import GameState

PLAYER_STATS = {"points": 0, "rebounds": 1, "assists": 2, "threes": 3}
PROP_SERIES = {
    "KXNBAPTS": ("points", "points"),
    "KXNBAREB": ("rebounds", "rebounds"),
    "KXNBAAST": ("assists", "assists"),
    "KXNBA3PT": ("threes", r"(?:made three-pointers|three pointers|threes)"),
}
GAME_SERIES = {"KXNBAGAME": "moneyline", "KXNBASPREAD": "spread", "KXNBATOTAL": "total"}
MODEL_SHA256 = "25f5dc57dcae0c707cde4f558b08b074db7f4dbfe471bb65cd2a9f039a1a7652"


@dataclass(frozen=True)
class Leg:
    ticker: str
    game_id: str
    kind: str
    side: str
    minimum: int
    subject_id: int | None = None

    def __post_init__(self):
        if not self.ticker or not self.game_id or self.side not in {"yes", "no"}:
            raise ValueError("Each leg needs a ticker, game ID, and YES or NO side")
        if self.kind not in PLAYER_STATS and self.kind not in GAME_SERIES.values():
            raise ValueError(f"Unsupported market type: {self.kind}")
        if type(self.minimum) is not int:
            raise ValueError("The minimum must be an integer inclusive threshold")
        if self.kind == "moneyline" and self.minimum != 1:
            raise ValueError("A full-game moneyline is a win by at least one point")
        if self.kind in {*PLAYER_STATS, "total"} and self.minimum <= 0:
            raise ValueError("Player and total thresholds must be positive")
        if self.kind == "total":
            if self.subject_id is not None:
                raise ValueError("Game total must not specify a player or team")
        elif type(self.subject_id) is not int or self.subject_id <= 0:
            raise ValueError("Provide the verified NBA player or team ID")


def name_key(name):
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return "".join(c for c in decomposed if c.isalnum())


def normalize_rfq(selections, markets, fixture):
    """Map verified Kalshi market definitions to integer events for one NBA game.

    Fixture supplies game_id, Kalshi game_keys, team_ids by Kalshi team code,
    and players by full verified display name. The latter values are NBA/ESPN
    identifiers aligned to the simulator's GameState, not ticker abbreviations.
    """
    players = {}
    for name, pid in fixture["players"].items():
        key = name_key(name)
        if key in players and players[key] != int(pid):
            raise ValueError(f"Ambiguous player name: {name}")
        players[key] = int(pid)
    game_keys = set(fixture["game_keys"])
    legs = []
    for selected in selections:
        ticker = selected["market_ticker"]
        market = markets[ticker]
        event = selected["event_ticker"]
        series, key = event.split("-", 1)
        if (key not in game_keys or ticker != market["ticker"] or event != market["event_ticker"]
                or not ticker.startswith(event + "-") or market.get("market_type") != "binary"):
            raise ValueError(f"Market is outside the verified full-game fixture: {ticker}")
        suffix = ticker[len(event) + 1:]
        rule_text = market.get("rules_primary", "")
        if series in PROP_SERIES:
            # Older full-game contracts state participation explicitly. A
            # positive stat threshold already requires entry. DNP uncertainty
            # remains handled by path_outcomes, as for the newer wording.
            rule_text = re.sub(r"^(If .+?) enters the game and records ",
                               r"\1 records ", rule_text, count=1, flags=re.I)
        rule_match = re.fullmatch(
            r"If (.+?) (?:in the|the) .+ (?:pro|professional) basketball game originally scheduled for "
            r"(?:[A-Za-z]+ \d{1,2}, \d{4})(.*), then the market resolves to Yes\.", rule_text, re.I
        )
        if rule_match is None:
            raise ValueError(f"Unrecognized full-game settlement rule: {ticker}")
        condition, after_date = rule_match.groups()
        subject = None
        if series in PROP_SERIES:
            kind, label = PROP_SERIES[series]
            prop = re.fullmatch(r"(.+) records (\d+)\+ " + label, condition, re.I)
            if after_date or prop is None or not suffix.endswith("-" + prop[2]):
                raise ValueError(f"Prop ticker and settlement rule disagree: {ticker}")
            subject = players.get(name_key(prop[1]))
            minimum = int(prop[2])
            if market.get("floor_strike") is not None and math.floor(Decimal(str(market["floor_strike"]))) + 1 != minimum:
                raise ValueError(f"Prop settlement rule and floor strike disagree: {ticker}")
            if subject is None:
                raise ValueError(f"No verified player identity for {prop[1]}")
        elif series in GAME_SERIES:
            kind = GAME_SERIES[series]
            if kind == "moneyline":
                winner = re.fullmatch(r"(.+) wins", condition, re.I)
                if after_date or winner is None or name_key(winner[1]) != name_key(market.get("yes_sub_title") or ""):
                    raise ValueError(f"Invalid moneyline rule: {ticker}")
                minimum = 1
                subject = fixture["team_ids"].get(suffix)
            else:
                pattern = r"over (-?\d+(?:\.\d+)?) total points are scored" if kind == "total" else (
                    r"(.+) wins by more than (-?\d+(?:\.\d+)?) points")
                expression = re.fullmatch(pattern, condition, re.I) if not after_date else None
                number = r"(-?\d+(?:\.\d+)?)"
                if expression is None and kind == "total":
                    if not after_date:
                        expression = re.fullmatch(r".+ and .+ collectively score over " + number + r" total points",
                                                  condition, re.I)
                    elif condition.casefold() == "the teams":
                        expression = re.fullmatch(r" collectively score more than " + number + r" points",
                                                  after_date, re.I)
                if expression is None and kind == "spread":
                    team = re.fullmatch(r"(.+) wins", condition, re.I)
                    margin = re.fullmatch(r" by more than " + number + r" points", after_date, re.I)
                    if team and margin:
                        condition = f"{team[1]} wins by more than {margin[1]} points"
                        expression = re.fullmatch(pattern, condition, re.I)
                if expression is None or market.get("strike_type") != "greater":
                    raise ValueError(f"Invalid spread or total rule: {ticker}")
                line = Decimal(expression[expression.lastindex])
                if kind == "spread":
                    title = re.fullmatch(r"(.+) wins by over (-?\d+(?:\.\d+)?) points",
                                         market.get("yes_sub_title") or "", re.I)
                    if title is None or name_key(title[1]) != name_key(expression[1]) or Decimal(title[2]) != line:
                        raise ValueError(f"Spread title and settlement rule disagree: {ticker}")
                if market.get("floor_strike") is None or Decimal(str(market["floor_strike"])) != line:
                    raise ValueError(f"Settlement rule and strike disagree: {ticker}")
                minimum = math.floor(line) + 1
                # Historical tickers can encode the floor of a verified half-point line.
                strike_slugs = {str(minimum)}
                if line % 1:
                    strike_slugs.add(str(math.floor(line)))
                if kind == "spread":
                    matches = [pid for code, pid in fixture["team_ids"].items()
                               if suffix.startswith(code) and suffix[len(code):] in strike_slugs]
                    subject = matches[0] if len(matches) == 1 else None
                elif suffix not in strike_slugs:
                    raise ValueError(f"Total ticker and settlement rule disagree: {ticker}")
        else:
            raise ValueError(f"Unsupported full-game series: {series}")
        if kind != "total" and subject is None:
            raise ValueError(f"No verified team identity or ticker strike: {ticker}")
        legs.append(Leg(ticker, str(fixture["game_id"]), kind, selected["side"], minimum,
                        int(subject) if subject is not None else None))
    return tuple(legs)


def impossible_combo(state, legs):
    """Check exact contradictions on the integer score and player-stat axes."""
    bounds = {}
    for leg in legs:
        if leg.kind in PLAYER_STATS:
            i = state.players.index(leg.subject_id)
            if not (state.seconds_played[i] > 0 or any(state.stats[i])):
                continue  # An unknown DNP payout can change binary logic.
            axis = (leg.kind, leg.subject_id)
            fixed_stat = state.stats[i][PLAYER_STATS[leg.kind]]
            upper = fixed_stat if leg.subject_id in state.unavailable else math.inf
            lower = fixed_stat
        elif leg.kind == "total":
            axis = ("total", None)
            lower, upper = sum(state.score), math.inf
        else:
            axis = ("margin", None)
            lower, upper = -math.inf, math.inf
        low, high = bounds.get(axis, (lower, upper))
        if leg.kind in {"moneyline", "spread"} and leg.subject_id == state.teams[1]:
            if leg.side == "yes":
                high = min(high, -leg.minimum)
            else:
                low = max(low, 1 - leg.minimum)
        elif leg.side == "yes":
            low = max(low, leg.minimum)
        else:
            high = min(high, leg.minimum - 1)
        if low > high or (axis == ("margin", None) and low == high == 0):
            return True
        bounds[axis] = low, high
    for (kind, player), (point_low, point_high) in bounds.items():
        if kind != "points" or ("threes", player) not in bounds:
            continue
        threes_low, _ = bounds["threes", player]
        pts, _, _, threes, _ = state.stats[state.players.index(player)]
        if max(point_low, pts + 3 * max(0, threes_low - threes)) > point_high:
            return True
    return False


def path_outcomes(state, batch, legs):
    """Represent each selected leg as a path hit and flag possible DNP payouts."""
    if tuple(batch.players) != tuple(state.players):
        raise ValueError("Simulation player IDs are not aligned with the game state")
    hits = []
    known = []
    fixed = []
    for leg in legs:
        if leg.kind in PLAYER_STATS:
            j = state.players.index(leg.subject_id)
            k = PLAYER_STATS[leg.kind]
            y = batch.stats[:, j, k] >= leg.minimum
            participated = state.seconds_played[j] > 0 or any(state.stats[j])
            available = np.ones(len(y), dtype=bool) if participated else batch.seconds_played[:, j] > 0
            locked = True if state.stats[j][k] >= leg.minimum else (
                False if participated and leg.subject_id in state.unavailable else None)
        elif leg.kind == "total":
            y = batch.scores.sum(axis=1) >= leg.minimum
            available = np.ones(len(y), dtype=bool)
            locked = True if sum(state.score) >= leg.minimum else None
        else:
            j = state.teams.index(leg.subject_id)
            y = batch.scores[:, j] - batch.scores[:, 1 - j] >= leg.minimum
            available = np.ones(len(y), dtype=bool)
            locked = None
        selected_yes = leg.side == "yes"
        hits.append(y == selected_yes)
        known.append(available)
        fixed.append(None if locked is None else locked == selected_yes)
    return np.stack(hits, axis=1), np.stack(known, axis=1), tuple(fixed)


def fit_marginals(hits, target):
    """Reweight shared paths to the requested marginals without adding outcomes."""
    support, counts = np.unique(hits, axis=0, return_counts=True)
    weights = counts / counts.sum()
    masks = support.T
    if any((mask.all() and p < 1) or (not mask.any() and p > 0)
           for mask, p in zip(masks, target)):
        return None
    for _ in range(500):
        for mask, p in zip(masks, target):
            previous = float(weights[mask].sum())
            if previous <= 0 or previous >= 1:
                if abs(previous - p) > 1e-10:
                    return None
                continue
            weights[mask] *= p / previous
            weights[~mask] *= (1 - p) / (1 - previous)
        if np.max(np.abs(weights @ support - target), initial=0.) <= 1e-7:
            return float(weights[support.all(axis=1)].sum())
    return None


def price_combo(simulator, state, legs, *, yes_midpoints=None, paths_per_seed=4096,
                seed=0, max_anchored_seed_gap=.01):
    """Estimate combo YES and NO on shared paths, with optional market anchors.

    yes_midpoints holds pre-request YES bid/ask midpoints for verified legs.
    The caller supplies a reconciled as-of state and enforces quote freshness.
    """
    legs = tuple(legs)
    if not legs or any(leg.game_id != str(state.game_id) for leg in legs):
        raise ValueError("A combo needs at least one leg and every leg must match the state game")
    for leg in legs:
        ids = state.players if leg.kind in PLAYER_STATS else state.teams
        if leg.kind != "total" and leg.subject_id not in ids:
            raise ValueError(f"Verified subject absent from the game state: {leg.ticker}")
    if type(paths_per_seed) is not int or paths_per_seed < 1:
        raise ValueError("paths_per_seed must be a positive integer")
    if not 0 <= max_anchored_seed_gap <= 1:
        raise ValueError("The maximum anchored seed gap must be a probability")
    midpoints = dict(yes_midpoints or {})
    if set(midpoints) - {leg.ticker for leg in legs}:
        raise ValueError("Quote supplied for a market outside the combo")
    if any(not math.isfinite(float(p)) or not 0 < float(p) < 1 for p in midpoints.values()):
        raise ValueError("YES midpoints must be finite and strictly between zero and one")

    if type(seed) is not int or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    batches = [
        simulator.simulate(state, batch=paths_per_seed, seed=seed + i)
        for i in range(2)
    ]
    return price_shared_paths(state, legs, batches, midpoints, max_anchored_seed_gap)


def price_shared_paths(state, legs, batches, midpoints, max_anchored_seed_gap=.01):
    """Price a verified combo on two equal batches already shared by this state."""
    contradiction = impossible_combo(state, legs)
    per_seed = [path_outcomes(state, batch, legs) for batch in batches]
    paths_per_seed = len(per_seed[0][0])
    fixed = per_seed[0][2]
    hits = np.concatenate([part[0] for part in per_seed])
    known = np.concatenate([part[1] for part in per_seed])
    certainly_lost = ((~hits) & known).any(axis=1)
    certainly_won = (hits & known).all(axis=1)
    uncertain = ~(certainly_lost | certainly_won)
    lower, upper = float(certainly_won.mean()), float((~certainly_lost).mean())
    if contradiction and upper != 0.:
        raise RuntimeError("Simulated outcomes violated an exact combo contradiction")
    probability = lower if not uncertain.any() else None
    result = {
        "game_id": str(state.game_id),
        "legs": [{"ticker": leg.ticker, "kind": leg.kind, "side": leg.side,
                  "probability_if_binary": float(hits[known[:, j], j].mean()) if known[:, j].any() else None,
                  "possible_dnp_fraction": float((~known[:, j]).mean())}
                 for j, leg in enumerate(legs)],
        "paths": len(hits), "combo_hits": int(certainly_won.sum()),
        "standalone_status": "exact" if contradiction or False in fixed or None not in fixed else
        "possible_nonbinary_payout" if probability is None else
        "sample_boundary" if probability in (0., 1.) and None in fixed and False not in fixed else "estimated",
        "standalone_yes": probability, "standalone_no": None if probability is None else 1 - probability,
        "standalone_yes_bounds": [lower, upper],
        "standalone_seed_gap": abs(float(certainly_won[:paths_per_seed].mean()) -
                                   float(certainly_won[paths_per_seed:].mean())) if probability is not None else None,
        "anchored_yes": None, "anchored_no": None, "anchor_seed_gap": None,
        "anchor_status": "missing_midpoints",
    }
    if contradiction or False in fixed or None not in fixed:
        anchored = float(not contradiction and all(fixed))
        result.update(anchored_yes=anchored, anchored_no=1-anchored, anchor_status="exact")
        return result
    columns = [j for j, value in enumerate(fixed) if value is None]
    if not known.all():
        result["anchor_status"] = "possible_nonbinary_leg_payout"
        return result
    if any(legs[j].ticker not in midpoints for j in columns):
        return result
    target = np.asarray([float(midpoints[legs[j].ticker]) if legs[j].side == "yes"
                         else 1 - float(midpoints[legs[j].ticker]) for j in columns])
    pooled = fit_marginals(hits[:, columns], target)
    seed_prices = [fit_marginals(part[0][:, columns], target) for part in per_seed]
    if pooled is None or None in seed_prices:
        result["anchor_status"] = "midpoints_incompatible_with_simulated_support"
        return result
    if pooled <= 0 or pooled >= 1:
        result["anchor_status"] = "sample_boundary"
        return result
    gap = abs(seed_prices[0] - seed_prices[1])
    result["anchor_seed_gap"] = gap
    if gap > max_anchored_seed_gap:
        result["anchor_status"] = "split_seed_disagreement"
        return result
    result.update(anchored_yes=pooled, anchored_no=1-pooled, anchor_status="estimated")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON with state and normalized legs or RFQ metadata")
    parser.add_argument("--model", type=Path, required=True, help="Original frozen fitted_model.npz")
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--paths-per-seed", type=int, default=4096)
    args = parser.parse_args()
    if hashlib.sha256(args.model.read_bytes()).hexdigest() != MODEL_SHA256:
        parser.error("Model file does not match the frozen NBA simulator")
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    state = GameState.from_dict(data["state"])
    if "legs" in data:
        legs = tuple(Leg(**leg) for leg in data["legs"])
    else:
        legs = normalize_rfq(data["selections"], data["markets"], data["fixture"])
    result = price_combo(Simulator.load(args.model), state, legs, yes_midpoints=data.get("yes_midpoints"),
                         paths_per_seed=args.paths_per_seed, seed=args.seed)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
