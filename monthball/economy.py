"""
Economic settlement, run at month-end (not daily) and at season-end.
"""
from . import market

MATCHDAY_REVENUE_RATE = 5.0     # cash per home_form point per home match played that month
SPONSORSHIP_RATE = 2.5          # cash per legacy_rating point, per month
BASE_STARTING_CASH = 1000.0
SPREAD = 0.12
DRAFT_BUDGET_MULTIPLIER = 2.0  # season-1 kickoff needs enough to actually build a 5-player squad


def starting_cash(team, days_in_month: int) -> float:
    length_bonus = (days_in_month - 30) / 30 * SPREAD
    prestige_bonus = ((team.peak_power - 50) / 50) * SPREAD
    return round(BASE_STARTING_CASH * (1 + length_bonus) * (1 + prestige_bonus), 1)


def settle_month(team, home_matches_played: int, scarcity_factors: dict, log=None):
    income = home_matches_played * team.home_form * MATCHDAY_REVENUE_RATE / 10.0 \
        + team.legacy_rating * SPONSORSHIP_RATE
    expenditure = sum(market.wage(p, scarcity_factors) for p in team.roster)

    team.cash = round(team.cash + income - expenditure, 1)
    distressed = team.cash < 0

    msg = (f"  {team.name:9s} income {income:7.1f}  wages {expenditure:7.1f}  "
           f"-> cash {team.cash:8.1f}" + ("  [DISTRESS]" if distressed else ""))
    if log is not None:
        log.append(msg)
    return distressed


# Tiered payout for final league position (1st..12th)
LEAGUE_BONUS_TABLE = {
    1: 3.0, 2: 2.4, 3: 2.0, 4: 1.7, 5: 1.4, 6: 1.2,
    7: 1.0, 8: 0.85, 9: 0.7, 10: 0.55, 11: 0.4, 12: 0.25,
}
BASE_PRIZE_POOL = 500.0


def pay_league_bonus(team, rank: int, log=None):
    multiplier = LEAGUE_BONUS_TABLE.get(rank, 0.25)
    bonus = round(BASE_PRIZE_POOL * multiplier, 1)
    team.cash = round(team.cash + bonus, 1)
    if log is not None:
        log.append(f"  {team.name:9s} finishes #{rank:2d} -> league bonus {bonus:.1f}")
    return bonus
