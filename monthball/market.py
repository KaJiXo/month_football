"""
Transfer market: player valuation, club worth, wages, and the rule-based
(no ML needed) transfer-window AI each team runs on itself.
"""
from statistics import mean, pstdev

WAGE_RATE_ANNUAL = 1.5  # ~150% of market value paid in wages per YEAR, spread over 12 months

WEAKEST_STAT_ATTRS = ["attack", "defense", "pace", "consistency", "peak_power", "resilience"]
MAX_SIGNINGS_PER_TEAM_PER_WINDOW = 2
REQUIRED_POSITIONS = ["Forward", "Defender", "Midfielder"]


def compute_scarcity_factors(players) -> dict:
    """Z-score each player's base stat total against the whole pool -> 0.7x-1.6x multiplier."""
    if not players:
        return {}
    values = [p.base_value for p in players]
    mu = mean(values)
    sigma = pstdev(values) or 1.0
    factors = {}
    for p, v in zip(players, values):
        z = (v - mu) / sigma
        factors[p.id] = max(0.7, min(1.6, 1 + z * 0.2))
    return factors


def market_value(player, scarcity_factors: dict) -> float:
    return round(player.base_value * scarcity_factors.get(player.id, 1.0), 1)


def wage(player, scarcity_factors: dict) -> float:
    """Monthly wage — the annual rate spread across the 12 monthly settlements."""
    return round(market_value(player, scarcity_factors) * WAGE_RATE_ANNUAL / 12, 1)


def _missing_positions(team):
    have = {p.position for p in team.roster}
    return [pos for pos in REQUIRED_POSITIONS if pos not in have]


def _relative_weakest_stat(team, all_teams):
    """
    Pick the stat where this team lags the LEAGUE AVERAGE the most (z-score),
    not just whichever stat happens to have the lowest raw number — different
    stats naturally live on different scales, so raw-magnitude comparison
    always picks the same stat for every team.
    """
    best_attr, best_z = None, None
    for attr in WEAKEST_STAT_ATTRS:
        league_vals = [getattr(t, attr) for t in all_teams]
        mu = mean(league_vals)
        sigma = pstdev(league_vals) or 1.0
        z = (getattr(team, attr) - mu) / sigma
        if best_z is None or z < best_z:
            best_z, best_attr = z, attr
    return best_attr


def _proxy_stat(player, weakest_attr):
    return {
        "attack": player.attack, "defense": player.defense, "pace": player.pace,
        "consistency": player.consistency, "peak_power": player.potential,
        "resilience": (player.consistency + player.potential) / 2,
    }[weakest_attr]


def _gather_candidates(team, teams, free_agents):
    candidates = list(free_agents)
    for other in teams.values():
        if other is not team:
            candidates.extend(other.listed_for_sale)
    return candidates


def _surplus_at_position(teams, exclude_team, position):
    """Players other teams could spare in a given position — anyone beyond
    their own required minimum of 1 in that position. This is what lets a
    team that structurally lacks (e.g.) any Defenders actually acquire one,
    rather than only ever seeing formally-listed players."""
    surplus = []
    for other in teams.values():
        if other is exclude_team:
            continue
        same_pos = sorted((p for p in other.roster if p.position == position),
                           key=lambda p: p.base_value)
        surplus.extend(same_pos[1:])  # keep their own best one, offer the rest
    return surplus


def _execute_signing(team, cand, cost, teams, free_agents, log, reason):
    seller_name = cand.owner
    if seller_name and seller_name in teams:
        seller = teams[seller_name]
        seller.remove_player(cand)
        if cand in seller.listed_for_sale:
            seller.listed_for_sale.remove(cand)
        seller.cash = round(seller.cash + cost, 1)
    elif cand in free_agents:
        free_agents.remove(cand)

    team.add_player(cand)
    team.cash = round(team.cash - cost, 1)
    log.append(f"  {team.name} signs {cand.id} ({cand.position}) for {cost:.0f} [{reason}]")


def run_transfer_window(teams: dict, free_agents: list, scarcity_factors: dict, log=None):
    """
    Deterministic, explainable per-team AI, run once per team per window:
      0. fill any missing required position (Forward/Defender/Midfielder) first —
         a squad isn't legal without at least one of each.
      1. otherwise, find the stat where the team lags the league average most
         (relative, not raw-magnitude, so it isn't always the same stat), and
         buy the best (improvement / cost) affordable fit. Squad size itself
         is uncapped — how big a squad to carry is a financial decision for
         the team (bigger squad = more wages, more stamina, more matchday
         options via the lineup selection in team.py), not a rules limit.
      2. repeat (capped per window) until budget runs dry or nothing useful
         remains.
      3. RELEASE: whenever the team's projected monthly wage bill would eat
         too much of its cash reserve, release surplus players (more than
         the required minimum of 1 per position) to free agency — this cuts
         the wage cost immediately but generates NO cash, since nobody
         bought them; the club simply couldn't afford to keep them. If
         another team later signs that released player, that fee still goes
         nowhere (same as any free-agent signing) — it does not retroactively
         reward the club that let them go.
    Teams act in a fixed order each window (no simultaneous-bid wars modelled).
    """
    log = log if log is not None else []
    all_teams = list(teams.values())

    for team in teams.values():
        signings = 0

        while signings < MAX_SIGNINGS_PER_TEAM_PER_WINDOW:
            candidates = _gather_candidates(team, teams, free_agents)
            if not candidates:
                break

            missing = _missing_positions(team)

            if missing:
                need = missing[0]
                pool_ids_seen = set()
                pool = []
                for c in candidates + _surplus_at_position(teams, team, need):
                    if c.position == need and c.id not in pool_ids_seen:
                        pool.append(c)
                        pool_ids_seen.add(c.id)
                reason = f"filling required {need}"
            else:
                weakest_attr = _relative_weakest_stat(team, all_teams)
                pool = candidates
                reason = f"fixing {weakest_attr}"

            if not pool:
                break

            def value_score(p, attr=(missing[0] if missing else None)):
                cost = market_value(p, scarcity_factors) or 1.0
                if attr:
                    return 1.0 / cost  # any body in the right position beats none
                return _proxy_stat(p, weakest_attr) / cost

            pool.sort(key=value_score, reverse=True)

            bought_this_round = False
            for cand in pool:
                cost = market_value(cand, scarcity_factors)
                if cost <= team.cash:
                    _execute_signing(team, cand, cost, teams, free_agents, log, reason)
                    signings += 1
                    bought_this_round = True
                    break

            if not bought_this_round:
                break  # can't afford anything useful right now

        _sell_if_overextended(team, scarcity_factors, free_agents, log)

    return log


def _sell_if_overextended(team, scarcity_factors, free_agents, log):
    """When the projected wage bill looks unaffordable relative to current
    cash, RELEASE surplus players to free agency. This is a release, not a
    sale: the club gets no cash for it (nobody bought them — the club just
    couldn't afford to keep paying them). It only removes their future wage
    cost. If some other team later signs them as a free agent, that fee
    still goes nowhere, exactly like any other free-agent signing — it is
    never paid retroactively to the club that released them."""
    if not team.roster:
        return

    projected_monthly_wages = sum(wage(p, scarcity_factors) for p in team.roster)
    safety_buffer = projected_monthly_wages * 4  # keep ~4 months of wages in reserve

    released = 0
    while team.cash < safety_buffer and released < 3:
        have_counts = {}
        for p in team.roster:
            have_counts[p.position] = have_counts.get(p.position, 0) + 1

        releasable = [p for p in team.roster if have_counts[p.position] > 1]
        if not releasable:
            break

        weakest_player = min(releasable, key=lambda p: p.base_value)
        team.remove_player(weakest_player)
        if weakest_player in team.listed_for_sale:
            team.listed_for_sale.remove(weakest_player)
        free_agents.append(weakest_player)
        # NOTE: no cash added to team.cash here — this is a release, not a sale.
        log.append(f"  {team.name} releases {weakest_player.id} to free agency, no fee "
                    f"(cash {team.cash:.0f} vs {safety_buffer:.0f} needed)")
        released += 1
