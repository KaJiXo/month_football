"""
Attacking strategy packages and their defensive counters.

Each attacking strategy leans on a primary + secondary TEAM stat.
Each defensive counter leans on a primary TEAM stat and has a fixed
rock-paper-scissors relationship (beats / weak_vs) with attacking strategies.
"""

# name -> (primary_stat, secondary_stat, base_goal_chance)
ATTACK_STRATEGIES = {
    "Through Ball":        ("attack", "pace", 0.32),
    "Wing Cross":           ("pace", "attack", 0.28),
    "Long Shot":            ("attack", "consistency", 0.18),
    "Tiki-Taka Build-up":   ("consistency", "attack", 0.25),
    "Set Piece":            ("peak_power", "consistency", 0.22),
    "Counter-Press":        ("pace", "momentum", 0.30),
    "Individual Dribble":   ("attack", "peak_power", 0.26),
    "Overlap Run":          ("pace", "defense", 0.27),
}

# name -> (primary_stat(s), beats[], weak_vs[])
DEFENSE_COUNTERS = {
    "High Press":       (["pace"], ["Tiki-Taka Build-up", "Individual Dribble"], ["Through Ball", "Counter-Press"]),
    "Deep Block":       (["defense"], ["Through Ball", "Long Shot"], ["Tiki-Taka Build-up", "Set Piece"]),
    "Man-Marking":      (["consistency"], ["Individual Dribble", "Set Piece"], ["Wing Cross", "Overlap Run"]),
    "Zonal Defense":    (["defense", "consistency"], ["Wing Cross", "Overlap Run"], ["Individual Dribble"]),
    "Offside Trap":     (["pace", "momentum"], ["Through Ball", "Counter-Press"], ["Long Shot", "Set Piece"]),
    "Compact Midfield": (["consistency"], ["Tiki-Taka Build-up", "Overlap Run"], ["Long Shot", "Individual Dribble"]),
}


def matchup_modifier(counter: str, attack_strategy: str) -> float:
    _, beats, weak_vs = DEFENSE_COUNTERS[counter]
    if attack_strategy in beats:
        return 0.6
    if attack_strategy in weak_vs:
        return 1.4
    return 1.0


def stat_value(team, stat_name: str) -> float:
    """Read a named stat off a Team object (all exposed as properties)."""
    return getattr(team, stat_name)


def attacker_stat(team, strategy: str) -> float:
    primary, secondary, _ = ATTACK_STRATEGIES[strategy]
    return 0.7 * stat_value(team, primary) + 0.3 * stat_value(team, secondary)


def defender_stat(team, counter: str) -> float:
    primaries, *_ = DEFENSE_COUNTERS[counter]
    return mean_stats(team, primaries)


def mean_stats(team, stat_names):
    vals = [stat_value(team, s) for s in stat_names]
    return sum(vals) / len(vals)
