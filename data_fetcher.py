# This module creates objects to utilize the relevant sports APIs to fetch
# relevant scores for each sport

import requests
from datetime import datetime, timedelta
import pytz
import json # Can use this to pretty-print the results
from pprint import pprint

class DataFetcher:
    NHL_BASE = "https://api-web.nhle.com/v1"
    MLB_BASE = "https://statsapi.mlb.com/api/v1"

    def __init__(self):
        """Initialization. Storing the gamePk here to be able to call for the live game methods"""
        # NHL
        self.rangers_team_id = 3
        self.rangers_gamePk = None

        # NFL
        self.lions_team_id = "8"    # Lions team ID in ESPN API
        self.lions_gameId = None
        self.nfl_team_lookup = {}
        self.build_nfl_team_lookup()

        # MLB
        self.yankees_team_id = "147"
        self.yankees_gamePk = None
      
    def get_nhl_daily_schedule(self):
        """
        Fetches upcoming or past NHL games for a given date (YYYY-MM-DD)
        Default is yesterday's date
        Returns dict with games list, or an error message if no games
        Also stores Rangers game ID if the Rangers are playing
        """
        
        # On 7 DEC I'm switching over to using 'scorboard' instead of schedule
        # So I can probably get rid of 'date' as a parameter - commented it out
        eastern = pytz.timezone("US/Eastern")

        # if date is None:
        #     date = datetime.now(eastern).strftime("%Y-%m-%d")

        nhl_url = f"{self.NHL_BASE}/scoreboard/now"

        try:
            resp = requests.get(nhl_url, timeout=10)
            resp.raise_for_status()
            nhl_data = resp.json()
            #print(json.dumps(nhl_sched_data, indent=2)[:2000])  DEBUG LINE
        except Exception as e:
            print(f"NHL API error: {e}")
            return {"games": []}
        
        now = datetime.now(eastern).date()
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        
        valid_dates = {today, yesterday}
        games = []
        
        for day in nhl_data.get("gamesByDate", []):
            day_date = day.get("date")
            if day_date not in valid_dates:
                continue
            for game in day.get("games", []):

                start_time = game.get("startTimeUTC")
                
                # Grab game and team data
                # Home and away team stubs
                home = game.get("homeTeam", {})
                away = game.get("awayTeam", {})

                # Get team names and abbreviations
                home_team = home.get("commonName", {}).get("default")
                away_team = away.get("commonName", {}).get("default")
                home_abbr = home.get("abbrev", "")
                away_abbr = away.get("abbrev", "")

                home_id = home.get("id")
                away_id = away.get("id")

                # Check for Rangers
                if home_id == self.rangers_team_id or away_id == self.rangers_team_id:
                    self.rangers_gamePk = game.get("id")

                # Score; default to 0 if not started
                home_score = int(home.get("score", 0))
                away_score = int(away.get("score", 0))

                # Period, Intermission, Clock
                period = game.get("periodDescriptor", {}).get("number")
                period_type = game.get("periodDescriptor", {}).get("periodType") 
                time_remaining = game.get("clock", {}).get("timeRemaining")
                intermission = game.get("clock", {}).get("inIntermission", False)

                # Game state
                game_state = game.get("gameState", "N/A")
                
                games.append({
                    "gamePk": game.get("id"),
                    "status": game_state,  # 11/11 changed from "status_text" to deconflict with display_utils
                    "start_time": start_time,    # raw UTC, but display_utils will format

                    "home_team": home_team,
                    "away_team": away_team,

                    "home_logo": home.get("logo", ""), # I don't think I need to pull the logo links from here, 
                    "away_logo": away.get("logo", ""), # I want to store them locally as .PNG and pull them from a folder to render
                    "home_abbr": home_abbr,
                    "away_abbr": away_abbr,

                    "home_score": home_score,
                    "away_score": away_score,

                    "period": period,
                    "period_type": period_type,
                    "time_remaining": time_remaining,
                    "intermission": intermission,

                    "league": "NHL"
                })

        # DEBUG STATEMENTS
        # print("NHL API URL:", nhl_url)
        # print("Response status:", resp.status_code)
        # print(json.dumps(resp.json(), indent=2)[:4000])

        return {"games": games}
        
    def get_rangers_live_game(self):
        """
        Fetch live Rangers game data
        Returns:
            dict when valid game data exists
            None if no gamePk is set or if the requests fails for some reason
        """
        if not self.rangers_gamePk:
            return None
        
        live_url = f"{self.NHL_BASE}/game/{self.rangers_gamePk}/feed/live"
        resp = requests.get(live_url)

        if resp.status_code != 200:
            return None
        
        rangers_live = resp.json()
        rangers_live_data = {}

        # --- Teams and Team Names ---
        home = rangers_live["gameData"]["teams"]["home"]
        away = rangers_live["gameData"]["teams"]["away"]
                
        rangers_live_data["home_team"] = home["name"]
        rangers_live_data["away_team"] = away["name"]

        # --- Scores ---
        linescore = rangers_live["liveData"]["linescore"]
        rangers_live_data["home_score"] = linescore["teams"]["home"].get("goals", 0)
        rangers_live_data["away_score"] = linescore["teams"]["away"].get("goals", 0)

        # --- Period / Time ---
        rangers_live_data["current_period"] = linescore.get("currentPeriod", None)
        rangers_live_data["period_time_remaining"] = linescore.get("currentPeriodTimeRemaining", None)

        # --- Shots on Goal ---
        rangers_live_data["shots_on_goal"] = {
            "home": linescore["teams"]["home"].get("shotsOnGoal", 0),
            "away": linescore["teams"]["away"].get("shotsOnGoal", 0),
        }

        # --- Game Status ---
        status = rangers_live.get("gameData", {}).get("status", {}).get("detailedState")
        rangers_live_data["status"] = status    # eg: "Scheduled", "In Progress", "Final"

        return rangers_live_data

    def build_nfl_team_lookup(self): 
        """Look up nfl teams to store abbreviations and logos"""
        
        url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
        resp = requests.get(url)
        
        if resp.status_code != 200:
            return {"error": f"Error fetching teams: {resp.status_code}"}
                    
        data = resp.json()
        team_lookup = {}

        for team in data.get("sports", [])[0].get("leagues", [])[0].get("teams", []):
            info = team.get("team", {})
            team_id = info.get("id")

            logos = info.get("logos", [])
            logo_url = logos[0]["href"] if logos else None

            team_lookup[team_id] = {
                "id": team_id,
                "name": info.get("displayName"),
                "abbrev": info.get("abbreviation"),
                "logo": logo_url,
                "color": info.get("color"),
                "alt_color": info.get("alternateColor"),
            }

        self.nfl_team_lookup = team_lookup
        return team_lookup

    def get_nfl_daily_schedule(self, date=None):
        """Fetches upcoming or past NFL games for a given date (YYYYMMDD)"""
        if date is None:
            date = datetime.now().strftime("%Y%m%d")
        formatted_date = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")

        url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        params = {"dates": date}
        resp = requests.get(url, params = params)

        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}"}
        
        nfl_sched_data = resp.json()
        nfl_games_summary = []

        for event in nfl_sched_data.get("events", []):
            games = event.get("competitions", [])
            if not games:
                continue

            game = games[0]

            situation = game.get("situation", {}) 
            possession_team_id = situation.get("possession")
            
            teams = game.get("competitors", [])
            
            # Initialize home/away placeholders
            home = {}
            away = {}

            # Assign home or away based on 'homeAway' within API
            for team in teams:
                if team.get("homeAway") == "home":
                    home = team
                elif team.get("homeAway") == "away":
                    away = team

            nfl_summary = {
                "home_team_id": home["team"]["id"],
                "home_abbrev": self.nfl_team_lookup.get(home["team"]["id"], {}).get("abbrev"),
                "home_logo": self.nfl_team_lookup.get(home["team"]["id"], {}).get("logo"),
                "home_score": int(home.get("score", 0) or 0),    

                "away_team_id": away["team"]["id"],
                "away_abbrev": self.nfl_team_lookup.get(away["team"]["id"], {}).get("abbrev"),
                "away_logo": self.nfl_team_lookup.get(away["team"]["id"], {}).get("logo"),
                "away_score": int(away.get("score", 0) or 0),

                "start_time": event.get("date"),
                
                "status": game["status"]["type"]["description"], # "Final", "In Progress", "Scheduled", "Halftime"
                "quarter": game["status"]["period"],
                "clock": game["status"]["displayClock"],
                "possession": self.nfl_team_lookup.get(possession_team_id, {}).get("abbrev"), # I dont think I care about possession_team_id in my dict.  Can I just code it this way?  I'm not sure how to do the if/else statement for a 'None' fallback (and is it strictly necessary?)
                "gameId": event["id"],    # This will provide a unique game ID which will be needed for live game updates

                "home_team": home["team"]["displayName"],
                "away_team": away["team"]["displayName"],
                "league": "NFL"
            }
            nfl_games_summary.append(nfl_summary)

            # Alternative block with safe-fail using .get:
            # nfl_summary = {
            #     "home_team": home.get("team", {}).get("name"),
            #     "away_team": away.get("team", {}).get("name"),
            #     "home_score": int(home.get("score", 0)) if home.get("score") else None,
            #     "away_score": int(away.get("score", 0)) if away.get("score") else None,
            #     "status": game.get("status", {}).get("type", {}).get("description"),
            #     "gameId": event.get("id")
            # }
            # nfl_games_summary.append(nfl_summary)

            if home["team"]["id"] == "8" or away["team"]["id"] == "8":  # Lions ID
                    self.lions_gameId = event.get("id")
            
        # DEBUG STATEMENTS
        # print("NFL API URL:", url)
        # print("Response status:", resp.status_code)
        # print(json.dumps(resp.json(), indent=2)[:4000])

        return {
            "date": formatted_date,
            "games": nfl_games_summary
        }

    def get_lions_live_game(self):
        """
        Fetches live game info for Lions (team ID = 8)
        Returns dictionary with error log if Lions are not currently playing
        """
        url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        resp = requests.get(url)

        if resp.status_code !=200:
            return None
        
        data = resp.json()
        for event in data.get("events", []):
            game = event["competitions"][0]
            teams = game.get("competitors", [])

            # Check if lions are playing in this game:
            if not any(t.get("team", {}).get("id") == self.lions_team_id for t in teams):
                continue

            # Save lions game ID for reference
            self.lions_gameId = event.get("id")

            # Get status and situation
            status = game.get("status", {})
            situation = game.get("situation", {})

            # To convert the raw ID to the team abbrev:
            # Get the raw team ID (for the team with ball possession)
            possession_id = situation.get("possession")

            # Resolve to team abbrev using the nfl_team_lookup
            possession_team = None
            if possession_id and possession_id in self.nfl_team_lookup:
                possession_team = self.nfl_team_lookup[possession_id]["abbrev"]
            else:
                possession_team = possession_id

            game_summary = {
                "quarter": status.get("period"),
                "clock": status.get("displayClock"),
                "status_desc": status.get("type", {}).get("description"),
                "scores": {
                    t["team"]["abbreviation"]: int(t["score"]) if t.get("score") else 0
                    for t in teams
                },
                "possession": possession_team,  
                "down": situation.get("down"),
                "distance": situation.get("distance"),
                "yardLine": situation.get("yardLine"),
            }

            return game_summary
        
        return None
    
    def get_mlb_daily_schedule(self, date=None):
        """Fetches upcoming or past MLB games for a given date (YYYY-MM-DD)"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")  # Defaults to today
            
        mlb_url = f"{self.MLB_BASE}/schedule"
        params = {
            "sportId": 1,       # 1 = Major League Baseball
            "date": date,
            "language": "en"    # This is option, just ensures English results
        }

        resp = requests.get(mlb_url, params=params)

        # Check if the request was successful (can probably delete after verifying)
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}"}
        
        data = resp.json()

        # Following section is to extract just the games with teams and scores
        mlb_games_summary = []
        for date in data.get("dates", []):
            for game in date.get("games", []):
                home = game["teams"]["home"]
                away = game["teams"]["away"]

                utc = pytz.utc
                est = pytz.timezone("US/Eastern")
                
                start_time_utc = datetime.fromisoformat(game["gameDate"].replace("Z", "+00:00"))
                start_time_local = start_time_utc.astimezone(est)
                if game["status"]["detailedState"] == "Scheduled":
                    try:
                        status_text = start_time_local.strftime("%-I:%M %p %Z")
                    except ValueError:
                        status_text = start_time_local.strftime("%#I:%M %p %Z")
                else:
                    status_text = game["status"]["detailedState"]

                mlb_summary = {
                    "home_team": home["team"]["name"],
                    "away_team": away["team"]["name"],
                    "home_score": home.get("score") or 0,    # May be None if the game has not started
                    "away_score": away.get("score") or 0,
                    "status": status_text, # such as: "Final", "In Progress", "Scheduled"
                    "gamePk": game["gamePk"],    # This will provide a unique game ID which will be needed for live game updates
                    "league": "MLB"
                }
                mlb_games_summary.append(mlb_summary)

                if mlb_summary["home_team"] == "New York Yankees" or mlb_summary["away_team"] == "New York Yankees":
                    self.yankees_gamePk = game["gamePk"]
            
        #print(json.dumps(games_summary, indent=2))
        return {
            "date": date,
            "games": mlb_games_summary
        }
              
    def get_yankees_live_game(self):
        """Fetch live Yankees game data"""
        if not self.yankees_gamePk:
            return None
        
        live_url = f"{self.MLB_BASE}/game/{self.yankees_gamePk}/feed/live"
        resp = requests.get(live_url)

        if resp.status_code !=200:
            return None
        
        yankees_live = resp.json()

        # Empty dictionary to fill with the parsed data
        yankees_live_data = {}

        # --- Teams ---
            # Trunk
        home = yankees_live["gameData"]["teams"]["home"]
        away = yankees_live["gameData"]["teams"]["away"]
                
            # Team names
        yankees_live_data["home_team"] = home["name"]
        yankees_live_data["away_team"] = away["name"]

        # --- Runs / Hits / Errors ---
            # Trunk
        linescore = yankees_live["liveData"]["linescore"]

        yankees_live_data["home_score"] = linescore["teams"]["home"].get("runs", None)
        yankees_live_data["away_score"] = linescore["teams"]["away"].get("runs", None)

        # --- Balls, Strikes, Outs ---
            # Trunk
        count = yankees_live["liveData"]["plays"].get("currentPlay", {}).get("count", "-")
        yankees_live_data["balls"] = count.get("balls", 0)
        yankees_live_data["strikes"] = count.get("strikes", 0)
        yankees_live_data["outs"] = count.get("outs", 0)

        # Inning info
        yankees_live_data["inning"] = linescore.get("currentInning", None)
        yankees_live_data["inning_half"] = linescore.get("inningState", "")

        # Pitcher & batter
            # Trunk
        matchup = yankees_live["liveData"]["plays"].get("currentPlay", {}).get("matchup", {})
        pitcher_id = matchup.get("pitcher", {}).get("id", None)
        batter_id = matchup.get("batter", {}).get("id", None)

        # Convert to first initial, full lastname
        def _format_name(player_obj):
            first = player_obj.get("firstName", "")
            last = player_obj.get("lastName", "")
            return f"{first[0]}. {last}" if first and last else last
        
        yankees_live_data["current pitcher"] = _format_name(yankees_live["gameData"]["players"][f"ID{pitcher_id}"])
        yankees_live_data["current batter"] = _format_name(yankees_live["gameData"]["players"][f"ID{batter_id}"])

        # --- Bases ---
            # Trunk
        offense = linescore.get("offense", {})
        yankees_live_data["bases"] = {
            "first": bool(offense.get("first")),
            "second": bool(offense.get("second")),
            "third": bool(offense.get("third")),
        }

        # Runs / hits / errors home team
        yankees_live_data["home_stats"] = {
            "runs": linescore["teams"]["home"].get("runs", 0),
            "hits": linescore["teams"]["home"].get("hits", 0),
            "errors": linescore["teams"]["home"].get("errors", 0),
        }
        
        # Runs / hits / errors away team
        yankees_live_data["away_stats"] = {
            "runs": linescore["teams"]["away"].get("runs", 0),
            "hits": linescore["teams"]["away"].get("hits", 0),
            "errors": linescore["teams"]["away"].get("errors", 0),
        }

        # --- Per-inning box scores for live display ---
        innings_data = linescore.get("innings", [])
        yankees_live_data["per_inning"] = []    # Initializing a key/list-value pair for innings data

        for inning in innings_data:
            yankees_live_data["per_inning"].append({
                "inning": inning.get("num"),
                "home": inning.get("home", {}).get("runs", None),
                "away": inning.get("away", {}).get("runs", None),
            })

        return yankees_live_data

        #return resp.json()
    
        #print(json.dumps(live_data, indent=2))
    
# testfetch = DataFetcher()
# print(testfetch.get_nhl_daily_schedule())
#testfetch.get_mlb_daily_schedule()
#print(testfetch.yankees_gamePk)
#print(testfetch.get_yankees_live_game())
#testfetch.build_nfl_team_lookup()
#print(testfetch.nfl_team_lookup["8"])
#games = testfetch.get_nfl_daily_schedule()
#print(testfetch.nfl_games_summary)
#lions = testfetch.get_lions_live_games()
#pprint(lions)
#print(json.dumps(lions, indent=2))