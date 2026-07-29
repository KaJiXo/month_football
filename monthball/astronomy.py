"""
Pure-astronomy helper functions.

Everything downstream (player stats) is derived from solar elevation and
daylight length, which are pure functions of (date, latitude). This makes
every player deterministic and computable for any year, past or future.
"""
import math
from datetime import date

LATITUDE = 45.0  # reference latitude used for the whole simulation


def day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def solar_declination(doy: int) -> float:
    """Approximate solar declination angle (degrees) for a given day of year."""
    return 23.44 * math.sin(math.radians(360 / 365 * (doy - 81)))


def solar_elevation_noon(latitude: float, declination: float) -> float:
    """Solar elevation angle (degrees) at solar noon."""
    return 90 - abs(latitude - declination)


def daylight_hours(latitude: float, declination: float) -> float:
    """Length of the day (hours) at the given latitude/declination."""
    lat_r = math.radians(latitude)
    dec_r = math.radians(declination)
    cos_h = -math.tan(lat_r) * math.tan(dec_r)
    cos_h = max(-1.0, min(1.0, cos_h))
    hour_angle = math.degrees(math.acos(cos_h))
    return (2 * hour_angle) / 15.0


def days_to_nearest_key_date(d: date) -> int:
    """Distance in days to the nearest solstice/equinox (any year)."""
    y = d.year
    key_dates = [
        date(y, 3, 20), date(y, 6, 21), date(y, 9, 22), date(y, 12, 21),
        date(y - 1, 12, 21), date(y + 1, 3, 20),
    ]
    return min(abs((d - k).days) for k in key_dates)


# True achievable range at this latitude (winter solstice <-> summer solstice),
# used to min-max normalize attack/defense to their OWN real range instead of
# an arbitrary fixed scale. Without this, defense (daylight hours, a narrow
# ~9-15h range) and attack (solar elevation, a much wider angular range) end
# up on incomparable scales and one can never statistically outrank the other.
_WINTER_DEC = solar_declination(355)   # ~Dec 21
_SUMMER_DEC = solar_declination(172)   # ~Jun 21
ELEVATION_MIN = solar_elevation_noon(LATITUDE, _WINTER_DEC)
ELEVATION_MAX = solar_elevation_noon(LATITUDE, _SUMMER_DEC)
DAYLIGHT_MIN = daylight_hours(LATITUDE, _WINTER_DEC)
DAYLIGHT_MAX = daylight_hours(LATITUDE, _SUMMER_DEC)
