"""
Transfer market: player valuation, club worth, wages, and the rule-based
(no ML needed) transfer-window AI each team runs on itself.
"""
from statistics import mean, pstdev
import random

WAGE_RATE_ANNUAL = 1.8  # ~180% of market value paid in wages per YEAR, spread over 12 months

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
            candidates.extend(other.listed_for_sale)  # currently always empty, kept for compatibility
            candidates.extend(_general_surplus(other))
    seen, unique = set(), []
    for c in candidates:
        if c.id not in seen:
            unique.append(c)
            seen.add(c.id)
    return unique


def _general_surplus(team, min_keep=2):
    """A team's genuinely spare depth, offered onto the open market for any
    other team to buy — not just during financial distress. Without this,
    discretionary buying could ONLY ever pull from the free-agent pool
    (which is often thin or empty), so a cash-rich team could have nothing
    to spend on even while other teams sat on lopsided extra depth in one
    position. Keeps each team's own best `min_keep` per position for itself
    and offers the rest."""
    surplus = []
    by_position = {}
    for p in team.roster:
        by_position.setdefault(p.position, []).append(p)
    for players in by_position.values():
        players.sort(key=lambda p: p.base_value, reverse=True)
        surplus.extend(players[min_keep:])
    return surplus


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
      3. RAISE FUNDS: whenever the team's projected monthly wage bill would
         eat too much of its cash reserve, shed surplus players (more than
         the required minimum of 1 per position) — trying to SELL them to
         another team for real cash first, and only releasing to free
         agency with no fee if genuinely nobody else can/would buy.
    Team turn order is SHUFFLED each call — always going in a fixed
    January-to-December order would let January get first pick of the
    cheapest/best-value candidates in every single window forever, and
    later months would permanently overpay for whatever's left. No
    simultaneous-bid wars are modelled beyond "turn order decides who
    gets a contested candidate."
    """
    log = log if log is not None else []
    all_teams = list(teams.values())

    turn_order = list(teams.values())
    random.shuffle(turn_order)

    for team in turn_order:
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
                min_reserve = 0.0  # required fills happen regardless of reserve — legality first
            else:
                weakest_attr = _relative_weakest_stat(team, all_teams)
                pool = candidates
                reason = f"fixing {weakest_attr}"
                # Discretionary buys must leave enough cash that the team
                # doesn't immediately qualify for its own distress-sell
                # trigger (2x wages) right after — otherwise it buys
                # something and gets forced to sell it straight back out.
                # The reserve here must be >= the sell trigger, with a
                # little margin, or buy/sell oscillate on the same player.
                min_reserve = sum(wage(p, scarcity_factors) for p in team.roster) * 2.5

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
                if cost <= team.cash and (team.cash - cost) >= min_reserve:
                    _execute_signing(team, cand, cost, teams, free_agents, log, reason)
                    signings += 1
                    bought_this_round = True
                    break

            if not bought_this_round:
                break  # can't afford anything useful right now (or it'd wreck reserves)

        _sell_if_overextended(team, teams, scarcity_factors, free_agents, log)

    return log


def run_initial_draft(teams, free_agents, scarcity_factors, log=None, max_rounds=8):
    """
    Season-1 kickoff: every team starts with an EMPTY roster and base cash.
    The previous year's weeks (the "pre-game" season) sit in the free-agent
    pool, and every team runs the normal transfer-window AI against that
    shared pool to assemble its opening-day squad — buying what it needs,
    same as any other window. Repeats several rounds so teams that need all
    3 required positions actually get there.

    A team can still get starved out of a scarce position by round order
    (everyone ahead of it in the fixed team order buys up the affordable
    ones first) even after many rounds, since normal rounds only ever use
    each team's ordinary value-scoring logic. So after the normal rounds,
    every team still missing a required position is force-completed with
    the cheapest available candidate in that position, regardless of value
    score — a legal squad for every team is a harder requirement than
    getting the "best" deal on the last piece.
    """
    log = log if log is not None else []
    for _ in range(max_rounds):
        if all(not _missing_positions(t) for t in teams.values()):
            break
        run_transfer_window(teams, free_agents, scarcity_factors, log)

    for team in teams.values():
        for pos in _missing_positions(team):
            pool = [c for c in free_agents if c.position == pos]
            for other in teams.values():
                if other is not team:
                    pool.extend(c for c in other.listed_for_sale if c.position == pos)
            if not pool:
                continue  # nobody of this position exists anywhere in the pool at all

            pool.sort(key=lambda p: market_value(p, scarcity_factors))
            cand = pool[0]
            cost = market_value(cand, scarcity_factors)
            affordable = cost <= team.cash
            _execute_signing(team, cand, cost, teams, free_agents, log,
                              f"emergency fill {pos}" + ("" if affordable else " (over budget)"))

    # Every team is now legal (>=1 per required position), but the rounds
    # above stop the instant that's true — even if a team still has cash to
    # spare. Without this, teams end the draft stuck at the bare minimum of
    # 3 players regardless of budget. Keep buying (affordable only, no
    # overspending — this part is about growth, not legality) until every
    # team reaches a full matchday-lineup-sized squad or genuinely can't
    # afford to grow further.
    _grow_squads_to_target(teams, free_agents, scarcity_factors, log)

    return log


def _grow_squads_to_target(teams, free_agents, scarcity_factors, log, target_size=5, max_passes=10):
    for _ in range(max_passes):
        progressed = False
        order = list(teams.values())
        random.shuffle(order)

        for team in order:
            if len(team.roster) >= target_size:
                continue
            candidates = _gather_candidates(team, teams, free_agents)
            if not candidates:
                continue

            weakest_attr = _relative_weakest_stat(team, list(teams.values()))
            candidates.sort(
                key=lambda p: _proxy_stat(p, weakest_attr) / (market_value(p, scarcity_factors) or 1.0),
                reverse=True,
            )
            for cand in candidates:
                cost = market_value(cand, scarcity_factors)
                if cost <= team.cash:
                    _execute_signing(team, cand, cost, teams, free_agents, log, "growing initial squad")
                    progressed = True
                    break

        if not progressed:
            break  # nobody could afford to grow further this pass


def _sell_if_overextended(team, teams, scarcity_factors, free_agents, log):
    """When the projected wage bill looks unaffordable relative to current
    cash, shed surplus players — but ALWAYS try to sell them to another
    team for real cash first. Only if no other team can afford (or wants)
    the player does it become a free release with no fee. Skipping straight
    to a free release every time is irrational: it throws away money the
    club could otherwise have raised."""
    if not team.roster:
        return

    projected_monthly_wages = sum(wage(p, scarcity_factors) for p in team.roster)
    safety_buffer = projected_monthly_wages * 2  # keep ~2 months of wages in reserve

    released = 0
    while team.cash < safety_buffer and released < 3:
        have_counts = {}
        for p in team.roster:
            have_counts[p.position] = have_counts.get(p.position, 0) + 1

        releasable = [p for p in team.roster if have_counts[p.position] > 1]
        if not releasable:
            break

        weakest_player = min(releasable, key=lambda p: p.base_value)
        cost = market_value(weakest_player, scarcity_factors)
        buyer = _find_buyer(weakest_player, teams, team, cost, scarcity_factors)

        team.remove_player(weakest_player)
        if weakest_player in team.listed_for_sale:
            team.listed_for_sale.remove(weakest_player)

        if buyer is not None:
            buyer.add_player(weakest_player)
            buyer.cash = round(buyer.cash - cost, 1)
            team.cash = round(team.cash + cost, 1)
            log.append(f"  {team.name} sells {weakest_player.id} to {buyer.name} for {cost:.0f} "
                        f"(raising funds)")
        else:
            free_agents.append(weakest_player)
            # NOTE: no cash added — nobody could/would buy this one, so it's a
            # genuine release, not a sale.
            log.append(f"  {team.name} releases {weakest_player.id} to free agency, no fee "
                        f"(no buyer found; cash {team.cash:.0f} vs {safety_buffer:.0f} needed)")
        released += 1


def _find_buyer(player, teams, seller, cost, scarcity_factors):
    """Find another team to buy a player a seller needs to shed. A buyer
    must actually be able to AFFORD it without immediately triggering its
    own distress-sale trigger — otherwise it just buys the player and gets
    forced to resell it (to anyone, including back to the original seller)
    on the very next check, causing an endless resale loop between two or
    three cash-tight teams. Prefers a team genuinely missing this position;
    otherwise any other team with room to spare. Returns None if nobody can
    safely absorb it."""
    candidates = []
    for t in teams.values():
        if t is seller or t.cash < cost:
            continue
        wage_bill_after = sum(wage(p, scarcity_factors) for p in t.roster) + wage(player, scarcity_factors)
        # Must clear the seller's OWN future sell-trigger (2x wages) with
        # margin, not just some smaller number — otherwise a team that buys
        # down to just above a lower bar immediately re-qualifies to sell
        # again, causing the exact same player to bounce back and forth
        # between two teams forever.
        reserve = wage_bill_after * 2.5
        if (t.cash - cost) >= reserve:
            candidates.append(t)

    if not candidates:
        return None
    in_need = [t for t in candidates if player.position in _missing_positions(t)]
    pool = in_need or candidates
    return max(pool, key=lambda t: t.cash)
