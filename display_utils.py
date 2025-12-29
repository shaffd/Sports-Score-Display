# Display Utilities File
# ----------------------
# This file provides utility functions for formatting the game data pulled from the
# data_fetcher.py file (dictionaries of data), before passing to the rendering layer

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from data_fetcher import DataFetcher
from typing import Any

# Helper: convert UTC ISO string -> Eastern HH:MM
# Includes Linux (for the Pi) formatting and a Windows fallback
def format_start_time(utc_str: str | None) -> str:
    if not utc_str:
        return "M. S. D"    # (Missing Start Data)
    try:
        # Convert UTC string to datetime
        utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))

        # Convert to US / Eastern timezone
        est_dt = utc_dt.astimezone(ZoneInfo("America/New_York"))

        # Format as "hour:minute AM/PM"
        # Linux format first
        try:
            return est_dt.strftime("%-I:%M %p").lstrip("0")
        except ValueError:
            # Windows fallback
            return est_dt.strftime("%#I:%M %p").lstrip("0")
        
    except Exception as e:
        print("FORMAT TIME ERROR (DEBUG):", utc_str, e)
        return "TBD"

# ---- MLB Section ----

def format_mlb_display(game: dict[str, Any]) -> dict[str, Any]:
    """
    Format MLB game data
    Input: dict from get_yankees_live_game() function in data_fetcher.py
    Output: dict with home/away logos, scores, status, markers for innings
    """
    home = game["home_team"]
    away = game["away_team"]

    status = game.get("status", "")
    inning = game.get("inning")
    half = game.get("inning_half", "").upper()

    # Status text display
    if status == "Final":
        status_text = "Final"
    elif status == "In Progress":
        status_text = f"In Progress: {half} {inning}"
    else:
        # Display UTC start time
        status_text = format_start_time(game.get("start_time", ""))

    # Marker for team at bat
    at_bat_marker = "home" if half == "BOT" else "away" if half == "TOP" else None

    return {
        "sport": "mlb",
        "type": "game",          # "type" so it's consistent with the 'header' card   
        "home_logo": home,       # renderer layer will resolve the name to logo
        "away_logo": away,
        "home_score": game["home_score"],
        "away_score": game["away_score"],
        "status_text": status_text,
        "marker": at_bat_marker     # At bat / inning half marker
    }

# ---- NHL Section ----

def format_nhl_display(game: dict[str, Any]) -> dict[str, Any]:
    """
    Format NHL game data
    Input: dict from get_rangers_live_game() function in data_fetcher.py
    Output: dict with home/away logos, scores, status
    """
    home = game["home_team"]
    away = game["away_team"]

    status = game.get("status")
    period = game.get("period")
    period_type = game.get("period_type")   # "REG" "OT" "SO" or None
    time_rem = game.get("time_remaining")
    intermission = game.get("intermission", False)

    if status in ("FUT", "PRE"):
        print("DEBUG start_time =", game.get("start_time")) # TEMPORARY debug line
        status_text = format_start_time(game.get("start_time"))
    
    elif status in ("FINAL", "OFF"):
        status_text = "FINAL"
    
    elif status in ("LIVE", "CRIT"):
        # Intermission
        if intermission:
            status_text = "INT"
        
        # Shootout
        elif period_type == "SO":
            status_text = "SO"

        # Overtime
        elif period_type == "OT":
            status_text = "OT"

        # Intermission
        elif intermission:
            status_text = "INT"
        
        # Regular play
        else:
            status_text = f"{time_rem} PER {period}"
    else: 
        status_text = format_start_time(game.get("start_time"))

    return {
        "sport": "nhl",
        "type": "game",          # "type" so it's consistent with the 'header' card
        "home_logo": home,       # renderer layer will resolve the name to logo
        "away_logo": away,
        "home_score": game["home_score"],
        "away_score": game["away_score"],
        "status_text": status_text,
        "marker": None,         # No marker needed for hockey
    }

# ---- NFL Section ----

def format_nfl_display(game: dict[str, Any]) -> dict[str, Any]:
    """
    Format NFL game data
    Input: dict from get_lions_live_game() function in data_fetcher.py
    Output: dict with home/away logos, scores, status, marker for ball pos.
    """
    home = game.get("home_abbrev") #or game.get("home_team") or ""
    away = game.get("away_abbrev") #or game.get("away_team") or ""
    
    # home_logo = game.get("home_logo", "")
    # away_logo = game.get("away_logo", "")
    home_abbrev = game.get("home_abbrev", "")
    away_abbrev = game.get("away_abbrev", "")
    home_score = game.get("home_score", "")
    away_score = game.get("away_score", "")

    status = game.get("status", "")
    quarter = game.get("quarter")
    clock = game.get("clock")
    possession = game.get("possession") # team name will already be abbreviated from the lookup function

    if status == "Final":
        status_text = "Final"
    elif status in ("In Progress", "Live"):
        status_text = f"In Progress: {clock} QTR {quarter}"
    elif status == "Halftime":
        status_text = "Halftime"
    else:
        status_text = format_start_time(game.get("start_time", ""))
    
    # Marker for team with possession
    marker = None
    if possession == home:
        marker = "home"
    elif possession == away:
        marker = "away"

    return {
        "sport": "nfl",
        "type": "game",          # "type" so it's consistent with the 'header' card
        "home_logo": home_abbrev or home,   # home_logo
        "away_logo": away_abbrev or away,     # away_logo
        "home_score": home_score,
        "away_score": away_score,
        "status_text": status_text,
        "marker": marker,
    }

def get_results(fetcher: DataFetcher):
    """
    Function to grab yesterday's results and today's upcoming games
    Returns a list of standardized dicts that are ready for rendering
    Part of the returned dict is the relevant header 'card' for each sport
    """
    results = []
    
    # Dates
    today = datetime.now()
    yesterday = today - timedelta(days = 1)
    tomorrow = today + timedelta(days = 1)

    # MLB and NHL date formatting
    mlb_nhl_dates = [
        yesterday.strftime("%Y-%m-%d"),
        today.strftime("%Y-%m-%d"),
    ]
    
    # NFL date formatting:
    nfl_dates = [
        yesterday.strftime("%Y%m%d"),
        today.strftime("%Y%m%d"),
        tomorrow.strftime("%Y%m%d")
    ]
    
    # Creating a flag to check if there are no games at all
    any_game = False

    # MLB
    mlb_games_all = []
    for date in mlb_nhl_dates:
        mlb_games = fetcher.get_mlb_daily_schedule(date)
        games = mlb_games.get("games", []) if isinstance(mlb_games, dict) else mlb_games
        #if mlb_games and mlb_games.get("games"):
        for game in games:
            mlb_games_all.append(format_mlb_display(game))
    
    if mlb_games_all:
        any_game = True
        results.append({"sport": "mlb", "type": "header", "title": "MLB"})
        results.extend(mlb_games_all)
    
    # NHL
    nhl_games_all = []
    #for date in mlb_nhl_dates:
    nhl_games = fetcher.get_nhl_daily_schedule()

    num_games = len(nhl_games.get("games", []))
    print(f"Retrieved NHL schedule for {today.strftime("%Y-%m-%d")} and {yesterday.strftime("%Y-%m-%d")}: {num_games} games")
    
    games = nhl_games.get("games", []) 
    
    for game in games:
        nhl_games_all.append(format_nhl_display(game))

    if nhl_games_all:
        any_game = True
        results.append({"sport": "nhl", "type": "header", "title": "NHL"})
        results.extend(nhl_games_all)
    
    # DEBUG Lines
    # print("NHL games received:", len(nhl_games_all))
    # for g in nhl_games_all:
    #     print(g)
    
    # NFL
    nfl_games_all = []
    for date in nfl_dates:
        nfl_games = fetcher.get_nfl_daily_schedule(date)
        games = nfl_games.get("games", []) if isinstance(nfl_games, dict) else nfl_games

        # Debug line
        if games:
            print(f"\nDEBUG NFL GAMES FETCHED ({date}):", games[0]) # this will show first game only
        else:
            print(f"\nDEBUG NFL GAMES FETCHED({date}): No games returned")

        for game in games:
            nfl_games_all.append(format_nfl_display(game))

    if nfl_games_all:
        any_game = True
        results.append({"sport": "nfl", "type": "header", "title": "NFL"})
        results.extend(nfl_games_all)
    
    # Fallback if no games
    if not any_game:
        return [{"type": "message", "title": "No games today"}]
    
    # DEBUG Lines
    print("NFL games received:", len(nfl_games_all))
    for g in nfl_games_all:
        print(g)
    
    return results