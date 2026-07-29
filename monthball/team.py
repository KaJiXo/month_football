"""
Team = a month. Its 10 stats mostly EMERGE from whichever week-players
(the roster) it currently owns, rather than being calendar-fixed.

Exceptions:
  homeForm - fixture/calendar-intrinsic (weekend day count of that month
             in a fixed reference year), not player-derived.
  momentum - derived from recent match results, not astronomy.

Squad size itself is NOT capped — a team can keep or sell as many players
as it can afford; that's a financial decision, not a rules cap. What IS
capped is how many of those players actually shape a given match: see
MATCHDAY_LINEUP_SIZE and select_lineup()/matchday() below. Stamina, cash,
and wages still reflect the FULL roster (bench depth costs money and
gives rotation capacity, whether or not those players start).
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

REFERENCE_YEAR = 2026  # used only to compute homeForm (weekend-day count) deterministically

MATCHDAY_LINEUP_SIZE = 5  # how many players actually shape a given match's stats


def _weekend_days_in_month(month_index: int, year: int = REFERENCE_YEAR) -> int:
    d = date(year, month_index + 1, 1)
    count = 0
    while d.month == month_index + 1:
        if d.weekday() >= 5:
            count += 1
        d += timedelta(days=1)
    return count


@dataclass
class Team:
    name: str
    roster: list = field(default_factory=list)

    cash: float = 0.0
    match_history: list = field(default_factory=list)   # 'W' / 'D' / 'L', most recent last
    listed_for_sale: list = field(default_factory=list)  # players this team wants to sell

    # bandit AI memory: defense_stats[attacker_strategy][counter] = [uses, stops]
    defense_stats: dict = field(default_factory=dict)

    # transient, not persisted: set by `matchday()` around a single match so
    # attack/defense/pace/consistency/peak_power reflect only the fielded
    # lineup rather than the whole squad. None = use the full roster.
    _matchday_pool: list = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    def add_player(self, p):
        p.owner = self.name
        self.roster.append(p)

    def remove_player(self, p):
        if p in self.roster:
            self.roster.remove(p)
        p.owner = None

    def select_lineup(self, size=MATCHDAY_LINEUP_SIZE):
        """Pick the matchday squad: the best player at each required position
        first (guaranteeing the lineup is legal), then fill remaining slots
        with the best remaining players by value regardless of position."""
        if len(self.roster) <= size:
            return list(self.roster)

        chosen, chosen_ids = [], set()
        for pos in ("Forward", "Defender", "Midfielder"):
            candidates = [p for p in self.roster if p.position == pos]
            if candidates:
                best = max(candidates, key=lambda p: p.base_value)
                chosen.append(best)
                chosen_ids.add(id(best))

        remaining = [p for p in self.roster if id(p) not in chosen_ids]
        remaining.sort(key=lambda p: p.base_value, reverse=True)
        chosen.extend(remaining[: max(0, size - len(chosen))])
        return chosen

    @contextmanager
    def matchday(self, size=MATCHDAY_LINEUP_SIZE):
        """Context manager: use this team's best `size` players for the
        duration of a single match (and any shootout), then restore."""
        previous = self._matchday_pool
        self._matchday_pool = self.select_lineup(size)
        try:
            yield self._matchday_pool
        finally:
            self._matchday_pool = previous

    # ------------------------------------------------------------------
    def _avg(self, stat, positions=None):
        pool = self._matchday_pool if self._matchday_pool is not None else self.roster
        pool = [p for p in pool if positions is None or p.position in positions]
        if not pool:
            pool = self._matchday_pool if self._matchday_pool is not None else self.roster
        if not pool:
            return 50.0  # empty squad fallback
        return mean(getattr(p, stat) for p in pool)

    # ---- 10 team stats, blended 70% specialist / 30% whole-squad ------
    @property
    def attack(self):
        return round(0.7 * self._avg("attack", ["Forward"]) + 0.3 * self._avg("attack"), 1)

    @property
    def defense(self):
        return round(0.7 * self._avg("defense", ["Defender"]) + 0.3 * self._avg("defense"), 1)

    @property
    def stamina(self):
        return round(min(100.0, len(self.roster) * 4.0), 1)  # grows with FULL squad size (bench depth)

    @property
    def pace(self):
        return round(self._avg("pace"), 1)

    @property
    def consistency(self):
        return round(self._avg("consistency"), 1)

    @property
    def home_form(self):
        month_index = MONTHS.index(self.name)
        weekend_days = _weekend_days_in_month(month_index)
        return round((weekend_days / 10.0) * 100, 1)  # ~8-10 weekend days/month max

    @property
    def peak_power(self):
        pool = self._matchday_pool if self._matchday_pool is not None else self.roster
        if not pool:
            return 50.0
        return round(max(p.potential for p in pool), 1)

    @property
    def momentum(self):
        recent = self.match_history[-5:]
        if not recent:
            return 50.0
        score = sum({"W": 1.0, "D": 0.5, "L": 0.0}[r] for r in recent) / len(recent)
        return round(score * 100, 1)

    @property
    def resilience(self):
        # squad-wide depth stat, deliberately NOT restricted to the matchday
        # lineup — it represents structural depth through the middle, not
        # who happened to start.
        mids = [p for p in self.roster if p.position == "Midfielder"]
        pool = mids or self.roster
        if not pool:
            return 50.0
        return round(mean((p.consistency + p.potential) / 2 for p in pool), 1)

    @property
    def legacy_rating(self):
        return round(
            0.25 * self.attack + 0.20 * self.defense + 0.15 * self.consistency +
            0.15 * self.peak_power + 0.10 * self.pace + 0.10 * self.momentum +
            0.05 * self.resilience, 1)

    # ---- economy --------------------------------------------------
    def club_worth(self, scarcity_factors: dict) -> float:
        return round(sum(p.base_value * scarcity_factors.get(p.id, 1.0) for p in self.roster), 1)

    def record_result(self, outcome: str):
        self.match_history.append(outcome)

    def __repr__(self):
        return (f"<Team {self.name:9s} LR{self.legacy_rating:5.1f} "
                f"ATK{self.attack:5.1f} DEF{self.defense:5.1f} squad={len(self.roster)} "
                f"cash={self.cash:.0f}>")


def create_teams():
    return {m: Team(name=m) for m in MONTHS}
