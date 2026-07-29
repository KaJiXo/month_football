"""
Match engine.

Per half: 4 strategy exchanges, attacker alternates each exchange.
After each half: decaying chance (50%, 25%, 12.5%, ...) of one more
extra-time exchange round, resisted by the attacking-at-the-time team's
`resilience` stat (higher resilience -> less likely extra time is even rolled
against them, modelled as a small negative bias on the coin flip).

Defensive strategy is NOT random: each team keeps a running record of how
often each counter has stopped each attacking strategy (globally, across all
matches it has defended) and uses epsilon-greedy selection over that record.
"""
import random

from .strategies import (
    ATTACK_STRATEGIES, DEFENSE_COUNTERS, matchup_modifier,
    attacker_stat, defender_stat,
)

EPSILON = 0.15               # chance the defending AI explores a random counter
COUNTERATTACK_CHANCE = 0.35  # chance a failed attack flips into a turnover chance


def _pick_defense_counter(defending_team, attack_strategy: str) -> str:
    stats = defending_team.defense_stats.setdefault(attack_strategy, {})
    if random.random() < EPSILON or not stats:
        return random.choice(list(DEFENSE_COUNTERS.keys()))

    def stop_rate(counter):
        uses, stops = stats.get(counter, [0, 0])
        if uses == 0:
            return 0.5  # unknown = treated as average, encourages trying it eventually
        return stops / uses

    return max(DEFENSE_COUNTERS.keys(), key=stop_rate)


def _record_defense_outcome(defending_team, attack_strategy, counter, stopped: bool):
    stats = defending_team.defense_stats.setdefault(attack_strategy, {})
    uses, stops = stats.get(counter, [0, 0])
    stats[counter] = [uses + 1, stops + (1 if stopped else 0)]


def _resolve_exchange(half, index, attacking_team, defending_team, score, forced_strategy=None):
    attack_strategy = forced_strategy or random.choice(list(ATTACK_STRATEGIES.keys()))
    _, _, base_chance = ATTACK_STRATEGIES[attack_strategy]

    counter = _pick_defense_counter(defending_team, attack_strategy)

    a_stat = attacker_stat(attacking_team, attack_strategy)
    d_stat = max(defender_stat(defending_team, counter), 1.0)
    modifier = matchup_modifier(counter, attack_strategy)
    momentum_factor = 0.85 + (attacking_team.momentum / 100) * 0.3  # 0.85x - 1.15x

    goal_chance = base_chance * (a_stat / d_stat) * modifier * momentum_factor
    goal_chance = max(0.03, min(0.85, goal_chance))

    roll = random.random()
    scored = roll < goal_chance
    _record_defense_outcome(defending_team, attack_strategy, counter, stopped=not scored)

    counterattack = False
    if not scored and random.random() < COUNTERATTACK_CHANCE:
        counterattack = True

    if scored:
        if attacking_team is score["home_team"]:
            score["home"] += 1
        else:
            score["away"] += 1

    return {
        "half": half, "index": index,
        "attacking_team": attacking_team.name, "defending_team": defending_team.name,
        "attacker_strategy": attack_strategy, "attacker_stat": round(a_stat, 1),
        "defender_counter": counter, "defender_stat": round(d_stat, 1),
        "goal_chance": round(goal_chance, 3), "roll": round(roll, 3),
        "outcome": "goal" if scored else "no_goal",
        "counterattack": counterattack,
        "score_after": {"home": score["home"], "away": score["away"]},
    }


def play_match(home_team, away_team, verbose=False):
    with home_team.matchday(), away_team.matchday():
        return _play_match_inner(home_team, away_team, verbose)


def _play_match_inner(home_team, away_team, verbose=False):
    score = {"home": 0, "away": 0, "home_team": home_team}
    halves_log = []

    def run_round(half_label, n_exchanges, exchange_index_start=1):
        exchanges = []
        idx = exchange_index_start
        i = 0
        while i < n_exchanges:
            attacker, defender = (home_team, away_team) if i % 2 == 0 else (away_team, home_team)
            ex = _resolve_exchange(half_label, idx, attacker, defender, score)
            exchanges.append(ex)
            if verbose:
                _print_exchange(ex)
            if ex["counterattack"]:
                # immediate bonus exchange for the team that just turned it over
                counter_attacker, counter_defender = defender, attacker
                ex2 = _resolve_exchange(half_label, idx + 0.5, counter_attacker, counter_defender, score)
                ex2["is_counterattack_bonus"] = True
                exchanges.append(ex2)
                if verbose:
                    _print_exchange(ex2, counter=True)
            idx += 1
            i += 1
        return exchanges

    for half in (1, 2):
        exchanges = run_round(half, 4)
        halves_log.append(exchanges)

        # decaying extra-time chance after this half
        decay = 0.5
        extra_round_num = 1
        while random.random() < decay:
            resisting_team = home_team if score["home"] >= score["away"] else away_team
            resilience_bias = (resisting_team.resilience - 50) / 100 * 0.1
            if random.random() < resilience_bias:  # resilient leader shuts it down early
                break
            extra_exchanges = run_round(f"{half}-extra{extra_round_num}", 2)
            halves_log.append(extra_exchanges)
            decay *= 0.5
            extra_round_num += 1

    result = "home_win" if score["home"] > score["away"] else \
              "away_win" if score["away"] > score["home"] else "draw"

    home_team.record_result({"home_win": "W", "away_win": "L", "draw": "D"}[result])
    away_team.record_result({"home_win": "L", "away_win": "W", "draw": "D"}[result])

    return {
        "home": home_team.name, "away": away_team.name,
        "home_score": score["home"], "away_score": score["away"],
        "result": result, "halves": halves_log,
    }


def _print_exchange(ex, counter=False):
    tag = "  ↳ COUNTER" if counter else f"[H{ex['half']} #{ex['index']}]"
    mark = "⚽ GOAL" if ex["outcome"] == "goal" else "—"
    print(f"  {tag} {ex['attacking_team']:9s} plays {ex['attacker_strategy']:20s} "
          f"vs {ex['defending_team']:9s} {ex['defender_counter']:15s} "
          f"({ex['goal_chance']*100:4.1f}%) -> {mark}  "
          f"[{ex['score_after']['home']}-{ex['score_after']['away']}]")


def resolve_penalties(home_team, away_team, verbose=True):
    """
    Knockout matches can't end in a draw. If regulation + extra time are level,
    settle it with a penalty shootout: 5 rounds each, then sudden death.
    Success chance is driven by `consistency` (composure under pressure) with
    a small `attack` assist, not by pure randomness.
    """
    def kick_chance(team):
        return max(0.45, min(0.92, 0.55 + (team.consistency - 50) / 200 + (team.attack - 50) / 400))

    if verbose:
        print(f"  --- PENALTY SHOOTOUT: {home_team.name} vs {away_team.name} ---")

    home_score, away_score = 0, 0
    rnd = 1
    while True:
        home_hit = random.random() < kick_chance(home_team)
        away_hit = random.random() < kick_chance(away_team)
        home_score += home_hit
        away_score += away_hit
        if verbose:
            print(f"    Round {rnd}: {home_team.name} {'GOAL' if home_hit else 'MISS'}  |  "
                  f"{away_team.name} {'GOAL' if away_hit else 'MISS'}   "
                  f"({home_score}-{away_score})")
        if rnd >= 5 and home_score != away_score:
            break
        if rnd >= 20:  # absurd safety cap
            break
        rnd += 1

    winner = home_team.name if home_score > away_score else away_team.name
    if verbose:
        print(f"  Shootout result: {home_team.name} {home_score} - {away_score} {away_team.name} "
              f"-> {winner} advances on penalties")
    return winner, home_score, away_score
