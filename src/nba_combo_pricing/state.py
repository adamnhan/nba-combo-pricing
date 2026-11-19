"""Historical event reconstruction for the offline NBA simulator."""
from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
import pandas as pd

CHECKPOINTS = ((1, 360), (2, 360), (3, 360), (4, 360), (4, 120))

STAT_NAMES = ("points", "rebounds", "assists", "three_point_field_goals_made", "fouls")
PLAY_COLUMNS = (
    "game_id", "game_play_number", "event_id_original", "period_number",
    "clock_display_value", "type_text", "text", "team_id", "athlete_id_1",
    "athlete_id_2", "athlete_id_3", "scoring_play", "shooting_play",
    "score_value", "home_score", "away_score", "source_event_time_utc",
)
BOX_COLUMNS = (
    "game_id", "team_id", "athlete_id", "minutes", "did_not_play",
    *STAT_NAMES, "field_goals_attempted", "field_goals_made",
    "three_point_field_goals_attempted", "free_throws_made",
    "free_throws_attempted", "offensive_rebounds", "turnovers",
)
PERSONAL_FOULS = {
    "Away from Play Foul", "Clear Path Foul", "Double Personal Foul",
    "Flagrant Foul Type 1", "Flagrant Foul Type 2", "Loose Ball Foul",
    "Offensive Charge", "Offensive Foul", "Personal Foul",
    "Personal Take Foul", "Shooting Foul", "Transition Take Foul",
}
BREAKS = tuple(720 * i for i in range(5))


@dataclass(frozen=True)
class GameState:
    """Two teams in home/away order, with all player IDs aligned to players."""
    game_id: str
    period: int
    clock_seconds: float
    teams: tuple
    score: tuple
    players: tuple
    player_team: tuple
    starters: tuple
    lineups: tuple
    seconds_played: tuple
    stats: tuple
    unavailable: tuple = ()
    last_play_number: int | None = None
    source_event_time_utc: str | None = None
    receipt_time_utc: str | None = None
    prior_minutes: tuple | None = None

    @classmethod
    def from_dict(cls, data):
        values = dict(data)
        for name in ("teams", "score", "players", "player_team", "starters",
                     "seconds_played", "unavailable", "prior_minutes"):
            if values.get(name) is not None:
                values[name] = tuple(values[name])
        for name in ("lineups", "stats"):
            values[name] = tuple(tuple(row) for row in values[name])
        return cls(**values)

    @property
    def elapsed(self):
        return elapsed_at(self.period, self.clock_seconds)


def elapsed_at(period, clock):
    if period <= 4:
        return 720 * period - clock
    return 2880 + 300 * (period - 4) - clock


def read_season(archive, season):
    games = pd.read_parquet(archive / "games.parquet", filters=[("season_end", "==", season)])
    team_ids = {str(team) for team in range(1, 31)}
    games = games.loc[
        games.completed & games.season_type.eq(2) & games.home_id.isin(team_ids)
        & games.away_id.isin(team_ids)
    ].drop_duplicates("game_id").sort_values(["scheduled_start_utc", "game_id"])
    partition = f"season_end={season}"
    tables = {}
    for name, file, columns in (
        ("pbp", "events.parquet", PLAY_COLUMNS),
        ("player_box", "data.parquet", BOX_COLUMNS),
        ("retrospective_starters", "data.parquet", ["game_id", "team_id", "athlete_id"]),
    ):
        table = pd.read_parquet(archive / name / partition / file, columns=list(columns))
        table["game_id"] = table.game_id.astype(str)
        tables[name] = table[table.game_id.isin(games.game_id)]
    plays = tables["pbp"]
    clock = plays.clock_display_value.str.extract(r"^(?:(\d+):)?(\d+(?:\.\d+)?)$")
    plays = plays.assign(seconds=clock[0].fillna(0).astype(float) * 60 + clock[1].astype(float))
    plays = plays.sort_values(["game_id", "game_play_number"], kind="stable")
    grouped = [dict(iter(frame.groupby("game_id", sort=False))) for frame in (
        plays, tables["player_box"], tables["retrospective_starters"],
    )]
    return games, grouped


def player_id(value):
    return int(value) if pd.notna(value) else None


def reconstruct(game, plays, box, starter_rows, prior_rosters, *, event_ids=(), event_states=None):
    teams = (int(game.home_id), int(game.away_id))
    expected_score = (int(game.home_final), int(game.away_final))
    game_id = str(game.game_id)
    audit = Counter()
    states = {}
    if plays is None:
        audit["no_pbp"] += 1
    if box is None:
        audit["no_box"] += 1
    if starter_rows is None:
        audit["no_starters"] += 1
    if audit:
        return states, {}, {}, audit

    starters = tuple(set(starter_rows.loc[starter_rows.team_id.eq(t), "athlete_id"].astype(int))
                     for t in teams)
    if any(len(s) != 5 for s in starters) or starters[0] & starters[1]:
        audit["invalid_starters"] += 1
        return states, {}, {}, audit
    lineups = [s.copy() for s in starters]
    observed = [s.copy() for s in starters]
    stats = defaultdict(lambda: [0] * 5)
    seconds = defaultdict(float)
    regulation = None
    elapsed = 0.0
    highest = 0.0
    score = (0, 0)
    player_running_score = [0, 0]
    last = None
    broken = False
    unavailable = set()
    last_foul = {}
    cutoffs = [(elapsed_at(p, c), p, c) for p, c in CHECKPOINTS]
    next_cutoff = 0
    final_period = 0
    seen_ids = set()

    def accrue(end):
        nonlocal elapsed, regulation
        end = max(elapsed, end)
        if elapsed < 2880 <= end:
            regulation = dict(seconds)
            for lineup in lineups:
                for player in lineup:
                    regulation[player] = regulation.get(player, 0) + 2880 - elapsed
        if end > elapsed:
            for lineup in lineups:
                for player in lineup:
                    seconds[player] += end - elapsed
        elapsed = end

    def snapshot(period, clock):
        roster_home = observed[0] | (prior_rosters.get(teams[0], set()) - observed[1])
        roster_away = (observed[1] | prior_rosters.get(teams[1], set())) - roster_home
        players = tuple(sorted(roster_home) + sorted(roster_away))
        stamp = last.source_event_time_utc if last is not None else None
        return GameState(
            game_id, period, clock, teams, score, players,
            (0,) * len(roster_home) + (1,) * len(roster_away),
            tuple(p in starters[0] or p in starters[1] for p in players),
            tuple(tuple(sorted(s)) for s in lineups),
            tuple(seconds.get(p, 0.0) for p in players),
            tuple(tuple(stats[p]) for p in players),
            tuple(sorted(unavailable)),
            int(last.game_play_number) if last is not None else None,
            stamp.isoformat() if pd.notna(stamp) else None,
        )

    for row in plays.itertuples(index=False):
        audit["events"] += 1
        audit["events_with_source_timestamp"] += int(pd.notna(row.source_event_time_utc))
        if pd.isna(row.period_number) or not math.isfinite(row.seconds):
            audit["invalid_clock_events"] += 1
            broken = True
            continue
        period = int(row.period_number)
        final_period = max(final_period, period)
        event_elapsed = elapsed_at(period, row.seconds)
        while next_cutoff < len(cutoffs) and event_elapsed >= cutoffs[next_cutoff][0]:
            cutoff, checkpoint_period, checkpoint_clock = cutoffs[next_cutoff]
            accrue(cutoff)
            key = (checkpoint_period, checkpoint_clock)
            audit[f"checkpoint_reached_{checkpoint_period}_{checkpoint_clock}"] += 1
            if not broken and last is not None and tuple(player_running_score) == score:
                states[key] = snapshot(checkpoint_period, checkpoint_clock)
            else:
                audit[f"checkpoint_prefix_failed_{checkpoint_period}_{checkpoint_clock}"] += 1
            next_cutoff += 1

        if event_elapsed + 0.11 < highest:
            audit["clock_reversals"] += 1
            broken = True
        highest = max(highest, event_elapsed)
        accrue(event_elapsed)
        if row.event_id_original in seen_ids:
            audit["duplicate_events"] += 1
            continue
        seen_ids.add(row.event_id_original)
        team = player_id(row.team_id)
        side = teams.index(team) if team in teams else None
        first, second, third = map(player_id, (row.athlete_id_1, row.athlete_id_2, row.athlete_id_3))
        kind = row.type_text or ""
        if kind == "Substitution":
            audit["substitution_events"] += 1
            if None in (side, first, second):
                audit["incomplete_substitution_events"] += 1
                broken = True
            elif second not in lineups[side] or first in lineups[side] or first in observed[1 - side]:
                audit["substitution_membership_errors"] += 1
                broken = True
            else:
                lineups[side].remove(second)
                lineups[side].add(first)
                observed[side].add(first)
        if side is not None and first is not None and kind != "Substitution":
            if row.scoring_play or kind in ("Defensive Rebound", "Offensive Rebound"):
                if first not in lineups[side]:
                    audit["off_court_stat_actors"] += 1
                    broken = True
                observed[side].add(first)
            if row.scoring_play:
                pts = int(row.score_value or 0)
                stats[first][0] += pts
                player_running_score[side] += pts
                stats[first][3] += pts == 3
                if pts >= 2 and second is not None and " assists" in (row.text or ""):
                    stats[second][2] += 1
                    if second not in lineups[side]:
                        audit["off_court_stat_actors"] += 1
                        broken = True
                    observed[side].add(second)
            if kind in ("Defensive Rebound", "Offensive Rebound"):
                stats[first][1] += 1
            if kind in PERSONAL_FOULS:
                foul_players = (first, second) if kind == "Double Personal Foul" else (first,)
                for player in foul_players:
                    if player is not None and last_foul.get(player) != (event_elapsed, kind):
                        stats[player][4] += 1
                        last_foul[player] = (event_elapsed, kind)
            if kind == "Ejection":
                unavailable.add(first)
        if pd.notna(row.home_score) and pd.notna(row.away_score):
            score = (int(row.home_score), int(row.away_score))
        last = row
        if (event_states is not None and row.game_play_number in event_ids
                and not broken and tuple(player_running_score) == score):
            event_states[int(row.game_play_number)] = snapshot(period, min(row.seconds, max(
                0, elapsed_at(period, 0) - elapsed,
            )))

    final_elapsed = elapsed_at(max(4, final_period), 0)
    if highest < final_elapsed - .11 or final_period < 4:
        audit["no_final_clock"] += 1
    accrue(final_elapsed)
    audit["schedule_score_fail"] = int(not game.score_reconciles or game.score_source_conflict)
    audit["final_score_fail"] = int(score != expected_score)
    audit["player_score_fail"] = int(tuple(player_running_score) != expected_score)
    audit["lineup_path_fail"] = int(broken)
    audit["overtime_games"] = int(final_period > 4)

    truth = {}
    for row in box.itertuples(index=False):
        if pd.isna(row.athlete_id):
            audit["box_rows_without_player_id"] += 1
            continue
        pid = int(row.athlete_id)
        expected = tuple(getattr(row, c) for c in STAT_NAMES)
        if not row.did_not_play and (pd.isna(row.minutes) or any(pd.isna(v) for v in expected)):
            audit["missing_box_labels"] += 1
        if pd.notna(row.minutes):
            audit["minutes_players"] += 1
            difference = abs(seconds.get(pid, 0) - row.minutes * 60)
            audit["minutes_absolute_error_seconds"] += difference
            if difference > 60.01:
                audit["minutes_players_over_60s"] += 1
            if difference > 300:
                audit["minutes_players_over_300s"] += 1
        if row.did_not_play:
            if seconds.get(pid, 0) > .01:
                audit["dnp_with_reconstructed_minutes"] += 1
            continue
        truth[pid] = expected
        for i, label in enumerate(STAT_NAMES):
            if pd.notna(expected[i]):
                audit[f"{label}_players"] += 1
                audit[f"{label}_mismatch_players"] += int(stats[pid][i] != expected[i])

    box_ids = set(box.athlete_id)
    audit["unlisted_players"] += len((observed[0] | observed[1]) - box_ids)
    audit["minutes_game_fail"] = int(bool(audit["minutes_players_over_60s"] or
                                          audit["dnp_with_reconstructed_minutes"]))
    audit["lineup_game_pass"] = int(not any(audit[key] for key in (
        "lineup_path_fail", "minutes_game_fail", "unlisted_players", "no_final_clock",
    )))
    audit["core_stat_game_pass"] = int(not any(audit[key] for key in (
        "missing_box_labels", "points_mismatch_players", "rebounds_mismatch_players",
        "assists_mismatch_players", "three_point_field_goals_made_mismatch_players",
        "player_score_fail", "final_score_fail", "schedule_score_fail",
    )))
    audit["foul_game_pass"] = int(not audit["fouls_mismatch_players"])
    return states, regulation or {}, truth, audit
