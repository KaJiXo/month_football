"""
Player = one ISO-ish week of a given year.

5 base stats, all pure functions of the week's dates:
  attack       - avg solar elevation that week
  defense      - avg daylight hours that week
  pace         - daylight rate-of-change across the week
  consistency  - inverse of day-to-day elevation variance
  potential    - closeness to a solstice/equinox
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, pstdev

from . import astronomy


@dataclass
class Player:
    year: int
    week_number: int
    start_date: date
    end_date: date

    attack: float = 0.0
    defense: float = 0.0
    pace: float = 0.0
    consistency: float = 0.0
    potential: float = 0.0

    owner: str = None          # team name, or None if free agent
    id: str = field(default="")

    def __post_init__(self):
        self.id = f"{self.year}-W{self.week_number:02d}"
        self._compute_stats()

    # ------------------------------------------------------------------
    def _compute_stats(self):
        n_days = (self.end_date - self.start_date).days + 1
        days = [self.start_date + timedelta(days=i) for i in range(n_days)]

        elevations, daylights = [], []
        for d in days:
            doy = astronomy.day_of_year(d)
            dec = astronomy.solar_declination(doy)
            elevations.append(astronomy.solar_elevation_noon(astronomy.LATITUDE, dec))
            daylights.append(astronomy.daylight_hours(astronomy.LATITUDE, dec))

        avg_elev = mean(elevations)
        avg_daylight = mean(daylights)

        self.attack = _clamp(100 * (avg_elev - astronomy.ELEVATION_MIN) /
                              (astronomy.ELEVATION_MAX - astronomy.ELEVATION_MIN))
        self.defense = _clamp(100 * (avg_daylight - astronomy.DAYLIGHT_MIN) /
                               (astronomy.DAYLIGHT_MAX - astronomy.DAYLIGHT_MIN))

        pace_delta = abs(daylights[-1] - daylights[0])
        self.pace = _clamp((pace_delta / 0.33) * 100)  # ~0.33h/week is the real max swing (near equinox)

        stdev_elev = pstdev(elevations) if len(elevations) > 1 else 0.0
        self.consistency = _clamp(100 - (stdev_elev / 4.0) * 100)

        mid_date = days[len(days) // 2]
        dist = astronomy.days_to_nearest_key_date(mid_date)
        self.potential = _clamp(100 * (1 - dist / 45.5))

        # round everything for display sanity
        for attr in ("attack", "defense", "pace", "consistency", "potential"):
            setattr(self, attr, round(getattr(self, attr), 1))

    # ------------------------------------------------------------------
    @property
    def position(self) -> str:
        """
        NOTE: attack (solar elevation) and defense (daylight length) are both
        monotonic functions of the same declination at a fixed latitude, so
        they're almost perfectly rank-correlated — comparing them head-to-head
        can never produce a real 3-way split. Position is instead based on
        seasonal phase: peak-sun weeks are Forwards, trough weeks are
        Defenders, and the fast-transitioning weeks around the equinoxes
        (high pace, mid-range attack) are Midfielders.
        """
        if self.attack >= 66.0:
            return "Forward"
        if self.attack <= 34.0:
            return "Defender"
        return "Midfielder"

    @property
    def base_value(self) -> float:
        """Unscaled sum of stats — scarcity factor is applied externally (market.py)."""
        return self.attack + self.defense + self.pace + self.consistency + self.potential

    def __repr__(self):
        return (f"<{self.id} {self.position:9s} "
                f"ATK{self.attack:5.1f} DEF{self.defense:5.1f} "
                f"PACE{self.pace:5.1f} CON{self.consistency:5.1f} POT{self.potential:5.1f}>")


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def generate_weeks(year: int):
    """All week-players for a given year, in order."""
    players = []
    d = date(year, 1, 1)
    week_num = 1
    while d.year == year:
        start = d
        end = min(d + timedelta(days=6), date(year, 12, 31))
        players.append(Player(year=year, week_number=week_num, start_date=start, end_date=end))
        d = end + timedelta(days=1)
        week_num += 1
    return players
