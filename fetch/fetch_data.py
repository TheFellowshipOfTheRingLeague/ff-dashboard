#!/usr/bin/env python3
"""
Fetches ESPN fantasy football league history (standings, records,
championships, draft picks, and trades) for every season from START_YEAR
through the current season, and writes one consolidated JSON file for the
dashboard to read.

Reads configuration from environment variables:
  LEAGUE_ID   - ESPN league ID (required)
  ESPN_S2     - ESPN "espn_s2" cookie value (required for private leagues)
  ESPN_SWID   - ESPN "SWID" cookie value (required for private leagues)
  START_YEAR  - first season to include (default: 2021)

Writes: data/league_history.json

This script is intentionally defensive: a problem fetching one season, one
team, one draft pick, or one trade is logged as a warning and skipped rather
than crashing the whole run, so a partial ESPN outage or a format quirk in
one old season doesn't block the daily refresh for every other season.
"""
import datetime
import json
import os
import sys

from espn_api.football import League

LEAGUE_ID_RAW = os.environ.get("LEAGUE_ID")
ESPN_S2 = os.environ.get("ESPN_S2") or None
ESPN_SWID = os.environ.get("ESPN_SWID") or None
START_YEAR = int(os.environ.get("START_YEAR", "2021"))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO_ROOT, "data", "league_history.json")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


if not LEAGUE_ID_RAW:
    fail("LEAGUE_ID environment variable is required.")

try:
    LEAGUE_ID = int(LEAGUE_ID_RAW)
except ValueError:
    fail(f"LEAGUE_ID must be numeric, got: {LEAGUE_ID_RAW!r}")


def current_season_year():
    """NFL/fantasy seasons are labeled by the calendar year they start in
    (e.g. the 2026 season runs Sept 2026 - Jan/Feb 2027). If we're running
    in Jan/Feb, the season that just finished is still last calendar year."""
    today = datetime.date.today()
    return today.year if today.month >= 3 else today.year - 1


END_YEAR = current_season_year()


def owner_name_from_dict(owner):
    if not owner:
        return None
    first = (owner.get("firstName") or "").strip()
    last = (owner.get("lastName") or "").strip()
    name = f"{first} {last}".strip()
    return name or owner.get("id")


def safe_owner_name(team):
    """Stable-ish identity for a team's owner, used to merge the same
    manager's records across seasons even if their team name changes."""
    if team is None:
        return "Unknown"
    try:
        owners = getattr(team, "owners", None) or []
    except Exception:
        owners = []
    for owner in owners:
        if isinstance(owner, dict):
            name = owner_name_from_dict(owner)
            if name:
                return name
        elif isinstance(owner, str) and owner.strip():
            return owner.strip()
    return getattr(team, "team_name", None) or f"Team {getattr(team, 'team_id', '?')}"


def fetch_season(year):
    print(f"Fetching season {year}...")
    season = {
        "year": year,
        "teams": [],
        "champion": None,
        "runner_up": None,
        "season_complete": False,
        "draft": [],
        "trades": [],
        "errors": [],
    }

    try:
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=ESPN_SWID)
    except Exception as e:
        season["errors"].append(f"Could not load league for {year}: {e}")
        return season

    num_teams = len(getattr(league, "teams", []) or [])

    # --- Has this season actually finished? ---
    # ESPN reports a "final_standing"/"standing" rank throughout the season,
    # not just after it ends, so without this check a team merely leading
    # mid-season would get mislabeled as league champion. A past season
    # (year < the season currently being played) is always finished. For the
    # season currently in progress, compare how many matchup periods have
    # been played (currentMatchupPeriod) against how many the league's
    # schedule has in total (settings.reg_season_count, which spans the
    # playoffs too) - the season is only finished once that's exceeded.
    current_mp = getattr(league, "currentMatchupPeriod", None)
    total_mp = getattr(getattr(league, "settings", None), "reg_season_count", None)
    season_complete = year < END_YEAR or (
        current_mp is not None and total_mp is not None and current_mp > total_mp
    )
    season["season_complete"] = season_complete

    # --- Standings / season records ---
    for team in getattr(league, "teams", []):
        try:
            final_rank = getattr(team, "final_standing", None) or getattr(team, "standing", None)
            if final_rank in (0,):
                final_rank = None
            season["teams"].append(
                {
                    "team_id": team.team_id,
                    "team_name": getattr(team, "team_name", f"Team {team.team_id}"),
                    "owner": safe_owner_name(team),
                    "wins": getattr(team, "wins", None),
                    "losses": getattr(team, "losses", None),
                    "ties": getattr(team, "ties", 0) or 0,
                    "points_for": round(getattr(team, "points_for", 0) or 0, 2),
                    "points_against": round(getattr(team, "points_against", 0) or 0, 2),
                    "final_rank": final_rank,
                }
            )
        except Exception as e:
            season["errors"].append(f"Team parse error (team_id={getattr(team, 'team_id', '?')}): {e}")

    # --- Champion / runner-up (only once the season has actually finished) ---
    if season_complete:
        ranked = [t for t in season["teams"] if t["final_rank"]]
        if ranked:
            ranked.sort(key=lambda t: t["final_rank"])
            season["champion"] = {"team_id": ranked[0]["team_id"], "team_name": ranked[0]["team_name"], "owner": ranked[0]["owner"]}
            if len(ranked) > 1:
                season["runner_up"] = {"team_id": ranked[1]["team_id"], "team_name": ranked[1]["team_name"], "owner": ranked[1]["owner"]}
        else:
            try:
                standings = league.standings()
                if standings:
                    champ = standings[0]
                    season["champion"] = {
                        "team_id": champ.team_id,
                        "team_name": getattr(champ, "team_name", ""),
                        "owner": safe_owner_name(champ),
                    }
                    if len(standings) > 1:
                        ru = standings[1]
                        season["runner_up"] = {
                            "team_id": ru.team_id,
                            "team_name": getattr(ru, "team_name", ""),
                            "owner": safe_owner_name(ru),
                        }
            except Exception as e:
                season["errors"].append(f"Could not determine champion via standings() for {year}: {e}")

    # --- Draft ---
    try:
        for pick in getattr(league, "draft", []) or []:
            try:
                team = getattr(pick, "team", None)
                round_num = getattr(pick, "round_num", None)
                round_pick = getattr(pick, "round_pick", None)
                overall_pick = None
                if round_num and round_pick and num_teams:
                    overall_pick = (round_num - 1) * num_teams + round_pick
                season["draft"].append(
                    {
                        "round": round_num,
                        "round_pick": round_pick,
                        "overall_pick": overall_pick,
                        "team_id": getattr(team, "team_id", None) if team else None,
                        "team_name": getattr(team, "team_name", "") if team else "",
                        "owner": safe_owner_name(team) if team else "Unknown",
                        "player_name": getattr(pick, "playerName", None),
                        "keeper": bool(getattr(pick, "keeper_status", False)),
                    }
                )
            except Exception as e:
                season["errors"].append(f"Draft pick parse error for {year}: {e}")
    except Exception as e:
        season["errors"].append(f"Could not fetch draft for {year}: {e}")

    # --- Trades ---
    try:
        activity = league.recent_activity(size=2000, msg_type="TRADED")
        for act in activity:
            try:
                raw_date = getattr(act, "date", None)
                trade_date = (
                    datetime.datetime.utcfromtimestamp(raw_date / 1000).isoformat() + "Z" if raw_date else None
                )
                teams_involved = []
                items = []
                for action in getattr(act, "actions", []) or []:
                    a_team = action[0] if len(action) > 0 else None
                    a_player = action[2] if len(action) > 2 else None
                    team_name = getattr(a_team, "team_name", None)
                    if team_name and team_name not in teams_involved:
                        teams_involved.append(team_name)
                    items.append(
                        {
                            "team": team_name,
                            "player": getattr(a_player, "name", None) or (str(a_player) if a_player else None),
                        }
                    )
                season["trades"].append({"date": trade_date, "teams_involved": teams_involved, "items": items})
            except Exception as e:
                season["errors"].append(f"Trade parse error for {year}: {e}")
    except Exception as e:
        season["errors"].append(f"Could not fetch trades for {year}: {e}")

    return season


def build_all_time(seasons):
    by_owner = {}
    for season in seasons:
        for t in season["teams"]:
            owner = t["owner"] or "Unknown"
            rec = by_owner.setdefault(
                owner,
                {
                    "owner": owner,
                    "team_names": set(),
                    "championships": 0,
                    "runner_up_finishes": 0,
                    "wins": 0,
                    "losses": 0,
                    "ties": 0,
                    "points_for": 0.0,
                    "points_against": 0.0,
                    "seasons_played": 0,
                },
            )
            rec["team_names"].add(t["team_name"])
            rec["wins"] += t["wins"] or 0
            rec["losses"] += t["losses"] or 0
            rec["ties"] += t["ties"] or 0
            rec["points_for"] += t["points_for"] or 0
            rec["points_against"] += t["points_against"] or 0
            rec["seasons_played"] += 1

        if season.get("champion"):
            owner = season["champion"]["owner"] or "Unknown"
            if owner in by_owner:
                by_owner[owner]["championships"] += 1
        if season.get("runner_up"):
            owner = season["runner_up"]["owner"] or "Unknown"
            if owner in by_owner:
                by_owner[owner]["runner_up_finishes"] += 1

    all_time = []
    for owner, rec in by_owner.items():
        games = rec["wins"] + rec["losses"] + rec["ties"]
        win_pct = round((rec["wins"] + 0.5 * rec["ties"]) / games, 3) if games else 0.0
        all_time.append(
            {
                "owner": owner,
                "team_names": sorted(rec["team_names"]),
                "championships": rec["championships"],
                "runner_up_finishes": rec["runner_up_finishes"],
                "wins": rec["wins"],
                "losses": rec["losses"],
                "ties": rec["ties"],
                "win_pct": win_pct,
                "points_for": round(rec["points_for"], 2),
                "points_against": round(rec["points_against"], 2),
                "seasons_played": rec["seasons_played"],
            }
        )

    all_time.sort(key=lambda r: (-r["championships"], -r["win_pct"], -r["points_for"]))
    return all_time


def main():
    seasons = [fetch_season(year) for year in range(START_YEAR, END_YEAR + 1)]

    output = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "league_id": LEAGUE_ID,
        "start_year": START_YEAR,
        "current_season_year": END_YEAR,
        "seasons": seasons,
        "all_time": build_all_time(seasons),
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {OUT_PATH}")

    any_warnings = False
    for s in seasons:
        if s.get("errors"):
            any_warnings = True
            print(f"[warnings for {s['year']}]")
            for e in s["errors"]:
                print(f"  - {e}")

    if not any_warnings:
        print("No warnings.")


if __name__ == "__main__":
    main()
