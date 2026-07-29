# Monthball

A calendar-driven football league sim: **months are teams**, **weeks are players**.
Every player and team stat is a deterministic function of solar astronomy
(elevation, daylight length) for a given date and latitude — no random rolls
in stat generation, only in match outcomes.

## Quick start

```bash
git clone <your-repo-url>
cd monthball
python3 main.py
```

No dependencies beyond the Python 3 standard library.

## How it works

- **Players** = ISO-ish weeks of a year (`2026-W01`, `2026-W02`, ...). Each has
  5 stats (`attack`, `defense`, `pace`, `consistency`, `potential`) derived
  from that week's solar elevation/daylight, plus a derived `position`
  (Forward / Midfielder / Defender).
- **Teams** = the 12 months. Their 10 stats mostly *emerge* from the current
  roster (blended by position), except `home_form` (fixture-intrinsic) and
  `momentum` (recent form).
- **Matches** are resolved as a series of tactical exchanges (4 per half,
  plus decaying-probability extra time), not a single stat comparison. Each
  exchange pits an attacking strategy against a defensive counter chosen by
  a simple epsilon-greedy bandit that learns from past exchanges. See
  `monthball/strategies.py` for the full strategy/counter table.
- **Economy**: `club_worth` (sum of scarcity-adjusted player values) and
  `cash` (settled monthly: home-match revenue + sponsorship, minus wages).
  Two transfer windows per season (mid-season + post-season) run a
  rule-based, explainable AI per team: find your biggest weakness, buy the
  best-value fix you can afford, or list your weakest player if you can't.
- **Season**: double round-robin (22 games/team) → top 2 seeds bye to semis,
  seeds 3-6 play a knockout for the last 2 spots → semis → final + 3rd place
  playoff → league bonus payout tiered by final rank → next season's weeks
  enter the pool as free agents.

## CLI commands

Run `python3 main.py`, then at the `>` prompt:

| Command | What it does |
|---|---|
| *(enter)* / `n` | advance one day |
| `n <k>` | advance k days |
| `run` | auto-run the rest of the current season with no pauses |
| `standings` | show the league table (once the season has finished round 2) |
| `team <Month>` | show a team's full stat line and roster |
| `schedule` | list upcoming fixtures/events |
| `verbose` / `quiet` | toggle whether tactics exchanges print live during matches |
| `season` | start the next season (once the current one is finished) |
| `quit` | exit |

## Project layout

```
monthball/
  astronomy.py     solar elevation / daylight — the root of every stat
  player.py         Player (week) entity + 5 base stats
  team.py           Team (month) entity + 10 emergent stats
  strategies.py      attacking strategies, defensive counters, matchups
  market.py          valuation, wages, rule-based transfer AI
  match_engine.py    the exchange-by-exchange match simulator
  schedule.py         double round-robin + playoff bracket generation
  economy.py          monthly settlement + end-of-season prize money
  season.py            orchestrator: the daily tick loop
main.py                CLI
```

## Tuning knobs worth knowing about

- `astronomy.LATITUDE` — reference latitude used for every stat calc.
- `match_engine.EPSILON` / `COUNTERATTACK_CHANCE` — bandit exploration rate
  and how often a failed attack flips into a turnover chance.
- `market.WAGE_RATE` and the constants at the top of `economy.py` — controls
  how tight team finances are.
- `season.MATCHDAY_INTERVAL_DAYS` / `MID_WINDOW_BREAK_DAYS` — calendar pacing.

## Notes / simplifications

- The transfer AI resolves bids in a fixed team order each window rather
  than simulating simultaneous competing bids.
- Playoff matches all resolve within the single calendar day their event is
  scheduled on, rather than being spread across further daily ticks.
- `home_form` uses a fixed reference year (2026) for its weekend-day count,
  since the league schedule itself is treated as year-agnostic.
