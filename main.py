#!/usr/bin/env python3
"""
monthball — CLI entry point.

Commands (type at the prompt):
  n / next        advance one day (default if you just hit enter)
  n <k>           advance k days
  m               advance one month (ticks until the calendar month changes)
  run             auto-run every remaining day of the current season, no pauses
  standings       show current league table
  team <Month>    show a team's full roster + stats
  schedule        list this season's upcoming fixtures
  clubs           list every club with squad size, position breakdown, cash
  market          list free agents currently available to buy (nobody's roster)
  quiet / verbose toggle whether match tactics-exchanges are printed live
  season          start the next season once the current one finishes
  quit            exit
"""
import sys

from monthball.season import Season
from monthball.team import MONTHS


def print_team(season, name):
    name = name.strip().title()
    if name not in season.teams:
        print(f"Unknown team '{name}'. Valid: {', '.join(MONTHS)}")
        return
    t = season.teams[name]
    print(f"\n{t}")
    print(f"  legacyRating {t.legacy_rating}  attack {t.attack}  defense {t.defense}  "
          f"pace {t.pace}  consistency {t.consistency}  peakPower {t.peak_power}  "
          f"momentum {t.momentum}  resilience {t.resilience}  homeForm {t.home_form}  "
          f"stamina {t.stamina}")
    print(f"  cash: {t.cash:.1f}   squad size: {len(t.roster)}")
    for p in sorted(t.roster, key=lambda p: p.position):
        print(f"    {p}")


def print_market(season, show_list=True):
    from collections import Counter
    pool = season.free_agents
    if not pool:
        print("\nFree agent market: empty. Nobody unowned is available right now.")
        return
    counts = Counter(p.position for p in pool)
    print(f"\nFree agent market: {len(pool)} available "
          f"(Forward {counts.get('Forward',0)}, Defender {counts.get('Defender',0)}, "
          f"Midfielder {counts.get('Midfielder',0)})")
    if show_list:
        for p in sorted(pool, key=lambda p: (p.position, -p.base_value)):
            print(f"    {p}")


def print_clubs(season):
    print(f"\n{'Club':10s} {'Squad':>5s}  {'Fwd':>3s} {'Def':>3s} {'Mid':>3s}   {'Cash':>9s}   Lineup-5 ready?")
    print("-" * 68)
    for name in MONTHS:
        t = season.teams[name]
        fwd = sum(1 for p in t.roster if p.position == "Forward")
        de = sum(1 for p in t.roster if p.position == "Defender")
        mid = sum(1 for p in t.roster if p.position == "Midfielder")
        ready = "yes" if len(t.roster) >= 5 else "no"
        print(f"{name:10s} {len(t.roster):5d}  {fwd:3d} {de:3d} {mid:3d}   {t.cash:9.1f}   {ready}")


def print_upcoming(season, n=10):
    print(f"\nUpcoming (from {season.current_date}):")
    shown = 0
    d = season.current_date
    while shown < n and d <= season.end_date:
        for ev in season.events_by_date.get(d, []):
            if ev["type"] == "match":
                print(f"  {d}  {ev['home']} vs {ev['away']}  ({ev['block']})")
                shown += 1
            elif ev["type"] in ("transfer_window", "standings", "playoffs", "league_bonus"):
                print(f"  {d}  [{ev['type'].upper()}]")
        d += __import__("datetime").timedelta(days=1)


def main():
    print("=" * 60)
    print(" MONTHBALL — months are teams, weeks are players")
    print("=" * 60)
    season = Season(season_number=1)
    verbose = True

    while True:
        try:
            raw = input("\n> ").strip()
        except EOFError:
            break
        if not raw:
            raw = "n"
        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            break

        elif cmd in ("n", "next"):
            k = int(parts[1]) if len(parts) > 1 else 1
            for _ in range(k):
                if season.finished:
                    print("Season finished. Type 'season' to start the next one.")
                    break
                s = season.tick(verbose_matches=verbose)
                if not any(e["type"] == "match" for e in s["events"]) and not s["events"]:
                    print(f"{s['date']} — nothing scheduled.")

        elif cmd == "m":
            if season.finished:
                print("Season finished. Type 'season' to start the next one.")
            else:
                start_month = season.current_date.month
                while not season.finished and season.current_date.month == start_month:
                    season.tick(verbose_matches=verbose)
                print(f"-- now {season.current_date.strftime('%B %Y')} --")

        elif cmd == "run":
            while not season.finished:
                season.tick(verbose_matches=verbose)
            print("\nSeason complete. Type 'season' to start the next one.")

        elif cmd == "standings":
            if season.final_standings:
                print(f"\n=== SEASON {season.season_number} FINAL STANDINGS (post-playoffs) ===")
                for i, name in enumerate(season.final_standings, start=1):
                    print(f" {i:2d}. {name}")
            else:
                live = season.compute_standings()
                label = f"SEASON {season.season_number} STANDINGS (as of {season.current_date})"
                season._print_standings(table=live, label=label)

        elif cmd == "team":
            if len(parts) < 2:
                print("Usage: team <MonthName>")
            else:
                print_team(season, " ".join(parts[1:]))

        elif cmd == "schedule":
            print_upcoming(season)

        elif cmd == "clubs":
            print_clubs(season)

        elif cmd == "market":
            print_market(season)

        elif cmd == "verbose":
            verbose = True
            print("Match tactics exchanges: ON")

        elif cmd == "quiet":
            verbose = False
            print("Match tactics exchanges: OFF (only final scores shown)")

        elif cmd == "season":
            if season.finished:
                season = season.next_season()
                print(f"\nSeason {season.season_number} begins {season.start_date}.")
            else:
                print("Current season isn't finished yet.")

        else:
            print("Unknown command. Try: n, m, run, standings, team <Month>, schedule, clubs, market, verbose, quiet, season, quit")

    print("Goodbye.")


if __name__ == "__main__":
    sys.exit(main())
