"""
Season orchestrator — the daily tick loop.

Each call to Season.tick() advances the calendar by exactly one day and:
  - plays any match(es) scheduled for that day (tactics exchanges printed live)
  - fires the mid-season or post-season transfer window if scheduled
  - runs month-end financial settlement whenever the date rolls into a new month
  - runs the playoff bracket + league bonus payout at season's end

This is the single source of truth for "what day is it / what just happened".
"""
from collections import defaultdict
from datetime import date, timedelta

from .team import create_teams, MONTHS
from .player import generate_weeks
from . import market, economy, schedule, match_engine

MATCHDAY_INTERVAL_DAYS = 12
MID_WINDOW_BREAK_DAYS = 25
POST_WINDOW_BREAK_DAYS = 15


def _days_in_month(month: int, year: int) -> int:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


class Season:
    def __init__(self, season_number=1, start_date=None, teams=None, free_agents=None):
        self.season_number = season_number
        self.start_date = start_date or date(2026, 1, 1)
        self.current_date = self.start_date
        self.teams = teams or create_teams()
        self.free_agents = free_agents if free_agents is not None else []

        self.events_by_date = defaultdict(list)
        self._home_matches_since_settlement = defaultdict(int)
        self.finished = False
        self.champion = None
        self.standings = []
        self.final_standings = []
        self.end_date = None

        self._build_calendar()

    # ------------------------------------------------------------------
    def _build_calendar(self):
        brand_new = all(len(t.roster) == 0 for t in self.teams.values())
        if brand_new:
            self._assign_initial_squads(self.start_date.year)
        else:
            new_weeks = generate_weeks(self.start_date.year)
            self.free_agents.extend(new_weeks)
            for t in self.teams.values():
                t.listed_for_sale.clear()

        round1, round2 = schedule.build_double_round_robin(list(MONTHS))

        d = self.start_date + timedelta(days=MATCHDAY_INTERVAL_DAYS)
        for matchday in round1:
            for (h, a) in matchday:
                self.events_by_date[d].append({"type": "match", "home": h, "away": a, "block": "Round 1"})
            d += timedelta(days=MATCHDAY_INTERVAL_DAYS)

        self.events_by_date[d].append({"type": "transfer_window", "label": "MID-SEASON"})
        d += timedelta(days=MID_WINDOW_BREAK_DAYS)

        for matchday in round2:
            for (h, a) in matchday:
                self.events_by_date[d].append({"type": "match", "home": h, "away": a, "block": "Round 2"})
            d += timedelta(days=MATCHDAY_INTERVAL_DAYS)

        self.events_by_date[d].append({"type": "standings"})
        d += timedelta(days=2)
        self.events_by_date[d].append({"type": "playoffs"})
        d += timedelta(days=POST_WINDOW_BREAK_DAYS)
        self.events_by_date[d].append({"type": "transfer_window", "label": "POST-SEASON"})
        d += timedelta(days=1)
        self.events_by_date[d].append({"type": "league_bonus"})

        # A season always spans exactly one calendar year (Jan 1 - Dec 31 of
        # start_date's year), regardless of how much slack the schedule left.
        # This guarantees "1 year = 1 season" and that each year's weeks enter
        # the free-agent pool exactly once.
        year_end = date(self.start_date.year, 12, 31)
        if d > year_end:
            raise RuntimeError(
                f"Season {self.season_number} schedule overran its calendar year "
                f"(reached {d}); shorten MATCHDAY_INTERVAL_DAYS or the break constants."
            )
        self.end_date = year_end

    def _assign_initial_squads(self, year):
        """
        Season 1 kickoff — no more "your month's weeks are automatically
        yours". Instead: the PRE-GAME season (year - 1, e.g. 2025 for a
        2026 start) generates its weeks straight into the shared free-agent
        pool, every team starts with empty rosters and base cash, and then
        an initial draft runs the normal transfer-window AI against that
        pool. Teams that come up short on a position buy in; teams that
        land well can stock up further, hold cash, or (in later windows)
        sell surplus — all the same market logic as mid/post-season windows,
        just run enough times up front that every team reaches a legal
        squad (>=1 Forward/Defender/Midfielder) before the season starts.
        """
        pregame_year = year - 1
        weeks = generate_weeks(pregame_year)
        self.free_agents.extend(weeks)

        # Building a squad from scratch costs far more than an incremental
        # in-season top-up, so the draft gets a dedicated preseason budget
        # rather than the same base used for ongoing windows — otherwise
        # teams can only ever afford the bare legal minimum (3 players) and
        # never reach a full matchday lineup (5).
        for month_index, t in enumerate(self.teams.values()):
            days_in_month = _days_in_month(month_index + 1, year)
            t.cash = economy.starting_cash(t, days_in_month) * economy.DRAFT_BUDGET_MULTIPLIER

        scarcity = self._scarcity()
        log = market.run_initial_draft(self.teams, self.free_agents, scarcity)
        print(f"\n--- INITIAL DRAFT ({pregame_year} pre-game season weeks) ---")
        for line in log:
            print(line)
        if not log:
            print("  (no moves)")

    # ------------------------------------------------------------------
    def _scarcity(self):
        pool = [p for t in self.teams.values() for p in t.roster] + self.free_agents
        return market.compute_scarcity_factors(pool)

    def tick(self, verbose_matches=True):
        """Advance exactly one day. Returns a summary dict of what happened."""
        if self.finished:
            return None

        d = self.current_date
        summary = {"date": d, "season": self.season_number, "events": []}

        for ev in self.events_by_date.get(d, []):
            summary["events"].append(self._process_event(ev, verbose_matches))

        next_day = d + timedelta(days=1)
        if next_day.month != d.month or next_day > self.end_date:
            settle_log = self._settle_month()
            if settle_log:
                summary["events"].append({"type": "settlement", "log": settle_log})

        self.current_date = next_day
        if d >= self.end_date:
            self.finished = True
        return summary

    # ------------------------------------------------------------------
    def _process_event(self, ev, verbose_matches):
        if ev["type"] == "match":
            home, away = self.teams[ev["home"]], self.teams[ev["away"]]
            if verbose_matches:
                print(f"\n=== {ev['block']}: {home.name} vs {away.name} ===")
            result = match_engine.play_match(home, away, verbose=verbose_matches)
            self._home_matches_since_settlement[home.name] += 1
            if verbose_matches:
                print(f"FT: {home.name} {result['home_score']} - {result['away_score']} {away.name}")
            return {"type": "match", "result": result}

        if ev["type"] == "transfer_window":
            print(f"\n--- {ev['label']} TRANSFER WINDOW ---")
            log = market.run_transfer_window(self.teams, self.free_agents, self._scarcity())
            for line in log:
                print(line)
            if not log:
                print("  (no moves)")
            return {"type": "transfer_window", "label": ev["label"], "log": log}

        if ev["type"] == "standings":
            self.standings = self._compute_standings()
            self._print_standings()
            return {"type": "standings", "table": self.standings}

        if ev["type"] == "playoffs":
            self.champion = self._run_playoffs()
            return {"type": "playoffs", "champion": self.champion}

        if ev["type"] == "league_bonus":
            log = []
            payout_order = self.final_standings or self.standings
            for rank, name in enumerate(payout_order, start=1):
                economy.pay_league_bonus(self.teams[name], rank, log)
            print("\n--- LEAGUE BONUS PAYOUTS (post-playoff final standings) ---")
            for line in log:
                print(line)
            return {"type": "league_bonus", "log": log}

        return {"type": "unknown"}

    # ------------------------------------------------------------------
    def _settle_month(self):
        scarcity = self._scarcity()
        log = []
        any_distress = False
        for name, team in self.teams.items():
            played = self._home_matches_since_settlement.get(name, 0)
            distressed = economy.settle_month(team, played, scarcity, log)
            any_distress = any_distress or distressed
        if log:
            print(f"\n--- MONTH-END SETTLEMENT ({self.current_date.strftime('%B %Y')}) ---")
            for line in log:
                print(line)
        self._home_matches_since_settlement.clear()
        return log

    def compute_standings(self):
        def points(team):
            return sum({"W": 3, "D": 1, "L": 0}[r] for r in team.match_history)
        ranked = sorted(self.teams.values(), key=lambda t: (-points(t), -t.legacy_rating))
        return [t.name for t in ranked]

    # kept as an alias since season.py's internal calls use the old name
    _compute_standings = compute_standings

    def _print_standings(self, table=None, label=None):
        table = table if table is not None else self.standings
        label = label or f"SEASON {self.season_number} FINAL STANDINGS"
        print(f"\n=== {label} ===")
        for i, name in enumerate(table, start=1):
            t = self.teams[name]
            pts = sum({"W": 3, "D": 1, "L": 0}[r] for r in t.match_history)
            w = t.match_history.count("W"); d = t.match_history.count("D"); l = t.match_history.count("L")
            print(f" {i:2d}. {name:9s}  P{w+d+l:2d}  W{w:2d} D{d:2d} L{l:2d}  Pts {pts:3d}  LR {t.legacy_rating}")

    # ------------------------------------------------------------------
    def _run_playoffs(self):
        print(f"\n=== SEASON {self.season_number} PLAYOFFS ===")
        bracket = schedule.make_playoff_bracket(self.standings)
        seeds = bracket["seeds"]
        seed_of = {name: num for num, name in seeds.items()}

        def play(label, home_name, away_name):
            """Play a knockout match; draws go to penalties. Returns (winner, loser)."""
            home, away = self.teams[home_name], self.teams[away_name]
            print(f"\n--- {label}: {home_name} vs {away_name} ---")
            with home.matchday(), away.matchday():
                r = match_engine._play_match_inner(home, away, verbose=True)
                print(f"FT: {home_name} {r['home_score']} - {r['away_score']} {away_name}")
                if r["result"] == "home_win":
                    winner, loser = home_name, away_name
                elif r["result"] == "away_win":
                    winner, loser = away_name, home_name
                else:
                    winner, _, _ = match_engine.resolve_penalties(home, away, verbose=True)
                    loser = away_name if winner == home_name else home_name
            print(f"  -> {winner} advances")
            return winner, loser

        w1, l1 = play("Play-in 3v6", bracket["play_in"][0]["home"], bracket["play_in"][0]["away"])
        w2, l2 = play("Play-in 4v5", bracket["play_in"][1]["home"], bracket["play_in"][1]["away"])

        semi1_winner, semi1_loser = play("Semifinal (1 vs winner 4/5)", seeds[1], w2)
        semi2_winner, semi2_loser = play("Semifinal (2 vs winner 3/6)", seeds[2], w1)

        third, fourth = play("3rd Place Playoff", semi1_loser, semi2_loser)
        champion, runner_up = play("FINAL", semi1_winner, semi2_winner)

        print(f"\n*** SEASON {self.season_number} CHAMPION: {champion} ***")

        # 5th/6th: the two play-in losers, ordered by their better original seed
        fifth, sixth = sorted([l1, l2], key=lambda n: seed_of[n])

        top_six = [champion, runner_up, third, fourth, fifth, sixth]
        rest = [n for n in self.standings if n not in top_six]  # already in regular-season order
        self.final_standings = top_six + rest

        print(f"\n=== SEASON {self.season_number} FINAL STANDINGS (post-playoffs) ===")
        for i, name in enumerate(self.final_standings, start=1):
            print(f" {i:2d}. {name}")

        return champion

    # ------------------------------------------------------------------
    def next_season(self):
        return Season(
            season_number=self.season_number + 1,
            start_date=self.end_date + timedelta(days=1),
            teams=self.teams,
            free_agents=[p for p in self.free_agents],  # unsold weeks carry over
        )
