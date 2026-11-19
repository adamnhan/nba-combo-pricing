"""Sample coherent full-game NBA outcomes from one observed game state."""
from dataclasses import dataclass

import numpy as np

from .state import GameState


@dataclass(frozen=True)
class SimulationBatch:
    players: tuple
    scores: np.ndarray
    stats: np.ndarray  # points, rebounds, assists, made threes
    seconds_played: np.ndarray
    regulation_seconds_played: np.ndarray
    overtime_periods: np.ndarray


def rotation_features(state, prior):
    left = max(0.0, (2880 - state.elapsed) / 60)
    played = np.asarray(state.seconds_played) / 60
    current = np.isin(state.players, state.lineups[0] + state.lineups[1])
    starter = np.asarray(state.starters)
    side = np.asarray(state.player_team)
    margin = np.diff(state.score)[0]
    signed = np.where(side == 0, -margin, margin) / 20
    blowout = np.clip(np.abs(signed) - .5, 0, 1.5)
    fouls = np.asarray(state.stats)[:, 4]
    foul_risk = np.maximum(0, fouls - max(1, state.period - 1))
    role = prior / 30
    used = played > 0
    horizon = left / 24
    pace_minutes = played / max(1, state.elapsed / 60)
    return np.column_stack((
        np.ones(len(played)), role, role**2, starter, current, used, pace_minutes,
        played / 24, horizon * role, starter * horizon, current * horizon,
        blowout, blowout * role, blowout * starter, signed, signed * role,
        foul_risk, foul_risk * role, fouls == 5, (~used) * role,
    ))


def box_prior(state, history):
    """Minutes from the current team's recent completed games, with role fallback."""
    return np.array([
        history.get((state.teams[t], p), 30.0 if starter else (13.0 if played else 4.0))
        for p, t, starter, played in zip(
            state.players, state.player_team, state.starters, state.seconds_played,
        )
    ])


def balance(values, cap, total):
    """Project rows to a capped simplex by solving for a shared shift."""
    low = (values - cap).min(axis=1, keepdims=True)
    high = values.max(axis=1, keepdims=True)
    for _ in range(21):
        middle = (low + high) / 2
        need_more = np.clip(values - middle, 0, cap).sum(axis=1, keepdims=True) < total
        high = np.where(need_more, middle, high)
        low = np.where(need_more, low, middle)
    return np.clip(values - (low + high) / 2, 0, cap)


class RotationModel:
    def __init__(self, examples):
        self.coefficients = {}
        self.residuals = {}
        for key, records in examples.items():
            design = np.concatenate([record[0] for record in records])
            target = np.concatenate([record[1] for record in records])
            penalty = np.eye(design.shape[1]) * 5
            penalty[0, 0] = 0
            coef = np.linalg.solve(design.T @ design + penalty, design.T @ target)
            self.coefficients[key] = coef
            banks = {}
            for features, truth, role, margin in records:
                for group in (0, 1):
                    mask = features[:, 3] == group
                    order = np.argsort(-role[mask], kind="stable")
                    residual = (truth - features @ coef)[mask][order]
                    banks.setdefault((group, margin), []).append(np.pad(
                        residual[:18], (0, max(0, 18 - len(residual))), constant_values=0,
                    ))
            self.residuals[key] = {k: np.array(v) for k, v in banks.items()}
        if not self.coefficients:
            raise ValueError("No eligible training checkpoints.")

    def anchor(self, state):
        left = max(0, 2880 - state.elapsed)
        return min(self.coefficients, key=lambda key: abs(2880 - (720 * key[0] - key[1]) - left))

    def predict(self, state, prior, indices, rng, batch, baseline=False):
        key = self.anchor(state)
        left = max(0, 2880 - state.elapsed) / 60
        anchor_left = (2880 - (720 * key[0] - key[1])) / 60
        features = rotation_features(state, prior)[indices]
        if baseline:
            raw = prior[indices] * left / 48
        else:
            raw = features @ self.coefficients[key] * (left / anchor_left)
        values = np.broadcast_to(raw, (batch, len(raw))).copy()
        margin_group = min(2, abs(state.score[0] - state.score[1]) // 10)
        if not baseline:
            for group in (0, 1):
                members = np.flatnonzero(features[:, 3] == group)
                order = members[np.argsort(-prior[indices][members], kind="stable")]
                bank = self.residuals[key].get((group, margin_group))
                if bank is None or len(bank) < 12:
                    bank = np.concatenate([v for (g, _), v in self.residuals[key].items() if g == group])
                ranks = np.minimum(np.arange(len(order)), bank.shape[1] - 1)
                values[:, order] += bank[rng.integers(len(bank), size=batch)[:, None], ranks] * (left / anchor_left)
        return values * 60


def eligible_indices(state, side):
    player_side = np.asarray(state.player_team)
    fouls = np.asarray(state.stats)[:, 4]
    allowed = ~np.isin(state.players, state.unavailable)
    return np.flatnonzero((player_side == side) & allowed & (fouls < 6))


def choose_lineups(state, rotation, prior, batch, rng, left, overtime=False):
    """Allocate exact five-player blocks from constrained sampled minutes."""
    steps = max(1, int(np.ceil(left / 30)))
    duration = left / steps
    schedule = np.empty((2, batch, steps, 5), dtype=np.int32)
    played = np.zeros((batch, len(state.players)))
    state_players = np.array(state.players)
    for side in (0, 1):
        indices = eligible_indices(state, side)
        if len(indices) < 5:
            raise ValueError("At least five eligible players are required per team.")
        current = np.isin(state_players[indices], state.lineups[side])
        keep_current = current.sum() == 5 and not overtime
        if overtime:
            order = np.argsort(-(prior[indices] + current * 5))
            raw = np.broadcast_to(np.maximum(0, 8 - 1.65 * np.argsort(order)), (batch, len(indices)))
            raw = raw * steps / 6 + rng.normal(0, .30, (batch, len(indices)))
        else:
            raw = rotation.predict(state, prior, indices, rng, batch) / duration
        begin = int(keep_current)
        if keep_current:
            schedule[side, :, 0] = indices[current]
            raw = raw - current
        quota_float = balance(raw, steps - begin, 5 * (steps - begin))
        quota_floor = np.floor(quota_float + 1e-7).astype(int)
        short = 5 * (steps - begin) - quota_floor.sum(axis=1)
        remainder = np.argsort(-(quota_float - quota_floor), axis=1, kind="stable")
        add = np.argsort(remainder, axis=1) < short[:, None]
        quota = quota_floor + add
        if not np.all(quota.sum(axis=1) == 5 * (steps - begin)) or np.any(quota > steps - begin):
            raise RuntimeError("Invalid rotation quota.")
        if keep_current:
            quota += current
        played[:, indices] = quota * duration
        if keep_current:
            quota -= current
        previous = np.broadcast_to(current, quota.shape).copy()
        for step in range(begin, steps):
            remaining = steps - step
            forced = quota == remaining
            priority = quota / remaining + .40 * previous + rng.uniform(0, .35, quota.shape)
            if not overtime and state.elapsed + step * duration >= 2520:
                priority += .15 * (prior[indices] / 30)
            priority = np.where(forced, np.inf, np.where(quota > 0, priority, -np.inf))
            chosen = np.argpartition(priority, -5, axis=1)[:, -5:]
            schedule[side, :, step] = indices[chosen]
            previous.fill(False)
            np.put_along_axis(previous, chosen, True, axis=1)
            quota -= previous
        if np.any(quota):
            raise RuntimeError("Lineup allocation did not use the planned minutes.")
    return schedule, played, duration


# Historical per-player weights and field-goal rates use only fitting-season boxes.
RATE_COLUMNS = (
    "field_goals_attempted", "field_goals_made", "three_point_field_goals_attempted",
    "three_point_field_goals_made", "free_throws_attempted", "free_throws_made",
    "assists", "offensive_rebounds", "rebounds", "turnovers",
)
TEAM_RATE_COLUMNS = (
    "field_goals_attempted", "field_goals_made", "three_point_field_goals_attempted",
    "three_point_field_goals_made", "free_throws_attempted", "free_throws_made",
    "assists", "offensive_rebounds", "defensive_rebounds", "total_turnovers",
)


def rate_components(counts):
    fga, fgm, three_a, three_m, fta, ftm, assists, orebs, rebs, tov = np.moveaxis(counts, -1, 0)
    weights = np.stack((fga - three_a, three_a, fta, assists, orebs, rebs - orebs, tov), axis=-1)
    makes = np.stack((fgm - three_m, three_m, ftm), axis=-1)
    return weights, makes


class EventModel:
    def __init__(self, players, team_rows, player_games):
        total = np.sum(np.array(list(players.values())), axis=0)
        self.prior = total[1:] / total[0]
        self.players = players
        self.typical_minutes = {p: float(r[0] / player_games[p]) for p, r in players.items()}
        # Rows are per game and adjusted to regulation length before pooling.
        values = np.array([r[2] for r in team_rows])
        fga, fgm, three_a, three_m, fta, ftm, assists, orebs, drebs, turnovers = values.T
        self.pace = np.mean(fga + .44 * fta - orebs + turnovers) / 48
        self.oreb = orebs.sum() / (fga - fgm).sum()
        self.rebound = min(1, (orebs + drebs).sum() / (fga - fgm + .44 * (fta - ftm)).sum())
        self.assist = assists.sum() / fgm.sum()
        # 2.0 is the v1 fixed trip length. Compensate for FT-miss putbacks in the action mix.
        self.actions = np.array([fga.mean(), fta.mean() / 2, turnovers.mean()])
        self.actions /= self.actions.sum()
        self.context = {}
        scored = 2 * (fgm - three_m) + 3 * three_m + ftm
        by_game = {}
        for i, (gid, team, _) in enumerate(team_rows):
            by_game.setdefault(gid, {})[team] = scored[i]
        defense_rate = np.array([
            sum(by_game[gid].values()) - scored[i]
            for i, (gid, _, _) in enumerate(team_rows)
        ])
        league = defense_rate.mean()
        for team in {r[1] for r in team_rows}:
            mask = np.array([r[1] == team for r in team_rows])
            self.context[team] = float((defense_rate[mask] - league).sum() / (mask.sum() + 75) / 400)


    def rates(self, state):
        rows = np.array([self.players.get(p, np.zeros(11)) for p in state.players])
        weights, makes = rate_components(rows[:, 1:] + self.prior * 240)
        makes = np.clip(makes / weights[:, :3], .05, .97)
        weights /= rows[:, :1] + 240
        return np.maximum(weights, .001), makes


def weighted_player(lineups, weights, rng, exclude=None):
    w = weights[lineups]
    if exclude is not None:
        w = np.where(lineups == exclude[:, None], 0, w)
    cum = w.cumsum(axis=1)
    pick = (cum < rng.random(len(w))[:, None] * cum[:, -1:]).sum(axis=1)
    return lineups[np.arange(len(w)), pick]


class Simulator:
    def __init__(self, rotation, events):
        self.rotation = rotation
        self.events = events

    def save(self, path):
        """Save a fitted model as portable arrays. The archive is not needed to load it."""
        payload = {
            "ids": np.array(sorted(self.events.players), dtype=np.int64),
            "prior": self.events.prior,
            "actions": self.events.actions,
            "event_parameters": np.array([
                self.events.pace, self.events.oreb, self.events.rebound, self.events.assist,
            ]),
            "defense": np.array(list(self.events.context.items())),
            "checkpoints": np.array(list(self.rotation.coefficients)),
        }
        payload["player_rates"] = np.array([self.events.players[p] for p in payload["ids"]])
        payload["player_minutes"] = np.array([self.events.typical_minutes[p] for p in payload["ids"]])
        for j, key in enumerate(payload["checkpoints"]):
            key = tuple(key)
            payload[f"coef_{j}"] = self.rotation.coefficients[key]
            for (role, margin), data in self.rotation.residuals[key].items():
                payload[f"resid_{j}_{role}_{margin}"] = data
        np.savez_compressed(path, **payload)

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as payload:
            rotation = RotationModel.__new__(RotationModel)
            rotation.coefficients = {}
            rotation.residuals = {}
            for j, key in enumerate(payload["checkpoints"]):
                key = tuple(key)
                rotation.coefficients[key] = payload[f"coef_{j}"]
                rotation.residuals[key] = {
                    (r, m): payload[f"resid_{j}_{r}_{m}"]
                    for r in (0, 1) for m in (0, 1, 2)
                    if f"resid_{j}_{r}_{m}" in payload
                }
            events = EventModel.__new__(EventModel)
            events.players = dict(zip(payload["ids"], payload["player_rates"]))
            events.typical_minutes = dict(zip(payload["ids"], payload["player_minutes"]))
            events.prior = payload["prior"]
            events.actions = payload["actions"]
            events.pace, events.oreb, events.rebound, events.assist = payload["event_parameters"]
            events.context = dict(payload["defense"])
        return cls(rotation, events)

    def _segment(self, state, prior, n, seconds, rng, overtime=False):
        schedule, minutes, duration = choose_lineups(
            state, self.rotation, prior, n, rng, seconds, overtime,
        )
        num_players = len(state.players)
        stats = np.zeros((n, num_players, 4), dtype=np.int32)
        weights, make = self.events.rates(state)
        steps = schedule.shape[2]
        left = seconds / 60
        clocked = min(state.elapsed / 60, 48)
        live_rate_delta = (sum(state.score) - 4.73 * clocked) / (clocked + 44)
        pace_factor = np.clip(1 + .065 * live_rate_delta, .89, 1.11)
        # Shared pace across both teams and separate shooting noise within a path.
        pace = self.events.pace * pace_factor
        if left < .5:
            count_both = rng.poisson(2 * pace * left, n)
        else:
            counts = rng.normal(pace * left, np.sqrt(left) * .68, n)
            counts = np.maximum(0, np.rint(counts)).astype(int)
            count_both = 2 * counts + rng.integers(0, 2, n)
        scenario = np.repeat(np.arange(n), count_both)
        offsets = np.r_[0, np.cumsum(count_both)[:-1]]
        sequence = np.arange(len(scenario)) - offsets[scenario]
        step = ((sequence + rng.random(len(scenario))) * steps / count_both[scenario]).astype(int)
        offense = (sequence + rng.integers(0, 2, n)[scenario]) % 2
        efficiency = rng.normal(0, .020, (n, 2))
        efficiency[:, 0] += .006 - self.events.context.get(state.teams[1], 0)
        efficiency[:, 1] -= .006 + self.events.context.get(state.teams[0], 0)
        efficiency += .035 * live_rate_delta

        def credit(which, player, channel, value=1):
            linear = which * num_players + player
            weight = None if np.isscalar(value) else value
            counts = np.bincount(linear, weights=weight, minlength=n * num_players)
            multiplier = value if weight is None else 1
            stats[:, :, channel] += counts.reshape(n, num_players).astype(np.int32) * multiplier

        while len(scenario):
            o = schedule[offense, scenario, step]
            d = schedule[1 - offense, scenario, step]
            action = rng.choice(3, size=len(scenario), p=self.events.actions)
            ft = action == 1
            shot = action == 0
            share = weights[o, 1].sum(axis=1) / weights[o, :2].sum(axis=(1, 2))
            three = shot & (rng.random(len(o)) < share)
            channel = np.where(ft, 2, three.astype(int))
            shooters = np.empty(len(o), dtype=np.int32)
            for i in range(3):
                mask = (channel == i) & (action != 2)
                shooters[mask] = weighted_player(o[mask], weights[:, i], rng)
            scored = np.zeros(len(o), dtype=bool)
            fg_indices = np.flatnonzero(shot)
            chance = make[shooters[shot], channel[shot]] + efficiency[scenario[shot], offense[shot]]
            makes = rng.random(len(fg_indices)) < np.clip(chance, .02, .98)
            scored[fg_indices] = makes
            credit(scenario[scored], shooters[scored], 0, 2 + three[scored])
            made_three = scored & three
            credit(scenario[made_three], shooters[made_three], 3)
            assisted = scored & (rng.random(len(o)) < self.events.assist)
            helpers = weighted_player(o[assisted], weights[:, 3], rng, shooters[assisted])
            credit(scenario[assisted], helpers, 2)
            ft_hits = rng.random((ft.sum(), 2)) < make[shooters[ft], 2, None]
            credit(scenario[ft], shooters[ft], 0, ft_hits.sum(axis=1))
            miss = shot & ~scored
            miss[ft] = ~ft_hits[:, 1]
            # Both credited and team-control offensive boards can extend a possession.
            retained = miss & (rng.random(len(o)) < np.where(ft, .12, self.events.oreb))
            credited = miss & (rng.random(len(o)) < self.events.rebound)
            for own in (False, True):
                mask = credited & (retained == own)
                rebounder = weighted_player((o if own else d)[mask], weights[:, 4 if own else 5], rng)
                credit(scenario[mask], rebounder, 1)
            scenario, step, offense = scenario[retained], step[retained], offense[retained]
        return stats, minutes


    def simulate(self, state: GameState, *, batch=1000, seed=0):
        """Return final paths, including overtime, for one game state."""
        if not isinstance(batch, int) or batch < 1:
            raise ValueError("batch must be a positive integer.")
        p = len(state.players)
        role_prior = state.prior_minutes
        if role_prior is None:
            role_prior = [
                self.events.typical_minutes.get(p, 30.0 if starter else (13.0 if played else 4.0))
                for p, starter, played in zip(state.players, state.starters, state.seconds_played)
            ]
        prior = np.asarray(role_prior, dtype=float)
        if prior.shape != (p,) or not np.isfinite(prior).all() or np.any(prior < 0):
            raise ValueError("Provide one finite, nonnegative prior per player.")
        sides = np.asarray(state.player_team)
        seconds = np.asarray(state.seconds_played, dtype=float)
        initial_stats = np.asarray(state.stats)
        max_clock = 720 if state.period <= 4 else 300
        if (state.period < 1 or not 0 <= state.clock_seconds <= max_clock
                or sides.shape != (p,) or not np.isin(sides, (0, 1)).all()
                or len(set(state.players)) != p or seconds.shape != (p,)
                or not np.isfinite(seconds).all() or (seconds < 0).any()
                or initial_stats.shape != (p, 5) or (initial_stats < 0).any()
                or len(state.starters) != p or len(state.teams) != 2
                or len(set(state.teams)) != 2 or len(state.score) != 2
                or len(state.lineups) != 2):
            raise ValueError("Invalid clock or player state.")
        for side, lineup in enumerate(state.lineups):
            if len(set(lineup)) != 5 or not set(lineup).issubset(np.asarray(state.players)[sides == side]):
                raise ValueError("Each team requires five distinct on-court players.")
            if not np.isclose(seconds[sides == side].sum(), 5 * state.elapsed, atol=.15, rtol=0):
                raise ValueError("Elapsed player seconds must reconcile to team seconds.")
        if any(initial_stats[sides == side, 0].sum() != score for side, score in enumerate(state.score)):
            raise ValueError("Initial player points must reconcile to team scores.")
        if (initial_stats[:, 3] * 3 > initial_stats[:, 0]).any():
            raise ValueError("Made threes must reconcile to initial player points.")

        rng = np.random.default_rng(seed)
        stats = np.broadcast_to(initial_stats[:, :4], (batch, p, 4)).copy()
        played = np.broadcast_to(seconds, (batch, p)).copy()
        ot = np.full(batch, max(0, state.period - 4), dtype=np.int32)
        left = 2880 - state.elapsed if state.period <= 4 else state.clock_seconds
        if left > 0:
            added, more = self._segment(state, prior, batch, left, rng, overtime=state.period > 4)
            stats += added
            played += more
        regulation = played.copy() if state.period <= 4 else np.full_like(played, np.nan)

        def scores():
            return np.stack([stats[:, sides == side, 0].sum(axis=1) for side in (0, 1)], axis=1)

        final = scores()
        tied = np.flatnonzero(final[:, 0] == final[:, 1])
        while len(tied):
            added, more = self._segment(state, prior, len(tied), 300, rng, overtime=True)
            stats[tied] += added
            played[tied] += more
            ot[tied] += 1
            final = scores()
            tied = np.flatnonzero(final[:, 0] == final[:, 1])
        return SimulationBatch(state.players, final, stats, played, regulation, ot)
