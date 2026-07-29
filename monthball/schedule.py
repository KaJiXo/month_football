"""
Fixture list generation.

Regular season: double round-robin (circle method) among the 12 teams
(months) -> each team plays every other team twice (home & away) = 22
games/team, 132 total, split into two "rounds" of 11 matchdays each.
Mid-season transfer window fires between round 1 and round 2.

Playoffs: seeds 1-2 bye to semis; seeds 3-6 play a knockout (3v6, 4v5) for
the remaining 2 semifinal spots; then semis, final, and 3rd-place playoff.
"""
import itertools


def round_robin_single(team_names):
    """Circle method: returns list of matchdays, each a list of (home, away) pairs."""
    names = list(team_names)
    if len(names) % 2:
        names.append(None)  # bye
    n = len(names)
    matchdays = []
    fixed = names[0]
    rotating = names[1:]

    for round_num in range(n - 1):
        pairing_order = [fixed] + rotating
        matchday = []
        for i in range(n // 2):
            a, b = pairing_order[i], pairing_order[n - 1 - i]
            if a is not None and b is not None:
                home, away = (a, b) if round_num % 2 == 0 else (b, a)
                matchday.append((home, away))
        matchdays.append(matchday)
        rotating = [rotating[-1]] + rotating[:-1]  # rotate

    return matchdays


def build_double_round_robin(team_names):
    round1 = round_robin_single(team_names)
    # round2 = same pairings, home/away swapped
    round2 = [[(away, home) for (home, away) in matchday] for matchday in round1]
    return round1, round2


def make_playoff_bracket(standings):
    """
    standings: list of team names ordered 1st..12th (or however many).
    Returns dict describing the knockout stage structure (fixtures filled
    in as results come in by season.py).
    """
    seeds = {i + 1: name for i, name in enumerate(standings[:6])}
    return {
        "byes": [seeds[1], seeds[2]],
        "play_in": [
            {"home": seeds[3], "away": seeds[6], "label": "3v6"},
            {"home": seeds[4], "away": seeds[5], "label": "4v5"},
        ],
        "seeds": seeds,
    }
