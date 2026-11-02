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


def player_points_since(league, player_cache, player_name, since_dt):
    """How a traded player has performed since the trade: total fantasy
    points, games played, and points-per-game, counting only weeks whose
    actual game date falls after `since_dt`. Mirrors the "who's winning this
    trade" view from the standalone trade tracker: each player's post-trade
    production is what decides which side came out ahead.

    Returns None if the player can't be looked up or has no post-trade game
    data yet (e.g. traded this week, byes, no more games this season).
    """
    if not player_name or since_dt is None:
        return None
    if player_name in player_cache:
        player = player_cache[player_name]
    else:
        try:
            player = league.player_info(name=player_name)
        except Exception:
            player = None
        if isinstance(player, list):
            player = player[0] if player else None
        player_cache[player_name] = player
    if not player:
        return None

    schedule = getattr(player, "schedule", None) or {}
    stats = getattr(player, "stats", None) or {}
    total = 0.0
    games = 0
    for week, game in schedule.items():
        game_date = game.get("date") if isinstance(game, dict) else None
        if not game_date or game_date <= since_dt:
            continue
        # espn_api's Player.schedule is keyed by scoring-period-id STRINGS
        # (e.g. "1", "2", ...) straight from the raw JSON, while Player.stats
        # is keyed by the same scoring period as an INT. Without normalizing,
        # stats.get(week) always misses and every player looks like they had
        # "no games since trade" even when they clearly played.
        try:
            week_num = int(week)
        except (TypeError, ValueError):
            week_num = week
        week_stats = stats.get(week_num)
        if week_stats is None:
            week_stats = stats.get(week)
        if not week_stats or "points" not in week_stats:
            continue  # bye week, or game not played/scored yet
        total += week_stats["points"] or 0
        games += 1
    if games == 0:
        return {"total": 0.0, "games": 0, "ppg": None}
    return {"total": round(total, 2), "games": games, "ppg": round(total / games, 2)}


def build_week_date_map(league):
    """Maps scoring-period/week number -> an actual game date for that week,
    built by merging every rostered player's own schedule. This data is
    already loaded on the league/team objects (no extra network calls), and
    since every NFL week's games fall in the same date range regardless of
    which player you look at, merging across all rosters just fills in the
    weeks any single player happened to have a bye for. Used to figure out
    which week a trade's "since the trade" window starts in."""
    week_date = {}
    for team in getattr(league, "teams", []) or []:
        for player in getattr(team, "roster", []) or []:
            schedule = getattr(player, "schedule", None) or {}
            for week, game in schedule.items():
                game_date = game.get("date") if isinstance(game, dict) else None
                if not game_date:
                    continue
                try:
                    week_num = int(week)
                except (TypeError, ValueError):
                    continue
                if week_num not in week_date:
                    week_date[week_num] = game_date
    return week_date


def team_record_since(team, start_week):
    """A team's own win-loss-tie record from `start_week` (inclusive)
    onward, using its per-week outcomes list (team.outcomes[0] = week 1,
    team.outcomes[1] = week 2, etc). Only counts decided games - weeks not
    yet played show up as 'U' (undecided) and are skipped rather than
    counted as losses."""
    if team is None or start_week is None:
        return None
    outcomes = getattr(team, "outcomes", None) or []
    wins = losses = ties = 0
    for idx, outcome in enumerate(outcomes):
        week_num = idx + 1
        if week_num < start_week:
            continue
        if outcome == "W":
            wins += 1
        elif outcome == "L":
            losses += 1
        elif outcome == "T":
            ties += 1
        # 'U' (undecided/not yet played) or anything else: skip.
    if wins == 0 and losses == 0 and ties == 0:
        return None
    return {"wins": wins, "losses": losses, "ties": ties}


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
        "waiver_adds": [],
        "errors": [],
    }

    try:
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=ESPN_SWID)
    except Exception as e:
        season["errors"].append(f"Could not load league for {year}: {e}")
        return season

    num_teams = len(getattr(league, "teams", []) or [])
    teams_by_id = {t.team_id: t for t in getattr(league, "teams", []) or []}
    week_date_map = build_week_date_map(league)

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
    # espn_api emits TWO action rows per traded player - one "TRADE_SENT" (from
    # the team giving the player up) and one "TRADE_RECEIVED" (for the team
    # getting the player) - so every player in a trade shows up twice in
    # act.actions. Group by player and pair up the SENT/RECEIVED rows so each
    # player appears exactly once, with a real from -> to direction, instead
    # of the raw duplicate list.
    player_perf_cache = {}
    try:
        activity = league.recent_activity(size=2000, msg_type="TRADED")
        for act in activity:
            try:
                raw_date = getattr(act, "date", None)
                trade_date_dt = datetime.datetime.utcfromtimestamp(raw_date / 1000) if raw_date else None
                trade_date = trade_date_dt.isoformat() + "Z" if trade_date_dt else None
                by_player = {}
                order = []
                team_meta = {}
                for action in getattr(act, "actions", []) or []:
                    a_team = action[0] if len(action) > 0 else None
                    a_type = action[1] if len(action) > 1 else None
                    a_player = action[2] if len(action) > 2 else None
                    team_name = getattr(a_team, "team_name", None)
                    player_name = getattr(a_player, "name", None) or (str(a_player) if a_player else None)
                    if team_name and team_name not in team_meta:
                        team_meta[team_name] = {
                            "id": getattr(a_team, "team_id", None),
                            "owner": safe_owner_name(a_team),
                        }
                    if not player_name:
                        continue
                    if player_name not in by_player:
                        by_player[player_name] = {"player": player_name, "from_team": None, "to_team": None}
                        order.append(player_name)
                    if a_type == "TRADE_SENT":
                        by_player[player_name]["from_team"] = team_name
                    elif a_type == "TRADE_RECEIVED":
                        by_player[player_name]["to_team"] = team_name
                    elif team_name and not by_player[player_name]["to_team"]:
                        # Fallback for any unexpected action shape - at least
                        # keep one team attached to the player.
                        by_player[player_name]["to_team"] = team_name

                items = [by_player[name] for name in order]
                teams_involved = []
                for item in items:
                    for t in (item["from_team"], item["to_team"]):
                        if t and t not in teams_involved:
                            teams_involved.append(t)

                # --- Post-trade performance: who's winning this trade so far? ---
                # For each player, total up fantasy points scored since the
                # trade date, then sum that by the team that RECEIVED each
                # player, to get each side's "value gained" and declare a
                # leader - the same thing the standalone trade tracker did
                # by hand, computed live from this season's data.
                side_totals = {}
                any_perf = False
                for item in items:
                    perf = player_points_since(league, player_perf_cache, item["player"], trade_date_dt)
                    item["points_since_trade"] = perf["total"] if perf else None
                    item["games_since_trade"] = perf["games"] if perf else None
                    item["ppg_since_trade"] = perf["ppg"] if perf else None
                    side = item["to_team"]
                    if side and perf and perf["games"]:
                        side_totals[side] = side_totals.get(side, 0.0) + perf["total"]
                        any_perf = True

                verdict = None
                if any_perf and len(side_totals) >= 2:
                    ranked = sorted(side_totals.items(), key=lambda kv: kv[1], reverse=True)
                    leader_team, leader_pts = ranked[0]
                    other_team, other_pts = ranked[1]
                    diff = round(leader_pts - other_pts, 2)
                    verdict = {
                        "side_totals": {k: round(v, 2) for k, v in side_totals.items()},
                        "leader_team": leader_team if diff > 0 else None,
                        "margin": abs(diff),
                    }

                # --- Record since the trade ---
                # Each involved team's own win-loss-tie record starting the
                # first week after the trade date, so the card can show
                # "how has each side done since" at the team level, not just
                # the traded players' individual stats.
                team_owners = {name: team_meta.get(name, {}).get("owner", "Unknown") for name in teams_involved}
                start_week = None
                if trade_date_dt:
                    future_weeks = [w for w, d in week_date_map.items() if d and d > trade_date_dt]
                    if future_weeks:
                        start_week = min(future_weeks)

                records_since_trade = {}
                for team_name in teams_involved:
                    team_id = team_meta.get(team_name, {}).get("id")
                    team_obj = teams_by_id.get(team_id)
                    rec = team_record_since(team_obj, start_week)
                    if rec:
                        records_since_trade[team_name] = rec

                season["trades"].append(
                    {
                        "date": trade_date,
                        "teams_involved": teams_involved,
                        "team_owners": team_owners,
                        "items": items,
                        "verdict": verdict,
                        "records_since_trade": records_since_trade,
                    }
                )
            except Exception as e:
                season["errors"].append(f"Trade parse error for {year}: {e}")
    except Exception as e:
        season["errors"].append(f"Could not fetch trades for {year}: {e}")

    # --- Waiver wire / free agent adds & drops ---
    # A single ESPN activity topic (`act`) can bundle multiple moves a team
    # made at once - most commonly a waiver claim that adds one player and
    # drops another in the same transaction. Group actions by team within
    # each activity and pair up ADDED/DROPPED entries in order, so a claim
    # shows both halves (who came in, who got cut) instead of just the add
    # with no context. A bare drop (cutting a player with no add attached)
    # or a bare add (empty roster spot, no corresponding drop) still shows
    # up as its own row with the other side left blank.
    try:
        add_activity = league.recent_activity(size=2000, msg_type=None)
        for act in add_activity:
            try:
                raw_date = getattr(act, "date", None)
                act_date = (
                    datetime.datetime.utcfromtimestamp(raw_date / 1000).isoformat() + "Z" if raw_date else None
                )
                by_team = {}
                team_order = []
                for action in getattr(act, "actions", []) or []:
                    a_team = action[0] if len(action) > 0 else None
                    a_type = action[1] if len(action) > 1 else None
                    a_player = action[2] if len(action) > 2 else None
                    a_bid = action[3] if len(action) > 3 else 0
                    if a_type not in ("FA ADDED", "WAIVER ADDED", "DROPPED"):
                        continue
                    team_name = getattr(a_team, "team_name", None)
                    player_name = getattr(a_player, "name", None) or (str(a_player) if a_player else None)
                    if not player_name:
                        continue
                    key = team_name or "Unknown"
                    if key not in by_team:
                        by_team[key] = {
                            "owner": safe_owner_name(a_team) if a_team else "Unknown",
                            "added": [],
                            "dropped": [],
                        }
                        team_order.append(key)
                    if a_type == "DROPPED":
                        by_team[key]["dropped"].append(player_name)
                    else:
                        by_team[key]["added"].append(
                            (player_name, "Waiver" if a_type == "WAIVER ADDED" else "Free Agent", a_bid or 0)
                        )

                for team_name in team_order:
                    bucket = by_team[team_name]
                    added = bucket["added"]
                    dropped = bucket["dropped"]
                    for i in range(max(len(added), len(dropped))):
                        add_info = added[i] if i < len(added) else None
                        drop_name = dropped[i] if i < len(dropped) else None
                        season["waiver_adds"].append(
                            {
                                "date": act_date,
                                "team": team_name,
                                "owner": bucket["owner"],
                                "player_added": add_info[0] if add_info else None,
                                "player_dropped": drop_name,
                                "type": add_info[1] if add_info else "Drop",
                                "bid_amount": add_info[2] if add_info else 0,
                            }
                        )
            except Exception as e:
                season["errors"].append(f"Waiver add parse error for {year}: {e}")
    except Exception as e:
        season["errors"].append(f"Could not fetch waiver adds for {year}: {e}")

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
